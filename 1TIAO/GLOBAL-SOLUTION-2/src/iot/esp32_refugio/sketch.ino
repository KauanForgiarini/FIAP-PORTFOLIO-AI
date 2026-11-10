/*
 * Refúgio - Estação de calor comunitária (ESP32 + DHT22) - simulada no Wokwi
 * ---------------------------------------------------------------------------
 * O que faz:
 *  - Mede temperatura e umidade do ar (DHT22) a cada 5 s.
 *  - Calcula a SENSAÇÃO TÉRMICA (índice de calor da NOAA) no próprio
 *    dispositivo (edge computing), para funcionar mesmo sem internet.
 *  - Mostra os valores e o nível de risco no display LCD e nos LEDs:
 *      verde = normal | amarelo = atenção | vermelho = alerta | vermelho + bip = perigo
 *  - Botão vermelho "PEDIR AJUDA": a pessoa idosa aperta e o pedido segue para o cuidador.
 *  - Publica cada leitura via MQTT sobre TLS (porta 8883), com verificação do
 *    certificado do servidor (Amazon Root CA 1, a mesma cadeia do AWS IoT Core).
 *  - Assina cada mensagem com HMAC-SHA256: o servidor rejeita mensagens falsas,
 *    adulteradas ou repetidas (o broker de demonstração é público).
 *
 * Dados SIMULADOS: no Wokwi, clique no DHT22 durante a simulação e arraste a
 * temperatura/umidade para reproduzir uma tarde de calor.
 *
 * Bibliotecas (libraries.txt): DHT sensor library for ESPx, PubSubClient,
 * LiquidCrystal I2C, ArduinoJson
 */
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <DHTesp.h>
#include <LiquidCrystal_I2C.h>
#include <time.h>
#include "mbedtls/md.h"

#if __has_include("secrets.h")
#include "secrets.h"            // segredo real (fora do Git) - veja secrets.h.example
#else
#define HMAC_SEGREDO "demo-troque-este-segredo"   // apenas demonstração
#endif

// ----------------------------------------------------------------- configuração
const char* WIFI_SSID   = "Wokwi-GUEST";
const char* WIFI_SENHA  = "";
const char* MQTT_HOST   = "broker.hivemq.com";   // em produção: <endpoint>.iot.<regiao>.amazonaws.com
const uint16_t MQTT_PORTA = 8883;
const char* SENSOR_ID   = "ESP32-SM-01";
const char* TOPICO      = "refugio/santamaria/ESP32-SM-01/leituras";
const uint32_t INTERVALO_MS = 5000;

const int PINO_DHT = 15, LED_VERDE = 25, LED_AMARELO = 26, LED_VERMELHO = 27, PINO_BUZZER = 14, PINO_BOTAO = 4;

// Raiz da cadeia de certificados do broker (e do AWS IoT Core)
static const char AMAZON_ROOT_CA1[] PROGMEM = R"EOF(
-----BEGIN CERTIFICATE-----
MIIDQTCCAimgAwIBAgITBmyfz5m/jAo54vB4ikPmljZbyjANBgkqhkiG9w0BAQsF
ADA5MQswCQYDVQQGEwJVUzEPMA0GA1UEChMGQW1hem9uMRkwFwYDVQQDExBBbWF6
b24gUm9vdCBDQSAxMB4XDTE1MDUyNjAwMDAwMFoXDTM4MDExNzAwMDAwMFowOTEL
MAkGA1UEBhMCVVMxDzANBgNVBAoTBkFtYXpvbjEZMBcGA1UEAxMQQW1hem9uIFJv
b3QgQ0EgMTCCASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBALJ4gHHKeNXj
ca9HgFB0fW7Y14h29Jlo91ghYPl0hAEvrAIthtOgQ3pOsqTQNroBvo3bSMgHFzZM
9O6II8c+6zf1tRn4SWiw3te5djgdYZ6k/oI2peVKVuRF4fn9tBb6dNqcmzU5L/qw
IFAGbHrQgLKm+a/sRxmPUDgH3KKHOVj4utWp+UhnMJbulHheb4mjUcAwhmahRWa6
VOujw5H5SNz/0egwLX0tdHA114gk957EWW67c4cX8jJGKLhD+rcdqsq08p8kDi1L
93FcXmn/6pUCyziKrlA4b9v7LWIbxcceVOF34GfID5yHI9Y/QCB/IIDEgEw+OyQm
jgSubJrIqg0CAwEAAaNCMEAwDwYDVR0TAQH/BAUwAwEB/zAOBgNVHQ8BAf8EBAMC
AYYwHQYDVR0OBBYEFIQYzIU07LwMlJQuCFmcx7IQTgoIMA0GCSqGSIb3DQEBCwUA
A4IBAQCY8jdaQZChGsV2USggNiMOruYou6r4lK5IpDB/G/wkjUu0yKGX9rbxenDI
U5PMCCjjmCXPI6T53iHTfIUJrU6adTrCC2qJeHZERxhlbI1Bjjt/msv0tadQ1wUs
N+gDS63pYaACbvXy8MWy7Vu33PqUXHeeE6V/Uq2V8viTO96LXFvKWlJbYK8U90vv
o/ufQJVtMVT8QtPHRh8jrdkPSHCa2XV4cdFyQzR1bldZwgJcJmApzyMZFo6IQ6XU
5MsI+yMRQ+hDKXJioaldXgjUkK642M4UwtBV8ob2xJNDd2ZhwLnoQdeXeGADbkpy
rqXRfboQnoZsG4q5WTP468SQvvG5
-----END CERTIFICATE-----
)EOF";

DHTesp dht;
LiquidCrystal_I2C lcd(0x27, 16, 2);
WiFiClientSecure tls;
PubSubClient mqtt(tls);

volatile bool pedidoAjuda = false;
uint32_t ultimoEnvio = 0;

void IRAM_ATTR aoApertarBotao() { pedidoAjuda = true; }

// ---------------------------------------------------- índice de calor (NOAA)
float indiceCalorC(float tC, float ur) {
  float t = tC * 9.0f / 5.0f + 32.0f;
  float hi = 0.5f * (t + 61.0f + (t - 68.0f) * 1.2f + ur * 0.094f);
  if ((hi + t) / 2.0f >= 80.0f) {
    hi = -42.379f + 2.04901523f * t + 10.14333127f * ur - 0.22475541f * t * ur
         - 0.00683783f * t * t - 0.05481717f * ur * ur + 0.00122874f * t * t * ur
         + 0.00085282f * t * ur * ur - 0.00000199f * t * t * ur * ur;
    if (ur < 13 && t >= 80 && t <= 112) hi -= ((13 - ur) / 4) * sqrtf((17 - fabsf(t - 95)) / 17);
    else if (ur > 85 && t >= 80 && t <= 87) hi += ((ur - 85) / 10) * ((87 - t) / 5);
  }
  return (hi - 32.0f) * 5.0f / 9.0f;
}

const char* nivelRisco(float ic) {
  if (ic < 27) return "normal";
  if (ic < 32) return "atencao";
  if (ic < 41) return "alerta";
  return "perigo";
}

// ---------------------------------------------------- HMAC-SHA256 (mbedTLS)
String hmacSha256(const char* chave, const char* msg) {
  uint8_t saida[32];
  mbedtls_md_context_t ctx;
  mbedtls_md_init(&ctx);
  mbedtls_md_setup(&ctx, mbedtls_md_info_from_type(MBEDTLS_MD_SHA256), 1);
  mbedtls_md_hmac_starts(&ctx, (const unsigned char*)chave, strlen(chave));
  mbedtls_md_hmac_update(&ctx, (const unsigned char*)msg, strlen(msg));
  mbedtls_md_hmac_finish(&ctx, saida);
  mbedtls_md_free(&ctx);
  char hex[65];
  for (int i = 0; i < 32; i++) sprintf(hex + 2 * i, "%02x", saida[i]);
  hex[64] = '\0';
  return String(hex);
}

// ---------------------------------------------------- saídas locais
void atualizarIndicadores(const char* nivel) {
  bool normal = !strcmp(nivel, "normal"), atencao = !strcmp(nivel, "atencao");
  digitalWrite(LED_VERDE, normal);
  digitalWrite(LED_AMARELO, atencao);
  digitalWrite(LED_VERMELHO, !normal && !atencao);
  if (!strcmp(nivel, "perigo")) tone(PINO_BUZZER, 2000, 300);
}

void mostrarLcd(float t, float u, float ic, const char* nivel, bool online) {
  char l1[17], l2[17];
  snprintf(l1, sizeof(l1), "T%4.1fC UR%3.0f%% %c", t, u, online ? '*' : '!');
  String n = String(nivel);
  n.toUpperCase();
  snprintf(l2, sizeof(l2), "Sens%4.1fC %-6s", ic, n.c_str());
  lcd.setCursor(0, 0); lcd.print(l1);
  lcd.setCursor(0, 1); lcd.print(l2);
}

// ---------------------------------------------------- conectividade
void conectarWifi() {
  WiFi.begin(WIFI_SSID, WIFI_SENHA, 6);
  Serial.print("WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(250); Serial.print("."); }
  Serial.println(" conectado");
  configTime(0, 0, "pool.ntp.org", "time.google.com");   // relógio para o número de sequência
  time_t agora = 0;
  while (agora < 1700000000) { delay(200); time(&agora); }
  Serial.printf("Relogio sincronizado: %ld\n", (long)agora);
}

bool conectarMqtt() {
  if (mqtt.connected()) return true;
  String idCliente = String(SENSOR_ID) + "-" + String((uint32_t)ESP.getEfuseMac(), HEX);
  Serial.printf("MQTT %s:%d (TLS)... ", MQTT_HOST, MQTT_PORTA);
  bool ok = mqtt.connect(idCliente.c_str());
  Serial.println(ok ? "ok" : "falhou");
  return ok;
}

void publicar(float t, float u, float ic, const char* nivel, bool sos) {
  // valores arredondados a 1 casa, exatamente como entram na assinatura
  String st = String(t, 1), su = String(u, 1), sic = String(ic, 1);
  uint32_t seq = (uint32_t)time(nullptr);
  char canonico[128];
  snprintf(canonico, sizeof(canonico), "%s|%lu|%s|%s|%s|%s|%d",
           SENSOR_ID, (unsigned long)seq, st.c_str(), su.c_str(), sic.c_str(), nivel, sos ? 1 : 0);

  JsonDocument doc;
  doc["id"] = SENSOR_ID;
  doc["seq"] = seq;
  doc["t"] = serialized(st);
  doc["u"] = serialized(su);
  doc["ic"] = serialized(sic);
  doc["nivel"] = nivel;
  doc["sos"] = sos ? 1 : 0;
  doc["sim"] = 1;                       // leitura simulada (Wokwi)
  doc["sig"] = hmacSha256(HMAC_SEGREDO, canonico);
  char payload[320];
  serializeJson(doc, payload, sizeof(payload));
  bool ok = mqtt.publish(TOPICO, payload);
  Serial.printf("%s %s\n", ok ? "->" : "xx", payload);
}

// ---------------------------------------------------- setup / loop
void setup() {
  Serial.begin(115200);
  pinMode(LED_VERDE, OUTPUT); pinMode(LED_AMARELO, OUTPUT); pinMode(LED_VERMELHO, OUTPUT);
  pinMode(PINO_BUZZER, OUTPUT);
  pinMode(PINO_BOTAO, INPUT_PULLUP);
  attachInterrupt(digitalPinToInterrupt(PINO_BOTAO), aoApertarBotao, FALLING);
  dht.setup(PINO_DHT, DHTesp::DHT22);
  lcd.init(); lcd.backlight();
  lcd.print("Refugio SM"); lcd.setCursor(0, 1); lcd.print("conectando...");

  conectarWifi();
  tls.setCACert(AMAZON_ROOT_CA1);       // valida o certificado do servidor (sem setInsecure!)
  mqtt.setServer(MQTT_HOST, MQTT_PORTA);
  mqtt.setBufferSize(512);
  mqtt.setKeepAlive(30);
  conectarMqtt();
  lcd.clear();
}

void loop() {
  mqtt.loop();
  bool sos = pedidoAjuda;
  if (!sos && millis() - ultimoEnvio < INTERVALO_MS) return;
  ultimoEnvio = millis();
  pedidoAjuda = false;

  TempAndHumidity d = dht.getTempAndHumidity();
  if (isnan(d.temperature) || isnan(d.humidity)) {
    Serial.println("Falha na leitura do DHT22");
    return;
  }
  float ic = indiceCalorC(d.temperature, d.humidity);
  const char* nivel = nivelRisco(ic);
  atualizarIndicadores(nivel);
  bool online = conectarMqtt();
  mostrarLcd(d.temperature, d.humidity, ic, nivel, online);
  if (sos) {
    lcd.setCursor(0, 1); lcd.print("AJUDA SOLICITADA");
    tone(PINO_BUZZER, 1000, 800);
  }
  if (online) publicar(d.temperature, d.humidity, ic, nivel, sos);
}

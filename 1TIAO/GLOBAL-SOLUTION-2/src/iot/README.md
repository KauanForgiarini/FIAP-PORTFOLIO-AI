# IoT – Estação de calor comunitária (ESP32 no Wokwi)

> ⚠️ **Sensor simulado.** O grupo não tem um ESP32 físico. O circuito roda no simulador
> [Wokwi](https://wokwi.com), mas a **conexão com a internet e com o servidor é real**.

## O circuito

| Componente | Pino ESP32 | Função |
|---|---|---|
| DHT22 | GPIO 15 | Temperatura e umidade do ar |
| LCD 16x2 I2C | SDA 21 / SCL 22 | Mostra temperatura, umidade, sensação térmica e nível |
| LED verde / amarelo / vermelho | 25 / 26 / 27 (com resistor de 220 Ω) | Nível: normal / atenção / alerta-perigo |
| Buzzer | GPIO 14 | Bipa no nível "perigo" e no pedido de ajuda |
| Botão vermelho "PEDIR AJUDA" | GPIO 4 (pull-up interno) | A pessoa idosa pede ajuda e o cuidador é avisado |

## Lógica

1. A cada 5 s, o ESP32 lê o DHT22 e calcula a **sensação térmica** (índice de calor da NOAA) no
   próprio dispositivo. Os LEDs e o display funcionam mesmo sem internet (*edge computing*).
2. A leitura é publicada via **MQTT sobre TLS** (porta 8883) no tópico
   `refugio/santamaria/ESP32-SM-01/leituras`.
3. A **ponte** (`src/iot/ponte_mqtt.py`) valida cada mensagem, grava no banco e, se configurado,
   envia para a AWS (DynamoDB). Leituras em "alerta" ou "perigo" e pedidos de ajuda acionam o
   assistente de alertas.

### Níveis (índice de calor, faixas do NWS/NOAA em °C)

| Sensação térmica | Nível | LEDs |
|---|---|---|
| < 27 °C | normal | verde |
| 27 – 32 °C | atenção | amarelo |
| 32 – 41 °C | alerta | vermelho |
| ≥ 41 °C | perigo | vermelho + bipe |

## Segurança (cibersegurança)

O broker de demonstração (`broker.hivemq.com`) é **público**, então tratamos o canal como não
confiável:

- **Confidencialidade:** TLS com **verificação do certificado** do servidor (Amazon Root CA 1,
  sem `setInsecure()`). Essa é a mesma cadeia usada pelo AWS IoT Core.
- **Autenticidade e integridade:** cada mensagem leva uma assinatura **HMAC-SHA256** com um segredo
  que só o sensor e a ponte conhecem (`secrets.h` e `.env`, fora do Git).
- **Anti-replay:** o campo `seq` usa o horário NTP e precisa sempre crescer. Mensagens repetidas
  são descartadas.
- **Validação de entrada:** a ponte aceita só sensores cadastrados e valores fisicamente plausíveis.
- **Privacidade:** as mensagens não contêm dados pessoais.

**Teste realizado:** a ponte recebeu 8 leituras válidas e **rejeitou** uma mensagem adulterada
depois de assinada ("assinatura inválida") e uma mensagem reenviada ("replay"). Veja
`python -m src.iot.ponte_mqtt --simular 8 --duracao 10`.

**Em produção:** trocar o broker público pelo **AWS IoT Core** com certificado X.509 por dispositivo
(TLS mútuo) e políticas de IoT que permitem a cada sensor publicar somente no próprio tópico.

## Como rodar no Wokwi

1. Acesse <https://wokwi.com/projects/new/esp32>.
2. Substitua o conteúdo de `sketch.ino` e `diagram.json` pelos arquivos desta pasta.
3. No **Library Manager**, adicione as bibliotecas de `libraries.txt`.
4. (Opcional) Crie uma aba `secrets.h` copiando `secrets.h.example` com o seu segredo.
5. Clique em ▶️. Durante a simulação, clique no DHT22 e arraste a temperatura (ex.: de 30 °C
   para 38 °C) para simular a tarde de calor. Aperte o botão vermelho para pedir ajuda.
6. Em outro terminal, rode a ponte: `python -m src.iot.ponte_mqtt`.

Sem Wokwi, dá para testar só a ponte com o emulador em Python: `python -m src.iot.ponte_mqtt --simular 20`.

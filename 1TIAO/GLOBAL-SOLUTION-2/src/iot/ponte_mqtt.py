"""Ponte MQTT -> banco de dados (e, opcionalmente, AWS).

Assina o tópico dos sensores, valida cada mensagem (ver protocolo.py), grava
as leituras no SQLite (tabela leitura_sensor) e, se configurado, envia para a
nuvem AWS (DynamoDB). Leituras em nível "alerta" ou "perigo" disparam o fluxo
de alerta (registrado no banco; o assistente de IA gera a mensagem).

Uso:
    python -m src.iot.ponte_mqtt                 # escuta o broker (Ctrl+C para sair)
    python -m src.iot.ponte_mqtt --simular 20    # também publica 20 leituras simuladas (sem Wokwi)

Configuração (.env): REFUGIO_HMAC_SEGREDO, REFUGIO_MQTT_HOST (padrão broker.hivemq.com),
REFUGIO_DYNAMO_TABELA (opcional - ativa o envio para AWS), AWS_REGION.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import ssl
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import paho.mqtt.client as mqtt
from dotenv import load_dotenv

from src import config as C
from src.iot.protocolo import TOPICO_BASE, Validador, montar_mensagem

load_dotenv(C.RAIZ / ".env")
HOST = os.environ.get("REFUGIO_MQTT_HOST", "broker.hivemq.com")
PORTA = int(os.environ.get("REFUGIO_MQTT_PORTA", "8883"))
# Raiz da cadeia do broker HiveMQ e também do AWS IoT Core
CA = Path(__file__).parent / "certs_publicos" / "AmazonRootCA1.crt"
DB = C.PROCESSED / "refugio.db"


def sensores_autorizados() -> set[str]:
    with sqlite3.connect(DB) as con:
        return {r[0] for r in con.execute("SELECT id_sensor FROM sensor")}


def gravar_leitura(m: dict) -> None:
    with sqlite3.connect(DB) as con:
        con.execute("INSERT INTO leitura_sensor (id_sensor, data_hora, temperatura_c, umidade_pct, indice_calor_c, simulado)"
                    " VALUES (?,?,?,?,?,?)",
                    (m["id"], datetime.now(timezone.utc).isoformat(timespec="seconds"), m["t"], m["u"], m["ic"],
                     int(m.get("sim", 1))))


def enviar_aws(m: dict) -> None:
    tabela = os.environ.get("REFUGIO_DYNAMO_TABELA")
    if not tabela:
        return
    import boto3
    from decimal import Decimal
    boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1")).Table(tabela).put_item(Item={
        "id_sensor": m["id"], "seq": int(m["seq"]), "data_hora": datetime.now(timezone.utc).isoformat(),
        "temperatura_c": Decimal(str(m["t"])), "umidade_pct": Decimal(str(m["u"])),
        "indice_calor_c": Decimal(str(m["ic"])), "nivel": m["nivel"], "simulado": int(m.get("sim", 1))})


def criar_cliente(nome: str) -> mqtt.Client:
    cli = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{nome}-{os.getpid()}")
    cli.tls_set(ca_certs=str(CA), tls_version=ssl.PROTOCOL_TLS_CLIENT)  # verifica o certificado do broker
    return cli


def escutar(simular: int = 0, duracao: float | None = None) -> dict:
    validador = Validador(sensores_autorizados())
    estat = {"recebidas": 0, "aceitas": 0, "rejeitadas": {}, "alertas": 0}
    pronto = threading.Event()

    def on_connect(cli, userdata, flags, rc, props=None):
        cli.subscribe(f"{TOPICO_BASE}/+/leituras", qos=1)
        print(f"Conectado a {HOST}:{PORTA} (TLS) - escutando {TOPICO_BASE}/+/leituras")
        pronto.set()

    def on_message(cli, userdata, msg):
        estat["recebidas"] += 1
        try:
            m = json.loads(msg.payload.decode())
        except (UnicodeDecodeError, json.JSONDecodeError):
            ok, motivo = False, "JSON inválido"
        else:
            ok, motivo = validador.validar(m)
        if not ok:
            estat["rejeitadas"][motivo] = estat["rejeitadas"].get(motivo, 0) + 1
            print(f"  ✗ rejeitada ({motivo})")
            return
        estat["aceitas"] += 1
        gravar_leitura(m)
        enviar_aws(m)
        marca = "⚠️ " if m["nivel"] in ("alerta", "perigo") else "  "
        if int(m.get("sos", 0)):
            marca = "🆘 PEDIDO DE AJUDA - "
            estat["sos"] = estat.get("sos", 0) + 1
        if marca.strip():
            estat["alertas"] += 1
        print(f"{marca}{m['id']} seq={m['seq']} T={m['t']}°C UR={m['u']}% sensação={m['ic']}°C nível={m['nivel']}"
              f"{' (simulado)' if m.get('sim') else ''}")

    cli = criar_cliente("refugio-ponte")
    cli.on_connect, cli.on_message = on_connect, on_message
    cli.connect(HOST, PORTA, keepalive=30)
    cli.loop_start()
    pronto.wait(20)
    if simular:
        publicar_simulado(simular)
    try:
        if duracao is not None:
            time.sleep(duracao)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    cli.loop_stop()
    cli.disconnect()
    return estat


def publicar_simulado(n: int, sensor: str = "ESP32-SM-01") -> None:
    """Emula o ESP32 (dados SIMULADOS): uma tarde que esquenta até ~38 °C."""
    pub = criar_cliente("refugio-simulador")
    pub.connect(HOST, PORTA, keepalive=30)
    pub.loop_start()
    limite = time.time() + 20
    while not pub.is_connected() and time.time() < limite:
        time.sleep(0.2)
    if not pub.is_connected():
        raise ConnectionError(f"Simulador não conectou a {HOST}:{PORTA}")
    seq0 = int(time.time())
    for i in range(n):
        temp = 29 + 9 * i / max(1, n - 1)
        umid = 60 - 20 * i / max(1, n - 1)
        m = montar_mensagem(sensor, seq0 + i, temp, umid, simulado=True)
        pub.publish(f"{TOPICO_BASE}/{sensor}/leituras", json.dumps(m), qos=1).wait_for_publish(10)
        time.sleep(0.3)
    # duas mensagens maliciosas para demonstrar a validação
    falsa = montar_mensagem(sensor, seq0 + n, 45, 30)
    falsa["t"] = 20.0  # adulterada depois de assinada
    pub.publish(f"{TOPICO_BASE}/{sensor}/leituras", json.dumps(falsa), qos=1).wait_for_publish(10)
    replay = montar_mensagem(sensor, seq0, 30, 50)
    pub.publish(f"{TOPICO_BASE}/{sensor}/leituras", json.dumps(replay), qos=1).wait_for_publish(10)
    pub.loop_stop()
    pub.disconnect()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--simular", type=int, default=0, help="publica N leituras simuladas")
    ap.add_argument("--duracao", type=float, default=None, help="segundos escutando (padrão: até Ctrl+C)")
    a = ap.parse_args()
    print(escutar(a.simular, a.duracao))

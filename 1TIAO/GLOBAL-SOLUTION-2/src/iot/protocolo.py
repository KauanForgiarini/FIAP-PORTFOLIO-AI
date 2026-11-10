"""Protocolo de mensagens dos sensores Refúgio (mesma lógica do firmware do ESP32).

Mensagem publicada pelo sensor no tópico  refugio/santamaria/<id>/leituras :
    {"id": "ESP32-SM-01", "seq": 1794116649, "t": 36.5, "u": 48.0, "ic": 39.1,
     "nivel": "alerta", "sos": 0, "sim": 1, "sig": "<hmac-sha256 hex>"}

    seq  = horário Unix (NTP) do envio: sempre crescente, mesmo após reiniciar o sensor
    sos  = 1 quando a pessoa idosa aperta o botão de pedido de ajuda
    texto assinado = "id|seq|t|u|ic|nivel|sos" (números com 1 casa decimal)

Segurança (o broker de demonstração é público, então qualquer um pode publicar):
- Autenticidade e integridade: assinatura HMAC-SHA256 com segredo compartilhado
  entre o sensor e a ponte (variável REFUGIO_HMAC_SEGREDO / secrets.h).
- Anti-replay: o número de sequência `seq` precisa ser sempre crescente por sensor.
- Validação: lista de sensores autorizados e faixas físicas plausíveis.
- Confidencialidade: TLS (porta 8883) com verificação do certificado da CA do broker.
- Privacidade: a mensagem não contém nenhum dado pessoal.
"""
from __future__ import annotations

import hashlib
import hmac
import os

TOPICO_BASE = "refugio/santamaria"
NIVEIS = ("normal", "atencao", "alerta", "perigo")


def segredo() -> bytes:
    s = os.environ.get("REFUGIO_HMAC_SEGREDO")
    if not s:
        s = "demo-troque-este-segredo"  # mesmo valor de secrets.h.example (apenas demonstração)
    return s.encode()


def indice_calor_c(temp_c: float, umid: float) -> float:
    """Índice de calor (sensação térmica) - regressão de Rothfusz, NOAA/NWS."""
    t = temp_c * 9 / 5 + 32
    hi = 0.5 * (t + 61.0 + (t - 68.0) * 1.2 + umid * 0.094)
    if (hi + t) / 2 >= 80:
        hi = (-42.379 + 2.04901523 * t + 10.14333127 * umid - 0.22475541 * t * umid
              - 0.00683783 * t * t - 0.05481717 * umid * umid + 0.00122874 * t * t * umid
              + 0.00085282 * t * umid * umid - 0.00000199 * t * t * umid * umid)
        if umid < 13 and 80 <= t <= 112:
            hi -= ((13 - umid) / 4) * ((17 - abs(t - 95)) / 17) ** 0.5
        elif umid > 85 and 80 <= t <= 87:
            hi += ((umid - 85) / 10) * ((87 - t) / 5)
    return (hi - 32) * 5 / 9


def nivel_risco(ic_c: float) -> str:
    """Faixas do NWS convertidas para °C: <27 normal | 27-32 atenção | 32-41 alerta | >=41 perigo."""
    if ic_c < 27:
        return "normal"
    if ic_c < 32:
        return "atencao"
    if ic_c < 41:
        return "alerta"
    return "perigo"


def texto_canonico(m: dict) -> str:
    return (f"{m['id']}|{int(m['seq'])}|{float(m['t']):.1f}|{float(m['u']):.1f}|{float(m['ic']):.1f}|{m['nivel']}"
            f"|{int(m.get('sos', 0))}")


def assinar(m: dict) -> str:
    return hmac.new(segredo(), texto_canonico(m).encode(), hashlib.sha256).hexdigest()


def montar_mensagem(sensor_id: str, seq: int, temp: float, umid: float, simulado: bool = True,
                    sos: bool = False) -> dict:
    ic = indice_calor_c(temp, umid)
    m = {"id": sensor_id, "seq": seq, "t": round(temp, 1), "u": round(umid, 1), "ic": round(ic, 1),
         "nivel": nivel_risco(ic), "sos": int(sos), "sim": int(simulado)}
    m["sig"] = assinar(m)
    return m


class Validador:
    """Valida mensagens recebidas: assinatura, sensor autorizado, anti-replay e faixas físicas."""

    def __init__(self, sensores_autorizados: set[str]):
        self.autorizados = sensores_autorizados
        self.ultimo_seq: dict[str, int] = {}

    def validar(self, m: dict) -> tuple[bool, str]:
        campos = {"id", "seq", "t", "u", "ic", "nivel", "sig"}
        if not isinstance(m, dict) or not campos <= m.keys():
            return False, "formato inválido"
        if m["id"] not in self.autorizados:
            return False, "sensor não autorizado"
        try:
            esperado = assinar(m)
        except (TypeError, ValueError, KeyError):
            return False, "campos com tipo inválido"
        if not hmac.compare_digest(esperado, str(m["sig"])):
            return False, "assinatura inválida"
        if int(m["seq"]) <= self.ultimo_seq.get(m["id"], -1):
            return False, "mensagem repetida (replay)"
        if not (-20 <= float(m["t"]) <= 70 and 0 <= float(m["u"]) <= 100) or m["nivel"] not in NIVEIS:
            return False, "valores fora da faixa física"
        self.ultimo_seq[m["id"]] = int(m["seq"])
        return True, "ok"

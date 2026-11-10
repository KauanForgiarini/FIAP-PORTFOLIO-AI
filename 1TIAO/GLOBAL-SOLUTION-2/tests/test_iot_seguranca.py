"""Testes de segurança e de cálculo do protocolo dos sensores (sem rede)."""
from src.iot.protocolo import Validador, indice_calor_c, montar_mensagem, nivel_risco


def test_indice_de_calor_bate_com_tabela_da_noaa():
    # Tabela do NWS: 32 °C (90 °F) com 50% de umidade -> sensação ~ 35 °C (95 °F)
    assert abs(indice_calor_c(32.2, 50) - 35.0) < 1.0
    # sem calor, o índice fica próximo da temperatura
    assert abs(indice_calor_c(22, 50) - 22) < 1.5


def test_niveis_de_risco():
    assert [nivel_risco(x) for x in (25, 30, 35, 45)] == ["normal", "atencao", "alerta", "perigo"]


def test_mensagem_legitima_e_aceita():
    v = Validador({"ESP32-SM-01"})
    ok, motivo = v.validar(montar_mensagem("ESP32-SM-01", 100, 36.0, 40.0))
    assert ok, motivo


def test_mensagem_adulterada_e_rejeitada():
    v = Validador({"ESP32-SM-01"})
    m = montar_mensagem("ESP32-SM-01", 100, 36.0, 40.0)
    m["t"] = 22.0
    assert v.validar(m) == (False, "assinatura inválida")


def test_pedido_de_ajuda_forjado_e_rejeitado():
    v = Validador({"ESP32-SM-01"})
    m = montar_mensagem("ESP32-SM-01", 100, 30.0, 50.0)
    m["sos"] = 1  # invasor tenta disparar um falso pedido de ajuda
    assert v.validar(m)[0] is False


def test_replay_e_rejeitado():
    v = Validador({"ESP32-SM-01"})
    m = montar_mensagem("ESP32-SM-01", 100, 30.0, 50.0)
    assert v.validar(m)[0]
    assert v.validar(dict(m)) == (False, "mensagem repetida (replay)")


def test_sensor_desconhecido_e_rejeitado():
    v = Validador({"ESP32-SM-01"})
    assert v.validar(montar_mensagem("INVASOR", 1, 30, 50)) == (False, "sensor não autorizado")


def test_payload_malformado_nao_derruba_a_ponte():
    v = Validador({"ESP32-SM-01"})
    assert v.validar({"id": "ESP32-SM-01"})[0] is False
    assert v.validar(["lista"])[0] is False
    m = montar_mensagem("ESP32-SM-01", 5, 30, 50)
    m["t"] = "abc"
    assert v.validar(m)[0] is False

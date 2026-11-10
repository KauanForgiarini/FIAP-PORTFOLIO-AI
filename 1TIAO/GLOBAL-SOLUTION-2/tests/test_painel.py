"""Teste automatizado do painel Streamlit (executa o app sem navegador)."""
import pytest

from src import config as C

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

PRONTO = (C.PROCESSED / "refugio.db").exists() and (C.MODELOS / "metricas_cnn.json").exists()


@pytest.mark.skipif(not PRONTO, reason="rode o pipeline antes")
def test_painel_carrega_sem_erros_e_gera_alerta():
    at = AppTest.from_file(str(C.RAIZ / "src" / "app" / "painel.py"), default_timeout=120)
    at.run()
    assert not at.exception
    assert len(at.metric) >= 5
    at.button[0].click().run()  # "Gerar alerta" com máxima simulada de 36 °C
    assert not at.exception
    textos = " ".join(i.value for i in at.info)
    assert "°C" in textos or "graus" in textos


@pytest.mark.skipif(not PRONTO, reason="rode o pipeline antes")
def test_chat_do_painel_responde_emergencia_com_192():
    at = AppTest.from_file(str(C.RAIZ / "src" / "app" / "painel.py"), default_timeout=120)
    at.run()
    at.chat_input[0].set_value("Minha mãe desmaiou com o calor").run()
    assert not at.exception
    assert any("192" in m.markdown[0].value for m in at.chat_message if m.markdown)

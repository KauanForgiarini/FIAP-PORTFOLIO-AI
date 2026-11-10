"""Testes automatizados das análises e dos modelos.

Rodar a partir da pasta GLOBAL-SOLUTION-2:   python -m pytest -v
Testes que dependem dos dados baixados são pulados se os arquivos não existirem.
"""
import json

import numpy as np
import pandas as pd
import pytest

from src import config as C
from src.analise import calor_saude
from src.data.leitor_dbc import ler_dbc
from src.data.processar_clima import marcar_ondas

TEM_DADOS = (C.PROCESSED / "setores_santa_maria.gpkg").exists() and (C.PROCESSED / "refugios.geojson").exists()


# ----------------------------------------------------------------------------- clima
def test_onda_de_calor_exige_3_dias_seguidos():
    quente = pd.Series([0, 1, 1, 0, 1, 1, 1, 0, 1, 1, 1, 1], dtype=bool)
    onda = marcar_ondas(quente, 3)
    assert onda.tolist() == [0, 0, 0, 0, 1, 1, 1, 0, 1, 1, 1, 1]


# ----------------------------------------------------------------------------- calor x saúde
def test_razao_de_taxas_recupera_efeito_conhecido():
    """Série sintética em que os dias quentes têm exatamente 20% mais óbitos."""
    rng = np.random.default_rng(0)
    datas = pd.date_range("2021-11-01", "2024-03-31")
    datas = datas[datas.month.isin(calor_saude.MESES_QUENTES)]
    quente = rng.random(len(datas)) < 0.1
    base = 50.0
    obitos = np.where(quente, base * 1.2, base)
    df = pd.DataFrame({"data": datas, "obitos_idosos": obitos, "dia_quente_abs": quente})
    r = calor_saude.razao_de_taxas(df, "obitos_idosos", "dia_quente_abs", n_boot=200)
    # o "esperado" mistura dias quentes e normais do mesmo estrato, então o RR estimado fica
    # um pouco abaixo de 1,20 (viés conservador conhecido do método)
    assert 1.12 < r["rr"] <= 1.20
    assert r["ic_inf"] <= r["rr"] <= r["ic_sup"]


# ----------------------------------------------------------------------------- DATASUS
@pytest.mark.skipif(not (C.RAW / "datasus" / "sim" / "DORS2022.dbc").exists(), reason="dados SIM não baixados")
def test_leitor_dbc_le_arquivo_real_do_sim():
    df = ler_dbc(C.RAW / "datasus" / "sim" / "DORS2022.dbc", ["DTOBITO", "CODMUNRES", "IDADE"])
    assert len(df) > 90_000                       # o RS tem ~100 mil óbitos/ano
    assert df["DTOBITO"].str.len().eq(8).mean() > 0.99
    assert df["DTOBITO"].str[-4:].eq("2022").mean() > 0.99
    assert (df["CODMUNRES"] == C.COD_IBGE_6).sum() > 1500   # Santa Maria


# ----------------------------------------------------------------------------- recomendação
@pytest.mark.skipif(not TEM_DADOS, reason="dados processados ausentes")
def test_recomendador_nao_indica_local_fechado_no_domingo():
    from src.ml.recomendacao import Perfil, recomendar_refugios
    rec = recomendar_refugios(Perfil(-29.6847, -53.8069, dia_semana=6, hora=15, mobilidade_m=800))
    assert len(rec) > 0
    assert not rec["categoria"].isin(["saude", "assistencia", "biblioteca"]).any()


@pytest.mark.skipif(not TEM_DADOS, reason="dados processados ausentes")
def test_recomendador_respeita_mobilidade_e_ordena_por_pontuacao():
    from src.ml.recomendacao import Perfil, recomendar_refugios
    p = Perfil(-29.6955, -53.8580, dia_semana=2, hora=14, mobilidade_m=500)
    rec = recomendar_refugios(p, top_n=5)
    assert (rec["distancia_m"] <= 3 * p.mobilidade_m).all()
    assert rec["pontuacao"].is_monotonic_decreasing


@pytest.mark.skipif(not TEM_DADOS, reason="dados processados ausentes")
def test_parque_nao_e_primeira_opcao_para_quem_precisa_de_ar_condicionado():
    from src.ml.recomendacao import Perfil, recomendar_refugios
    rec = recomendar_refugios(Perfil(-29.6847, -53.8069, 2, 14, 800, "climatizado"))
    assert rec.iloc[0]["climatizado"]


# ----------------------------------------------------------------------------- índice de risco
@pytest.mark.skipif(not (C.PROCESSED / "setores_santa_maria.csv").exists(), reason="dados processados ausentes")
def test_indice_de_risco_entre_0_e_100_e_correlacionado_com_calor():
    s = pd.read_csv(C.PROCESSED / "setores_santa_maria.csv")
    if "indice_risco" not in s:
        pytest.skip("rode src.ml.vulnerabilidade")
    assert s["indice_risco"].between(0, 100).all()
    assert s[["indice_risco", "lst_media"]].corr().iloc[0, 1] > 0.3


@pytest.mark.skipif(not (C.MODELOS / "metricas_cnn.json").exists(), reason="CNN não treinada")
def test_cnn_supera_baseline_classico():
    m = json.loads((C.MODELOS / "metricas_cnn.json").read_text(encoding="utf-8"))
    escolhido = m["modelo_escolhido"]
    assert m[escolhido]["acuracia_teste"] > m["baseline_rf_histograma"]["acuracia_teste"] + 0.05

"""Associação entre dias de calor extremo e óbitos/internações de idosos.

Método (desenho "estratificado no tempo", comum em epidemiologia ambiental):
para cada dia, o número esperado de eventos é a média dos dias do MESMO mês/ano
e do MESMO dia da semana. Isso controla sazonalidade, tendência de longo prazo
e o efeito de fim de semana. A razão observado/esperado nos dias de calor
estima o excesso de risco (razão de taxas, RR). O intervalo de confiança vem
de um bootstrap sobre os dias de calor.

Limitações: é uma análise ecológica (nível populacional, não individual), não
controla poluição nem umidade, e o bootstrap simples ignora a autocorrelação
entre dias consecutivos de uma mesma onda de calor.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src import config as C

MESES_QUENTES = [11, 12, 1, 2, 3]

DESFECHOS = {
    "obitos_idosos": ("Óbitos de idosos (todas as causas)", "2020-01-01", "2024-12-31"),
    "obitos_idosos_sensivel_calor": ("Óbitos de idosos (causas sensíveis ao calor)", "2020-01-01", "2024-12-31"),
    "internacoes_idosos": ("Internações de idosos (todas as causas)", "2021-01-01", "2025-11-30"),
    "internacoes_idosos_sensivel_calor": ("Internações de idosos (causas sensíveis ao calor)", "2021-01-01", "2025-11-30"),
}


def carregar(recorte: str = "santa_maria") -> pd.DataFrame:
    clima = pd.read_csv(C.PROCESSED / "clima_diario.csv", parse_dates=["data"])
    saude = pd.read_csv(C.PROCESSED / "saude_diaria.csv", parse_dates=["data"])
    saude = saude[saude.recorte.eq(recorte)]
    df = saude.merge(clima[["data", "tmax", "dia_quente_abs", "dia_quente_p90", "onda_calor"]], on="data")
    return df[df.data.dt.month.isin(MESES_QUENTES)].copy()


def razao_de_taxas(df: pd.DataFrame, desfecho: str, marcador: str = "dia_quente_abs",
                   n_boot: int = 2000, semente: int = 42) -> dict:
    rotulo, ini, fim = DESFECHOS[desfecho]
    d = df[df.data.between(ini, fim)].copy()
    d["estrato"] = d.data.dt.to_period("M").astype(str) + "-" + d.data.dt.day_of_week.astype(str)
    d["esperado"] = d.groupby("estrato")[desfecho].transform("mean")
    quente = d[d[marcador]]
    obs, esp = quente[desfecho].to_numpy(), quente["esperado"].to_numpy()
    rr = obs.sum() / esp.sum()
    rng = np.random.default_rng(semente)
    idx = rng.integers(0, len(obs), size=(n_boot, len(obs)))
    boot = obs[idx].sum(axis=1) / esp[idx].sum(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"desfecho": desfecho, "rotulo": rotulo, "marcador": marcador, "dias": len(quente),
            "observado": int(obs.sum()), "esperado": float(esp.sum()),
            "excesso": float(obs.sum() - esp.sum()), "rr": float(rr), "ic_inf": float(lo), "ic_sup": float(hi)}


def tabela_resultados(recorte: str = "santa_maria", marcador: str = "dia_quente_abs") -> pd.DataFrame:
    df = carregar(recorte)
    return pd.DataFrame([razao_de_taxas(df, d, marcador) for d in DESFECHOS])


if __name__ == "__main__":
    pd.set_option("display.width", 160)
    for m in ("dia_quente_abs", "onda_calor"):
        t = tabela_resultados(marcador=m)
        print(f"\n== {m} ==")
        print(t[["rotulo", "dias", "observado", "esperado", "excesso", "rr", "ic_inf", "ic_sup"]].round(3).to_string(index=False))
    t = tabela_resultados(marcador="dia_quente_abs")
    t.to_csv(C.PROCESSED / "resultado_calor_saude.csv", index=False)

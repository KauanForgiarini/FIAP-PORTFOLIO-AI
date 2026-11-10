"""Série climática diária de Santa Maria com marcação de dias e ondas de calor.

Combina duas fontes:
- Observações da estação meteorológica 83936 (Meteostat, 2021-2026): valor
  medido, usado sempre que disponível.
- Reanálise ERA5 (Open-Meteo, 1991-2025): série longa e sem falhas, usada para
  climatologia, tendência e para preencher lacunas da estação. A reanálise
  suaviza extremos (resolução ~25 km), por isso a comparamos com a estação.

Definições (ver src/config.py):
- dia_quente_abs : Tmax >= 35 °C
- dia_quente_p90 : Tmax acima do percentil 90 dos verões (dez-fev) de 1991-2020
- onda_calor     : >= 3 dias consecutivos com dia_quente_p90

Saída: data/processed/clima_diario.csv
Uso  : python -m src.data.processar_clima
"""
from __future__ import annotations

import pandas as pd

from src import config as C


def marcar_ondas(serie_bool: pd.Series, minimo: int) -> pd.Series:
    """True nos dias que pertencem a sequências de pelo menos `minimo` dias True."""
    grupo = (serie_bool != serie_bool.shift()).cumsum()
    tamanho = serie_bool.groupby(grupo).transform("size")
    return serie_bool & (tamanho >= minimo)


def main() -> pd.DataFrame:
    era5 = pd.read_csv(C.RAW / "clima" / "openmeteo_era5_diario_1991_2025.csv", parse_dates=["data"])
    era5 = era5.rename(columns={"temperature_2m_max": "tmax_era5", "temperature_2m_min": "tmin_era5",
                                "temperature_2m_mean": "tmed_era5",
                                "apparent_temperature_max": "sensacao_max_era5",
                                "relative_humidity_2m_mean": "umidade_era5", "precipitation_sum": "chuva_era5"})
    est = pd.read_csv(C.RAW / "clima" / f"meteostat_{C.ESTACAO_OMM}_diario.csv", parse_dates=["data"])
    est = est[["data", "tmax", "tmin", "tavg", "prcp"]].rename(columns={
        "tmax": "tmax_estacao", "tmin": "tmin_estacao", "tavg": "tmed_estacao", "prcp": "chuva_estacao"})

    df = era5.merge(est, on="data", how="outer").sort_values("data").reset_index(drop=True)

    # Calibração simples: viés médio da reanálise frente à estação nos dias em comum
    comum = df.dropna(subset=["tmax_estacao", "tmax_era5"])
    vies = (comum.tmax_estacao - comum.tmax_era5).mean()
    corr = comum[["tmax_estacao", "tmax_era5"]].corr().iloc[0, 1]
    print(f"Estação x ERA5 em {len(comum)} dias: viés Tmax = {vies:+.2f} °C, correlação = {corr:.3f}")

    # Série homogênea (só reanálise corrigida) para tendência de longo prazo: evita misturar
    # fontes diferentes ao comparar décadas.
    df["tmax_era5_corrigido"] = df["tmax_era5"] + vies
    df["tmax"] = df["tmax_estacao"].fillna(df["tmax_era5_corrigido"])
    df["fonte_tmax"] = df["tmax_estacao"].notna().map({True: "estacao", False: "era5_corrigido"})

    verao = df.data.dt.month.isin([12, 1, 2]) & df.data.dt.year.between(1991, 2020)
    p90 = df.loc[verao, "tmax"].quantile(C.PERCENTIL_ONDA_CALOR / 100)
    print(f"Percentil {C.PERCENTIL_ONDA_CALOR} da Tmax de verão (1991-2020): {p90:.1f} °C")

    df["dia_quente_abs"] = df["tmax"] >= C.LIMIAR_TMAX_ABSOLUTO
    df["dia_quente_p90"] = df["tmax"] >= p90
    df["onda_calor"] = marcar_ondas(df["dia_quente_p90"], C.DIAS_MIN_ONDA_CALOR)
    df.attrs["p90"] = p90

    df.to_csv(C.PROCESSED / "clima_diario.csv", index=False)
    anual = df.groupby(df.data.dt.year).agg(dias_35=("dia_quente_abs", "sum"),
                                            dias_onda=("onda_calor", "sum"), tmax_max=("tmax", "max"))
    print(anual.tail(12))
    return df


if __name__ == "__main__":
    main()

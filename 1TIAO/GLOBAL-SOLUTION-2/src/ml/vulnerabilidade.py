"""Índice de risco ao calor para idosos e agrupamento (clusterização) dos setores.

Referencial: o conceito de risco climático do IPCC (AR5/AR6), em que
    RISCO = PERIGO x EXPOSIÇÃO x VULNERABILIDADE

    Perigo         -> quão quente o setor fica (temperatura de superfície, área construída pela CNN)
    Exposição      -> quantos idosos vivem ali (idosos 60+, % de 70+)
    Vulnerabilidade-> sensibilidade e baixa capacidade de adaptação
                      (pouca vegetação, idosos não alfabetizados, distância ao refúgio climatizado)

Duas técnicas complementares:
1. Índice contínuo (0-100) para ORDENAR setores: média geométrica das três
   dimensões normalizadas (um setor sem idosos tem risco baixo, mesmo que quente).
2. K-Means para DESCREVER perfis de setores parecidos. O número de grupos é
   escolhido pela silhueta (k de 3 a 7), conferida pelo índice Davies-Bouldin.

Saídas: colunas `indice_risco`, `prioridade`, `cluster`, `perfil_cluster` em
data/processed/setores_santa_maria.*; data/processed/clusters_perfis.csv;
src/ml/modelos/metricas_clusters.json
Uso: python -m src.ml.vulnerabilidade
"""
from __future__ import annotations

import json

import geopandas as gpd
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import davies_bouldin_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from src import config as C

ATRIBUTOS = {
    "lst_media": "Temperatura de superfície (°C)",
    "frac_construida_cnn": "Área construída (CNN)",
    "ndvi_media": "Vegetação (NDVI)",
    "pct_idosos": "% idosos 60+",
    "pct_70_mais": "% idosos 70+",
    "pct_idosos_nao_alfabetizados": "% idosos não alfabetizados",
    "dist_refugio_km": "Distância ao refúgio climatizado (km)",
}


def _norm(s: pd.Series) -> pd.Series:
    """Min-max robusto (percentis 2-98) para 0-1."""
    lo, hi = s.quantile(0.02), s.quantile(0.98)
    return ((s - lo) / (hi - lo)).clip(0, 1)


def distancia_refugio(g: gpd.GeoDataFrame) -> pd.Series:
    ref = gpd.read_file(C.PROCESSED / "refugios.geojson").to_crs(C.CRS_METRICO)
    ref = ref[ref.climatizado.astype(bool)]
    cent = g.geometry.representative_point()
    return cent.apply(lambda p: ref.distance(p).min() / 1000)


def main():
    g = gpd.read_file(C.PROCESSED / "setores_santa_maria.gpkg").set_index("CD_SETOR")
    g["dist_refugio_km"] = distancia_refugio(g)

    # Setores com sigilo do IBGE: para o ÍNDICE, imputa a mediana do bairro (e registra quais foram
    # imputados). As contagens reais (idosos_60_mais) não são alteradas, para não inflar os totais.
    cols_censo = ["pct_idosos", "pct_70_mais", "pct_idosos_nao_alfabetizados"]
    g["imputado"] = g[cols_censo + ["idosos_60_mais"]].isna().any(axis=1)
    for c in cols_censo:
        g[c] = g[c].fillna(g.groupby("bairro")[c].transform("median")).fillna(g[c].median())
    idosos_idx = g["idosos_60_mais"].fillna(g.groupby("bairro")["idosos_60_mais"].transform("median"))
    if "frac_construida_cnn" not in g:
        g["frac_construida_cnn"] = np.nan
    g["frac_construida_cnn"] = g["frac_construida_cnn"].fillna(g["frac_construida_cnn"].median()
                                                               if g["frac_construida_cnn"].notna().any() else 0.5)

    # ---------------- 1) Índice de risco ----------------
    perigo = (_norm(g.lst_media) * 0.7 + _norm(g.frac_construida_cnn) * 0.3)
    exposicao = (_norm(idosos_idx) * 0.6 + _norm(g.pct_70_mais) * 0.4)
    vulner = (_norm(-g.ndvi_media) * 0.4 + _norm(g.pct_idosos_nao_alfabetizados) * 0.3
              + _norm(g.dist_refugio_km) * 0.3)
    eps = 0.05  # evita zerar o índice quando uma dimensão é mínima
    g["risco_perigo"], g["risco_exposicao"], g["risco_vulnerabilidade"] = perigo, exposicao, vulner
    g["indice_risco"] = 100 * ((perigo + eps) * (exposicao + eps) * (vulner + eps)) ** (1 / 3) / (1 + eps)
    g["prioridade"] = pd.qcut(g["indice_risco"], [0, 0.5, 0.8, 0.95, 1],
                              labels=["Baixa", "Média", "Alta", "Muito alta"])

    # ---------------- 2) K-Means ----------------
    X = StandardScaler().fit_transform(g[list(ATRIBUTOS)])
    avaliacao = []
    for k in range(3, 8):
        km = KMeans(n_clusters=k, n_init=20, random_state=42).fit(X)
        avaliacao.append({"k": k, "silhueta": silhouette_score(X, km.labels_),
                          "davies_bouldin": davies_bouldin_score(X, km.labels_), "inercia": km.inertia_})
    aval = pd.DataFrame(avaliacao)
    k = int(aval.loc[aval.silhueta.idxmax(), "k"])
    km = KMeans(n_clusters=k, n_init=50, random_state=42).fit(X)
    g["cluster"] = km.labels_

    perfis = g.groupby("cluster")[list(ATRIBUTOS) + ["indice_risco"]].mean()
    perfis["setores"] = g.groupby("cluster").size()
    perfis["idosos"] = g.groupby("cluster")["idosos_60_mais"].sum()
    # renumera do maior para o menor risco médio e dá um nome descritivo a cada perfil
    ordem = perfis["indice_risco"].sort_values(ascending=False).index
    mapa = {old: new for new, old in enumerate(ordem, start=1)}
    g["cluster"] = g["cluster"].map(mapa)
    perfis = perfis.rename(index=mapa).sort_index()
    media = g[list(ATRIBUTOS)].mean()
    desv = g[list(ATRIBUTOS)].std()

    def nomear(row):
        z = (row[list(ATRIBUTOS)] - media) / desv
        partes, lim = [], 0.3  # desvios-padrão em relação à média da cidade
        partes.append("quente" if z.lst_media > lim else "fresco" if z.lst_media < -lim else "temperatura média")
        partes.append("envelhecido" if z.pct_idosos > lim else "jovem" if z.pct_idosos < -lim else "idade média")
        partes.append("pouco verde" if z.ndvi_media < -lim else "arborizado" if z.ndvi_media > lim else "verde médio")
        if z.dist_refugio_km > lim:
            partes.append("longe de refúgio")
        return ", ".join(partes).capitalize()

    perfis["perfil"] = perfis.apply(nomear, axis=1)
    g["perfil_cluster"] = g["cluster"].map(perfis["perfil"])

    # salva
    g.to_file(C.PROCESSED / "setores_santa_maria.gpkg", driver="GPKG")
    pd.DataFrame(g.drop(columns="geometry")).to_csv(C.PROCESSED / "setores_santa_maria.csv")
    web = g.to_crs(4326)
    web["geometry"] = web.geometry.simplify(0.00005)
    web.reset_index().to_file(C.PROCESSED / "setores_santa_maria.geojson", driver="GeoJSON")
    perfis.round(3).to_csv(C.PROCESSED / "clusters_perfis.csv")
    (C.MODELOS / "metricas_clusters.json").write_text(json.dumps({
        "k_escolhido": k, "avaliacao_k": aval.round(4).to_dict("records"),
        "atributos": ATRIBUTOS, "setores_imputados": int(g.imputado.sum()),
        "pesos_indice": {"perigo": {"lst": 0.7, "construido_cnn": 0.3},
                         "exposicao": {"idosos_60_mais": 0.6, "pct_70_mais": 0.4},
                         "vulnerabilidade": {"ndvi_invertido": 0.4, "nao_alfabetizados": 0.3, "dist_refugio": 0.3}},
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    pd.set_option("display.width", 200)
    print(aval.round(3).to_string(index=False))
    print(f"\nk escolhido = {k}")
    print(perfis[["perfil", "setores", "idosos", "indice_risco", "lst_media", "ndvi_media", "pct_idosos",
                  "dist_refugio_km"]].round(2).to_string())
    top = g.sort_values("indice_risco", ascending=False).head(10)
    print("\nTop 10 setores de maior risco:")
    print(top[["bairro", "indice_risco", "lst_media", "idosos_60_mais", "ndvi_media", "dist_refugio_km"]].round(2).to_string())
    print("\nIdosos por prioridade:", g.groupby("prioridade", observed=True)["idosos_60_mais"].sum().to_dict())


if __name__ == "__main__":
    main()

"""Gera as figuras estáticas usadas no README e no relatório PDF (docs/img/).

Uso: python -m src.analise.figuras
"""
from __future__ import annotations

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.colors import LinearSegmentedColormap
from rasterio.plot import plotting_extent

from src import config as C
from src.analise.calor_saude import tabela_resultados

# Paleta (tokens) - superfície clara, tinta de texto, série principal e rampas sequenciais
SUPERFICIE, TEXTO, TEXTO_2, GRADE = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3de"
AZUL = "#2a78d6"
RAMPA_AZUL = LinearSegmentedColormap.from_list("azul", ["#cde2fb", "#6da7ec", "#2a78d6", "#1c5cab", "#0d366b"])
RAMPA_CALOR = LinearSegmentedColormap.from_list("calor", ["#fde7da", "#f6a57f", "#eb6834", "#b8461b", "#6e2709"])
RAMPA_VERDE = LinearSegmentedColormap.from_list("verde", ["#e3f3e3", "#8fcf8f", "#2f9e2f", "#0b6b0b", "#033d03"])

plt.rcParams.update({
    "figure.facecolor": SUPERFICIE, "axes.facecolor": SUPERFICIE, "savefig.facecolor": SUPERFICIE,
    "text.color": TEXTO, "axes.labelcolor": TEXTO_2, "xtick.color": TEXTO_2, "ytick.color": TEXTO_2,
    "axes.edgecolor": GRADE, "axes.grid": True, "grid.color": GRADE, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 10, "axes.titlesize": 12,
    "axes.titleweight": "bold", "axes.titlelocation": "left",
})


def _salvar(fig, nome):
    caminho = C.DOCS_IMG / nome
    fig.savefig(caminho, dpi=200, bbox_inches="tight")
    plt.close(fig)
    print(f"salvo docs/img/{nome}")


def dias_de_calor_por_ano():
    df = pd.read_csv(C.PROCESSED / "clima_diario.csv", parse_dates=["data"])
    df = df[df.data.dt.year <= 2025]
    anual = (df["tmax_era5_corrigido"] >= C.LIMIAR_TMAX_ABSOLUTO).groupby(df.data.dt.year).sum()
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.bar(anual.index, anual.values, width=0.7, color=AZUL, zorder=2)
    ax.grid(axis="x", visible=False)
    for (a, b) in [(1991, 2000), (2016, 2025)]:
        m = anual.loc[a:b].mean()
        ax.hlines(m, a - 0.4, b + 0.4, color=TEXTO, linewidth=1.2, linestyles="--", zorder=3)
        ax.annotate(f"média {a}–{b}: {m:.1f} dias".replace(".", ","), (b + 0.4, m), xytext=(4, 4),
                    textcoords="offset points", fontsize=9, color=TEXTO, ha="left" if a == 1991 else "right")
    ax.set_title("Dias com máxima ≥ 35 °C por ano em Santa Maria/RS")
    ax.set_ylabel("dias por ano")
    ax.text(0, -0.2, "Fonte: reanálise ERA5 (Open-Meteo) com correção de viés pela estação 83936 – série homogênea "
            "1991–2025. Elaboração do grupo.", transform=ax.transAxes, fontsize=8, color=TEXTO_2)
    _salvar(fig, "dias_35C_por_ano.png")


def calor_e_saude():
    t = tabela_resultados()
    t = t.iloc[::-1].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(9, 3.4))
    y = np.arange(len(t))
    ax.axvline(1, color=TEXTO_2, linewidth=1)
    ax.hlines(y, t.ic_inf, t.ic_sup, color=AZUL, linewidth=2, zorder=2)
    ax.scatter(t.rr, y, s=60, color=AZUL, edgecolor=SUPERFICIE, linewidth=2, zorder=3)
    for i, r in t.iterrows():
        ax.annotate(f"{(r.rr - 1) * 100:+.0f}%  (IC95% {(r.ic_inf - 1) * 100:+.0f}% a {(r.ic_sup - 1) * 100:+.0f}%)",
                    (r.ic_sup, i), xytext=(8, -3), textcoords="offset points", fontsize=9, color=TEXTO)
    ax.set_yticks(y, t.rotulo)
    ax.set_xlim(0.85, 1.55)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("razão observado / esperado nos dias com máxima ≥ 35 °C  (1 = sem efeito)")
    ax.set_title("Dias de calor extremo e saúde dos idosos (60+) em Santa Maria/RS")
    ax.text(0, -0.32, "Fonte: DATASUS (SIM 2020–2024, SIH 2021–2025) e estação 83936. Esperado = média do mesmo "
            "mês/ano e dia da semana; meses de nov a mar.", transform=ax.transAxes, fontsize=8, color=TEXTO_2)
    _salvar(fig, "calor_saude_idosos.png")


def mapas_setores():
    g = gpd.read_file(C.PROCESSED / "setores_santa_maria.gpkg")
    paineis = [("pct_idosos", "% de idosos (60+) por setor", RAMPA_AZUL, "%")]
    if "lst_media" in g:
        paineis += [("lst_media", "Temperatura de superfície no verão", RAMPA_CALOR, "°C"),
                    ("ndvi_media", "Vegetação (NDVI)", RAMPA_VERDE, "NDVI")]
    fig, axs = plt.subplots(1, len(paineis), figsize=(5.2 * len(paineis), 3.0), layout="constrained")
    axs = np.atleast_1d(axs)
    for ax, (col, titulo, cmap, unidade) in zip(axs, paineis):
        g.plot(column=col, ax=ax, cmap=cmap, edgecolor=SUPERFICIE, linewidth=0.15,
               missing_kwds={"color": "#dddcd6", "label": "sigilo IBGE"},
               legend=True, legend_kwds={"shrink": 0.6, "label": unidade})
        ax.set_title(titulo, fontsize=11)
        ax.set_axis_off()
    fig.supxlabel("Fontes: IBGE Censo 2022 (setores urbanos do distrito-sede) e Landsat 8/9 "
                   "(mediana dos verões 2022–2025). Elaboração do grupo.", fontsize=8, color=TEXTO_2, x=0.01, ha="left")
    _salvar(fig, "mapas_setores.png")


def mapa_lst_raster():
    caminho = C.PROCESSED / "landsat_lst_verao_mediana.tif"
    if not caminho.exists():
        return
    with rasterio.open(caminho) as src:
        arr = src.read(1)
        ext = plotting_extent(src)
    g = gpd.read_file(C.PROCESSED / "setores_santa_maria.gpkg")
    fig, ax = plt.subplots(figsize=(9, 6))
    vmin, vmax = np.nanpercentile(arr, [2, 98])
    im = ax.imshow(arr, extent=ext, cmap=RAMPA_CALOR, vmin=vmin, vmax=vmax)
    g.boundary.plot(ax=ax, color=TEXTO, linewidth=0.15, alpha=0.5)
    ax.set_axis_off()
    cb = fig.colorbar(im, ax=ax, shrink=0.7)
    cb.set_label("°C (superfície)")
    ax.set_title("Ilhas de calor em Santa Maria/RS – temperatura de superfície no verão (Landsat, 30 m)")
    ax.text(0, -0.04, "Mediana das cenas de dez–mar de 2022/23, 2023/24 e 2024/25 sem nuvens. "
            "Contornos: setores censitários urbanos.", transform=ax.transAxes, fontsize=8, color=TEXTO_2)
    _salvar(fig, "mapa_lst_santa_maria.png")


def modelos_cnn():
    import json
    caminho = C.MODELOS / "metricas_cnn.json"
    if not caminho.exists():
        return
    m = json.loads(caminho.read_text(encoding="utf-8"))
    nomes = {"baseline_rf_histograma": "Random Forest\n(histograma de cores)", "cnn_pequena": "CNN pequena\n(do zero)",
             "resnet18_transfer": "ResNet-18\n(transfer learning)"}
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.6), gridspec_kw={"width_ratios": [1, 1.25]}, layout="constrained")
    ax = axs[0]
    acc = [m[k]["acuracia_teste"] * 100 for k in nomes]
    cores = ["#9ec5f4", "#6da7ec", AZUL]  # do mais simples (claro) ao mais sofisticado (escuro)
    barras = ax.bar(list(nomes.values()), acc, color=cores, width=0.55, zorder=2)
    for b, v in zip(barras, acc):
        ax.annotate(f"{v:.1f}%".replace(".", ","), (b.get_x() + b.get_width() / 2, v), xytext=(0, 4),
                    textcoords="offset points", ha="center", fontsize=10, color=TEXTO)
    ax.set_ylim(0, 105)
    ax.grid(axis="x", visible=False)
    ax.set_ylabel("acurácia no teste (%)")
    ax.set_title("Comparação dos modelos (EuroSAT, 4.050 imagens de teste)", fontsize=11)
    ax = axs[1]
    cm = np.array(m["matriz_confusao"], dtype=float)
    cmn = cm / cm.sum(1, keepdims=True)
    ax.imshow(cmn, cmap=RAMPA_AZUL, vmin=0, vmax=1)
    rot = m["classes_pt"]
    ax.set_xticks(range(10), rot, rotation=45, ha="right", fontsize=8)
    ax.set_yticks(range(10), rot, fontsize=8)
    for i in range(10):
        for j in range(10):
            if cmn[i, j] >= 0.01:
                ax.text(j, i, f"{cmn[i, j] * 100:.0f}", ha="center", va="center", fontsize=7,
                        color="white" if cmn[i, j] > 0.6 else TEXTO)
    ax.grid(False)
    ax.set_xlabel("classe prevista")
    ax.set_ylabel("classe real")
    ax.set_title(f"Matriz de confusão (%) – modelo escolhido: {m['modelo_escolhido']}", fontsize=11)
    _salvar(fig, "cnn_comparacao_modelos.png")


def mapa_risco():
    g = gpd.read_file(C.PROCESSED / "setores_santa_maria.gpkg")
    if "prioridade" not in g:
        return
    ordem = ["Baixa", "Média", "Alta", "Muito alta"]
    cores = {"Baixa": "#fde7da", "Média": "#f6a57f", "Alta": "#eb6834", "Muito alta": "#6e2709"}
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.8), layout="constrained")
    ax = axs[0]
    for p in ordem:
        sub = g[g.prioridade == p]
        sub.plot(ax=ax, color=cores[p], edgecolor=SUPERFICIE, linewidth=0.2,
                 label=f"{p} ({int(sub.idosos_60_mais.sum()):,} idosos)".replace(",", "."))
    ref = gpd.read_file(C.PROCESSED / "refugios.geojson").to_crs(g.crs)
    clim = ref[ref.climatizado.astype(bool)]
    clim.plot(ax=ax, color=TEXTO, markersize=6, marker="o", label="refúgio climatizado")
    ax.legend(loc="lower left", fontsize=8, frameon=False)
    ax.set_axis_off()
    ax.set_title("Prioridade de ação por setor (índice de risco ao calor)", fontsize=11)
    ax = axs[1]
    if "dist_refugio_aberto_domingo_14h_m" in g:
        col = "dist_refugio_aberto_domingo_14h_m"
        g.plot(column=g[col].clip(upper=3000) / 1000, ax=ax, cmap=RAMPA_AZUL, edgecolor=SUPERFICIE, linewidth=0.2,
               legend=True, legend_kwds={"shrink": 0.6, "label": "km até o refúgio aberto mais próximo"})
        dom = ref[ref.climatizado.astype(bool) & ref.dias_abertos.astype(str).str.contains("6")]
        dom.plot(ax=ax, color=TEXTO, markersize=8)
        ax.set_title("Domingo, 14h: distância até um refúgio climatizado aberto", fontsize=11)
    ax.set_axis_off()
    fig.supxlabel("Fontes: IBGE Censo 2022, Landsat, CNN sobre Sentinel-2 e OpenStreetMap. Elaboração do grupo.",
                  fontsize=8, color=TEXTO_2, x=0.01, ha="left")
    _salvar(fig, "mapa_risco_refugios.png")


if __name__ == "__main__":
    dias_de_calor_por_ano()
    calor_e_saude()
    mapas_setores()
    mapa_lst_raster()
    modelos_cnn()
    mapa_risco()

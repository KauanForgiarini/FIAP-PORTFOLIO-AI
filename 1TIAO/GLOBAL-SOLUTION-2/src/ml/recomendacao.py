"""Sistemas de recomendação do Refúgio.

A) Para o CIDADÃO (idoso, familiar ou cuidador): qual refúgio climático
   procurar agora. É um recomendador baseado em conhecimento e utilidade,
   personalizado por:
     - localização (ponto ou setor de moradia);
     - mobilidade (distância que a pessoa consegue andar);
     - necessidade (ambiente climatizado, sombra ao ar livre ou atendimento de saúde);
     - dia e horário (só recomenda o que está aberto).
   Pontuação = 0,45 proximidade + 0,35 adequação à necessidade + 0,20 frescor do entorno.

B) Para o GESTOR PÚBLICO: onde plantar árvores primeiro. Usamos a relação
   observada entre vegetação e temperatura de superfície nos 406 setores
   (regressão linear LST ~ NDVI) para estimar quanto cada setor esfriaria com
   mais verde, e multiplicamos pelo número de idosos: benefício em "idoso·°C".

Avaliação:
   A) simulação para todos os setores (ponderada pelo número de idosos) em dia
      útil e domingo às 14h, comparada a um baseline ingênuo ("refúgio mais
      próximo", sem olhar horário nem tipo);
   B) benefício capturado pelos 20 primeiros setores recomendados, comparado a
      critérios simples (mais quentes, mais idosos, menos verdes) e
      estabilidade do ranking quando os pesos variam.

Uso: python -m src.ml.recomendacao
"""
from __future__ import annotations

import json
from dataclasses import dataclass

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from scipy.stats import kendalltau
from shapely.geometry import Point
from sklearn.linear_model import LinearRegression

from src import config as C

PESOS = {"proximidade": 0.45, "adequacao": 0.35, "frescor": 0.20}
ADEQUACAO = {  # necessidade -> categoria -> adequação (0-1)
    "climatizado": {"saude": 1.0, "assistencia": 1.0, "biblioteca": 1.0, "shopping": 1.0, "parque": 0.2},
    "sombra": {"parque": 1.0, "saude": 0.6, "assistencia": 0.6, "biblioteca": 0.6, "shopping": 0.6},
    "atendimento": {"saude": 1.0, "assistencia": 0.5, "biblioteca": 0.2, "shopping": 0.2, "parque": 0.1},
}
DIAS = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]


# ==========================================================================
# A) Recomendação de refúgio para o cidadão
# ==========================================================================
@dataclass
class Perfil:
    lat: float
    lon: float
    dia_semana: int = 2          # 0 = segunda ... 6 = domingo
    hora: int = 14
    mobilidade_m: int = 800      # quanto consegue caminhar
    necessidade: str = "climatizado"


_cache: dict = {}


def carregar_refugios() -> gpd.GeoDataFrame:
    if "ref" not in _cache:
        ref = gpd.read_file(C.PROCESSED / "refugios.geojson").to_crs(C.CRS_METRICO)
        ref["dias"] = ref["dias_abertos"].astype(str).str.split(",").apply(lambda d: {int(x) for x in d})
        with rasterio.open(C.PROCESSED / "landsat_lst_verao_mediana.tif") as src:
            xy = [(p.x, p.y) for p in ref.geometry]
            ref["lst_local"] = [v[0] for v in src.sample(xy)]
        ref["lst_local"] = ref["lst_local"].fillna(ref["lst_local"].median())
        _cache["ref"] = ref
    return _cache["ref"]


def aberto(ref: gpd.GeoDataFrame, dia: int, hora: int) -> pd.Series:
    return ref["dias"].apply(lambda d: dia in d) & (ref["abre"] <= hora) & (hora < ref["fecha"])


def recomendar_refugios(perfil: Perfil, top_n: int = 3) -> pd.DataFrame:
    ref = carregar_refugios()
    ponto = gpd.GeoSeries([Point(perfil.lon, perfil.lat)], crs=4326).to_crs(C.CRS_METRICO).iloc[0]
    r = ref.copy()
    r["distancia_m"] = r.distance(ponto)
    r["aberto_agora"] = aberto(r, perfil.dia_semana, perfil.hora)
    r = r[r["aberto_agora"] & (r["distancia_m"] <= 3 * perfil.mobilidade_m)]
    if r.empty:
        return r
    r["s_proximidade"] = np.exp(-r["distancia_m"] / perfil.mobilidade_m)
    r["s_adequacao"] = r["categoria"].map(ADEQUACAO[perfil.necessidade])
    lst = ref["lst_local"]
    r["s_frescor"] = (1 - (r["lst_local"] - lst.min()) / (lst.max() - lst.min())).clip(0, 1)
    r["pontuacao"] = sum(PESOS[k] * r[f"s_{k}"] for k in PESOS)
    r = r.sort_values("pontuacao", ascending=False).head(top_n)
    r["explicacao"] = r.apply(lambda x: (
        f"{x['nome']} ({x['categoria']}) a {x['distancia_m'] / 1000:.1f} km"
        f"{', climatizado' if x['climatizado'] else ', ao ar livre com sombra'}"
        f", aberto até {int(x['fecha'])}h"), axis=1)
    return r[["nome", "categoria", "climatizado", "distancia_m", "fecha", "pontuacao", "s_proximidade",
              "s_adequacao", "s_frescor", "explicacao", "geometry"]]


def avaliar_refugios(setores: gpd.GeoDataFrame) -> dict:
    ref = carregar_refugios()
    pts = setores.geometry.representative_point()
    idosos = setores["idosos_60_mais"].fillna(0).to_numpy()
    resultados = {}
    for nome_cenario, dia in (("dia_util_14h", 2), ("domingo_14h", 6)):
        abertos_clim = ref[aberto(ref, dia, 14) & ref.climatizado.astype(bool)]
        d_rec = np.array([abertos_clim.distance(p).min() if len(abertos_clim) else np.inf for p in pts])
        # baseline ingênuo: o ponto mais próximo de qualquer tipo, sem olhar horário
        idx_base = [ref.distance(p).idxmin() for p in pts]
        base = ref.loc[idx_base]
        base_ok = (aberto(base, dia, 14) & base.climatizado.astype(bool)).to_numpy()
        resultados[nome_cenario] = {
            "idosos_com_refugio_climatizado_aberto_ate_800m_%": float(100 * idosos[d_rec <= 800].sum() / idosos.sum()),
            "idosos_com_refugio_climatizado_aberto_ate_1500m_%": float(100 * idosos[d_rec <= 1500].sum() / idosos.sum()),
            "distancia_media_ponderada_m": float(np.average(np.minimum(d_rec, 10000), weights=idosos)),
            "baseline_mais_proximo_inadequado_ou_fechado_%": float(100 * idosos[~base_ok].sum() / idosos.sum()),
            "refugios_climatizados_abertos": int(len(abertos_clim)),
        }
        setores[f"dist_refugio_aberto_{nome_cenario}_m"] = d_rec
    return resultados


# ==========================================================================
# B) Recomendação de plantio de árvores para o gestor
# ==========================================================================
def recomendar_plantio(setores: gpd.GeoDataFrame, delta_max: float = 0.10, top_k: int = 20):
    v = setores.dropna(subset=["lst_media", "ndvi_media"])
    reg = LinearRegression().fit(v[["ndvi_media"]], v["lst_media"])
    beta, r2 = float(reg.coef_[0]), float(reg.score(v[["ndvi_media"]], v["lst_media"]))
    alvo = setores["ndvi_media"].quantile(0.75)
    delta_ndvi = (alvo - setores["ndvi_media"]).clip(lower=0, upper=delta_max)
    setores["resfriamento_potencial_C"] = -beta * delta_ndvi
    setores["beneficio_idoso_grau"] = setores["resfriamento_potencial_C"] * setores["idosos_60_mais"].fillna(0)
    setores["rank_plantio"] = setores["beneficio_idoso_grau"].rank(ascending=False, method="first").astype(int)

    def captura(ordem: pd.Series) -> float:
        return float(setores.loc[ordem.sort_values(ascending=False).index[:top_k], "beneficio_idoso_grau"].sum())

    total_top = captura(setores["beneficio_idoso_grau"])
    comparacao = {
        "recomendador_plantio": total_top,
        "mais_quentes": captura(setores["lst_media"]),
        "mais_idosos": captura(setores["idosos_60_mais"].fillna(0)),
        "menos_verdes": captura(-setores["ndvi_media"]),
        "aleatorio_media_100x": float(np.mean([
            setores["beneficio_idoso_grau"].sample(top_k, random_state=s).sum() for s in range(100)])),
    }
    # estabilidade: varia o alvo de NDVI e o teto de plantio e compara o ranking
    taus = []
    for q in (0.6, 0.7, 0.8, 0.9):
        for dm in (0.05, 0.10, 0.15):
            d = (setores["ndvi_media"].quantile(q) - setores["ndvi_media"]).clip(0, dm)
            b = -beta * d * setores["idosos_60_mais"].fillna(0)
            taus.append(kendalltau(b, setores["beneficio_idoso_grau"]).statistic)
    return {"beta_C_por_unidade_ndvi": beta, "resfriamento_por_0_1_ndvi_C": -beta * 0.1, "r2": r2,
            "ndvi_alvo_p75": float(alvo), "top_k": top_k, "beneficio_capturado_top_k": comparacao,
            "kendall_tau_estabilidade_min": float(np.min(taus)), "kendall_tau_estabilidade_media": float(np.mean(taus))}


def main():
    setores = gpd.read_file(C.PROCESSED / "setores_santa_maria.gpkg").set_index("CD_SETOR")
    aval_ref = avaliar_refugios(setores)
    plantio = recomendar_plantio(setores)

    setores.to_file(C.PROCESSED / "setores_santa_maria.gpkg", driver="GPKG")
    pd.DataFrame(setores.drop(columns="geometry")).to_csv(C.PROCESSED / "setores_santa_maria.csv")
    web = setores.to_crs(4326)
    web["geometry"] = web.geometry.simplify(0.00005)
    web.reset_index().to_file(C.PROCESSED / "setores_santa_maria.geojson", driver="GeoJSON")
    bairros = (setores.groupby("bairro").agg(beneficio=("beneficio_idoso_grau", "sum"),
                                             idosos=("idosos_60_mais", "sum"), lst=("lst_media", "mean"),
                                             ndvi=("ndvi_media", "mean"))
               .sort_values("beneficio", ascending=False))
    bairros.round(3).to_csv(C.PROCESSED / "plantio_por_bairro.csv")

    # Casos de teste com perfis (personas)
    personas = {
        "Dona Maria, 78 anos, Tancredo Neves, quarta 14h, anda até 500 m, precisa de ar-condicionado":
            Perfil(-29.6955, -53.8580, 2, 14, 500, "climatizado"),
        "Seu João, 82 anos, Centro, domingo 15h, anda até 800 m, precisa de ar-condicionado":
            Perfil(-29.6847, -53.8069, 6, 15, 800, "climatizado"),
        "Cuidadora de idoso com hipertensão, Camobi, sexta 10h, de carro (3 km), precisa de atendimento":
            Perfil(-29.7010, -53.7170, 4, 10, 3000, "atendimento"),
    }
    exemplos = {}
    for nome, p in personas.items():
        rec = recomendar_refugios(p)
        exemplos[nome] = rec["explicacao"].tolist()
        print(f"\n{nome}:")
        for i, e in enumerate(rec["explicacao"], 1):
            print(f"   {i}. {e}")

    metricas = {"refugios": aval_ref, "plantio": plantio, "pesos_refugio": PESOS, "exemplos_personas": exemplos}
    (C.MODELOS / "metricas_recomendacao.json").write_text(json.dumps(metricas, indent=2, ensure_ascii=False),
                                                          encoding="utf-8")
    print("\nAvaliação refúgios:", json.dumps(aval_ref, indent=1, ensure_ascii=False))
    print("\nPlantio:", json.dumps(plantio, indent=1, ensure_ascii=False))
    print("\nTop 8 bairros para plantio:\n", bairros.head(8).round(2).to_string())


if __name__ == "__main__":
    main()

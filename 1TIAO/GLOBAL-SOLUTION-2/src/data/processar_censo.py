"""Base integrada por setor censitário: população idosa (Censo 2022) + calor e vegetação (Landsat).

Entrada : data/raw/ibge/*  e  data/processed/landsat_*_verao_mediana.tif
Saída   : data/processed/setores_santa_maria.gpkg  (geometria em UTM 22S)
          data/processed/setores_santa_maria.geojson (WGS84, para mapas web)
          data/processed/setores_santa_maria.csv     (sem geometria)

Recorte: setores urbanos do distrito-sede de Santa Maria (406 setores, ~94% da
população do município). Setores rurais e de distritos afastados ficam de fora
porque o fenômeno de ilha de calor é urbano.

Valores sigilosos do IBGE (marcados com "X" em setores muito pequenos) viram
ausentes (NaN) e são tratados na análise.

Uso: python -m src.data.processar_censo
"""
from __future__ import annotations

import zipfile

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize

from src import config as C

VARS_DEMO = {"V01006": "moradores", "V01040": "pop_60_69", "V01041": "pop_70_mais"}
VARS_ALFA = {
    "V00653": "p60_64", "V00654": "p65_69", "V00655": "p70_79", "V00656": "p80_mais",
    "V00757": "alf60_64", "V00758": "alf65_69", "V00759": "alf70_79", "V00760": "alf80_mais",
}


def _ler_csv_zip(caminho, variaveis: dict) -> pd.DataFrame:
    """Lê do CSV nacional (dentro do zip) apenas os setores de Santa Maria."""
    with zipfile.ZipFile(caminho) as z:
        nome = z.namelist()[0]
        partes = []
        with z.open(nome) as f:
            for bloco in pd.read_csv(f, sep=";", dtype=str, encoding="latin-1", chunksize=200_000,
                                     usecols=lambda c: c in {"CD_setor", "CD_SETOR", *variaveis}):
                bloco.columns = [c.upper() if c.lower() == "cd_setor" else c for c in bloco.columns]
                partes.append(bloco[bloco["CD_SETOR"].str.startswith(C.COD_IBGE_7)])
    df = pd.concat(partes).set_index("CD_SETOR").rename(columns=variaveis)
    return df.apply(pd.to_numeric, errors="coerce")  # "X" (sigilo) -> NaN


def _estatisticas_zonais(gdf: gpd.GeoDataFrame, raster: str, prefixo: str) -> pd.DataFrame:
    caminho = C.PROCESSED / raster
    if not caminho.exists():
        print(f"  (sem {raster} - rode src.data.processar_landsat)")
        return pd.DataFrame(index=gdf.index)
    with rasterio.open(caminho) as src:
        arr = src.read(1)
        ids = rasterize(((geom, i + 1) for i, geom in enumerate(gdf.geometry)), out_shape=arr.shape,
                        transform=src.transform, fill=0, dtype="int32", all_touched=False)
    ok = (ids > 0) & np.isfinite(arr)
    s = pd.DataFrame({"id": ids[ok] - 1, "v": arr[ok]}).groupby("id")["v"]
    est = pd.DataFrame({f"{prefixo}_media": s.mean(), f"{prefixo}_p90": s.quantile(0.9),
                        f"{prefixo}_pixels": s.size()})
    est.index = gdf.index[est.index]
    return est


def main() -> None:
    print("Lendo malha de setores...")
    g = gpd.read_file(C.RAW / "ibge" / "RS_setores_CD2022.gpkg", where=f"CD_MUN='{C.COD_IBGE_7}'")
    g = g[(g.SITUACAO == "Urbana") & (g.NM_DIST == C.MUNICIPIO)].copy()
    g = g.to_crs(C.CRS_METRICO).set_index("CD_SETOR")
    g = g[["NM_BAIRRO", "NM_SUBDIST", "AREA_KM2", "v0001", "v0002", "v0005", "geometry"]].rename(columns={
        "NM_BAIRRO": "bairro", "NM_SUBDIST": "subdistrito", "AREA_KM2": "area_km2",
        "v0001": "pessoas", "v0002": "domicilios", "v0005": "moradores_por_domicilio"})
    print(f"  {len(g)} setores urbanos do distrito-sede")

    print("Lendo demografia (idade)...")
    demo = _ler_csv_zip(C.RAW / "ibge" / "Agregados_por_setores_demografia_BR.zip", VARS_DEMO)
    print("Lendo alfabetização por idade...")
    alfa = _ler_csv_zip(C.RAW / "ibge" / "Agregados_por_setores_alfabetizacao_BR.zip", VARS_ALFA)

    df = g.join(demo).join(alfa)
    df["idosos_60_mais"] = df["pop_60_69"] + df["pop_70_mais"]
    df["pct_idosos"] = 100 * df["idosos_60_mais"] / df["moradores"]
    df["pct_70_mais"] = 100 * df["pop_70_mais"] / df["moradores"]
    df["densidade_hab_km2"] = df["pessoas"] / df["area_km2"]
    tot60 = df[["p60_64", "p65_69", "p70_79", "p80_mais"]].sum(axis=1, min_count=1)
    alf60 = df[["alf60_64", "alf65_69", "alf70_79", "alf80_mais"]].sum(axis=1, min_count=1)
    df["pct_idosos_nao_alfabetizados"] = 100 * (1 - alf60 / tot60)
    df = df.drop(columns=list(VARS_ALFA.values()))

    print("Cruzando com temperatura de superfície e NDVI (Landsat)...")
    df = df.join(_estatisticas_zonais(df, "landsat_lst_verao_mediana.tif", "lst"))
    df = df.join(_estatisticas_zonais(df, "landsat_ndvi_verao_mediana.tif", "ndvi"))
    if "lst_media" in df:
        # anomalia: quanto o setor é mais quente que a média urbana (intensidade da ilha de calor)
        df["lst_anomalia"] = df["lst_media"] - df["lst_media"].mean()

    gdf = gpd.GeoDataFrame(df, geometry="geometry", crs=C.CRS_METRICO)
    gdf.to_file(C.PROCESSED / "setores_santa_maria.gpkg", driver="GPKG")
    web = gdf.to_crs(4326)
    web["geometry"] = web.geometry.simplify(0.00005)
    web.reset_index().to_file(C.PROCESSED / "setores_santa_maria.geojson", driver="GeoJSON")
    pd.DataFrame(gdf.drop(columns="geometry")).to_csv(C.PROCESSED / "setores_santa_maria.csv")

    print(f"Salvo: {len(gdf)} setores | moradores {gdf.moradores.sum():,.0f} | "
          f"idosos 60+ {gdf.idosos_60_mais.sum():,.0f} ({100*gdf.idosos_60_mais.sum()/gdf.moradores.sum():.1f}%)")
    print(gdf.drop(columns="geometry").describe().T[["count", "mean", "min", "max"]].round(2))


if __name__ == "__main__":
    main()

"""Aplica a CNN de uso do solo a uma imagem Sentinel-2 real de Santa Maria.

1. Busca a cena Sentinel-2 L2A de verão com menos nuvens sobre a cidade
   (Planetary Computer) e lê as bandas RGB (10 m) só na janela urbana.
2. Ajusta o brilho da cena para a mesma distribuição de cores das imagens de
   treino (EuroSAT), reduzindo a diferença de domínio entre os dois conjuntos.
3. Percorre a cidade com uma janela deslizante de 64x64 px (640 m), passo de
   16 px (160 m). Cada pixel recebe a média das probabilidades de todas as
   janelas que o cobrem, o que gera um mapa contínuo de "área construída".
4. Calcula a fração construída média de cada setor censitário e a valida
   contra medidas independentes (NDVI e temperatura de superfície do Landsat).

Saídas: data/processed/cnn_prob_construido.tif, coluna `frac_construida_cnn`
em setores_santa_maria.*, docs/img/cnn_santa_maria.png

Uso: python -m src.ml.aplicar_cnn
"""
from __future__ import annotations

import json

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import planetary_computer
import pystac_client
import rasterio
import torch
from rasterio.enums import Resampling
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

from src import config as C
from src.ml.cnn_eurosat import CNNPequena, criar_resnet18

RES, JANELA, PASSO = 10, 64, 16


def carregar_modelo():
    ck = torch.load(C.MODELOS / "cnn_uso_solo.pt", map_location="cpu", weights_only=False)
    m = CNNPequena() if ck["arquitetura"] == "cnn_pequena" else criar_resnet18(pretreinada=False)
    m.load_state_dict({k: v.float() for k, v in ck["estado"].items()})
    return m.eval(), ck


def ler_sentinel2():
    cat = pystac_client.Client.open("https://planetarycomputer.microsoft.com/api/stac/v1",
                                    modifier=planetary_computer.sign_inplace)
    itens = list(cat.search(collections=["sentinel-2-l2a"], bbox=C.BBOX_URBANA,
                            datetime="2024-12-01/2025-03-31", query={"eo:cloud_cover": {"lt": 5}}).items())
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", C.CRS_METRICO, *C.BBOX_URBANA)
    w, h = int(np.ceil((x1 - x0) / RES)), int(np.ceil((y1 - y0) / RES))
    transform = from_origin(x0, y1, RES, RES)
    for it in sorted(itens, key=lambda i: i.properties["eo:cloud_cover"]):
        bandas = []
        for b in ("B04", "B03", "B02"):
            with rasterio.open(it.assets[b].href) as src, WarpedVRT(
                    src, crs=C.CRS_METRICO, transform=transform, width=w, height=h,
                    resampling=Resampling.bilinear) as vrt:
                bandas.append(vrt.read(1).astype("float32"))
        rgb = np.stack(bandas, -1)
        if (rgb == 0).any(-1).mean() > 0.01:  # cena não cobre a cidade inteira
            continue
        offset = 1000 if float(it.properties.get("s2:processing_baseline", "0")) >= 4 else 0
        refl = (rgb - offset) / 10000.0
        info = {"id": it.id, "data": f"{it.datetime:%Y-%m-%d}", "nuvens_%": it.properties["eo:cloud_cover"]}
        print(f"Cena Sentinel-2: {info}")
        return refl, transform, info
    raise RuntimeError("Nenhuma cena Sentinel-2 cobrindo a cidade")


def ajustar_dominio(refl: np.ndarray, media: torch.Tensor, desvio: torch.Tensor) -> np.ndarray:
    """Casa média e desvio de cada canal com os do EuroSAT (escala 0-1)."""
    out = np.empty_like(refl)
    for c in range(3):
        canal = refl[..., c]
        out[..., c] = (canal - canal.mean()) / canal.std() * float(desvio[c]) + float(media[c])
    return np.clip(out, 0, 1)


def mapa_probabilidades(modelo, img01, media, desvio, lote=256):
    h, w, _ = img01.shape
    t = torch.from_numpy(img01).permute(2, 0, 1).float()
    t = (t - media.view(3, 1, 1)) / desvio.view(3, 1, 1)
    ys = list(range(0, h - JANELA + 1, PASSO))
    xs = list(range(0, w - JANELA + 1, PASSO))
    posicoes = [(y, x) for y in ys for x in xs]
    soma = np.zeros((10, h, w), dtype="float32")
    cont = np.zeros((h, w), dtype="float32")
    print(f"{len(posicoes)} janelas de 64x64 px")
    with torch.no_grad():
        for i in range(0, len(posicoes), lote):
            pos = posicoes[i:i + lote]
            xb = torch.stack([t[:, y:y + JANELA, x:x + JANELA] for y, x in pos])
            prob = torch.softmax(modelo(xb), 1).numpy()
            for (y, x), p in zip(pos, prob):
                soma[:, y:y + JANELA, x:x + JANELA] += p[:, None, None]
                cont[y:y + JANELA, x:x + JANELA] += 1
    return soma / np.maximum(cont, 1)


def main():
    modelo, ck = carregar_modelo()
    refl, transform, info = ler_sentinel2()
    img01 = ajustar_dominio(refl, ck["media"], ck["desvio"])
    prob = mapa_probabilidades(modelo, img01, ck["media"], ck["desvio"])
    grupos = np.array([ck["grupo"][c] for c in ck["classes"]])
    p_constr = prob[grupos == "construido"].sum(0).astype("float32")
    classe = prob.argmax(0).astype("uint8")

    perfil = dict(driver="GTiff", height=p_constr.shape[0], width=p_constr.shape[1], count=1,
                  crs=C.CRS_METRICO, transform=transform, compress="deflate")
    with rasterio.open(C.PROCESSED / "cnn_prob_construido.tif", "w", dtype="float32", **perfil) as dst:
        dst.write(p_constr, 1)
    with rasterio.open(C.PROCESSED / "cnn_classe_uso_solo.tif", "w", dtype="uint8", **perfil) as dst:
        dst.write(classe, 1)

    # Fração construída por setor
    g = gpd.read_file(C.PROCESSED / "setores_santa_maria.gpkg").set_index("CD_SETOR")
    ids = rasterize(((geom, i + 1) for i, geom in enumerate(g.geometry)), out_shape=p_constr.shape,
                    transform=transform, fill=0, dtype="int32")
    ok = ids > 0
    frac = pd.Series(p_constr[ok]).groupby(ids[ok] - 1).mean()
    g["frac_construida_cnn"] = np.nan
    g.iloc[frac.index, g.columns.get_loc("frac_construida_cnn")] = frac.values

    # Validação externa: a CNN nunca viu o NDVI nem a temperatura do Landsat
    v = g[["frac_construida_cnn", "ndvi_media", "lst_media"]].dropna()
    corr = {"construida_x_ndvi": float(v.corr().loc["frac_construida_cnn", "ndvi_media"]),
            "construida_x_lst": float(v.corr().loc["frac_construida_cnn", "lst_media"]),
            "spearman_construida_x_lst": float(v.corr(method="spearman").loc["frac_construida_cnn", "lst_media"])}
    print(f"Validação nos {len(v)} setores: {json.dumps(corr, indent=1)}")
    metr = json.loads((C.MODELOS / "metricas_cnn.json").read_text(encoding="utf-8"))
    metr["aplicacao_santa_maria"] = {"cena": info, "validacao_setores": corr, "n_setores": len(v)}
    (C.MODELOS / "metricas_cnn.json").write_text(json.dumps(metr, indent=2, ensure_ascii=False), encoding="utf-8")

    g.to_file(C.PROCESSED / "setores_santa_maria.gpkg", driver="GPKG")
    pd.DataFrame(g.drop(columns="geometry")).to_csv(C.PROCESSED / "setores_santa_maria.csv")
    web = g.to_crs(4326)
    web["geometry"] = web.geometry.simplify(0.00005)
    web.reset_index().to_file(C.PROCESSED / "setores_santa_maria.geojson", driver="GeoJSON")

    # Figura: imagem real x mapa da CNN
    fig, axs = plt.subplots(1, 2, figsize=(12, 4.6), layout="constrained")
    vis = np.clip(refl / np.percentile(refl, 98, axis=(0, 1)), 0, 1)
    axs[0].imshow(vis)
    axs[0].set_title(f"Sentinel-2 (cor real) – {info['data']}", fontsize=11, loc="left", fontweight="bold")
    im = axs[1].imshow(p_constr, cmap="Greys", vmin=0, vmax=1)
    axs[1].set_title("CNN: probabilidade de área construída", fontsize=11, loc="left", fontweight="bold")
    for a in axs:
        a.set_axis_off()
    fig.colorbar(im, ax=axs[1], shrink=0.7)
    fig.savefig(C.DOCS_IMG / "cnn_santa_maria.png", dpi=180)
    print("salvo docs/img/cnn_santa_maria.png")


if __name__ == "__main__":
    main()

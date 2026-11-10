"""Temperatura de superfície (LST) e vegetação (NDVI) de Santa Maria a partir do Landsat 8/9.

Fonte: Landsat Collection 2 Level-2 (USGS), acessada pelo catálogo STAC do
Microsoft Planetary Computer (gratuito, sem cadastro).

O que o script faz:
1. Busca cenas de verão (dez-mar) com menos de 10% de nuvens sobre a área urbana.
2. Lê apenas a janela da cidade de cada cena (arquivos COG na nuvem, sem baixar a cena inteira).
3. Aplica a máscara de nuvem/sombra (banda QA_PIXEL) e converte para unidades físicas:
      LST (°C) = DN * 0.00341802 + 149.0 - 273.15
      Refletância = DN * 0.0000275 - 0.2   ->   NDVI = (NIR - RED) / (NIR + RED)
4. Calcula a mediana de todas as cenas (composição robusta a nuvens remanescentes).
5. Salva GeoTIFFs em data/processed/ e uma figura em docs/img/.

Uso: python -m src.data.processar_landsat
"""
from __future__ import annotations

import json

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import from_origin
from rasterio.vrt import WarpedVRT
from rasterio.warp import transform_bounds

from src import config as C

RES = 30  # metros (resolução nativa do Landsat)
VERAOS = ["2022-12-01/2023-03-31", "2023-12-01/2024-03-31", "2024-12-01/2025-03-31"]
MAX_NUVEM = 10


def grade_destino():
    """Grade comum em UTM 22S (metros) cobrindo a mancha urbana."""
    x0, y0, x1, y1 = transform_bounds("EPSG:4326", C.CRS_METRICO, *C.BBOX_URBANA)
    largura = int(np.ceil((x1 - x0) / RES))
    altura = int(np.ceil((y1 - y0) / RES))
    transform = from_origin(x0, y1, RES, RES)
    return transform, largura, altura


def buscar_cenas():
    cat = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    itens = []
    for periodo in VERAOS:
        busca = cat.search(
            collections=["landsat-c2-l2"], bbox=C.BBOX_URBANA, datetime=periodo,
            query={"eo:cloud_cover": {"lt": MAX_NUVEM}, "platform": {"in": ["landsat-8", "landsat-9"]}},
        )
        itens.extend(busca.items())
    # remove duplicatas de mesma data/plataforma (cenas sobrepostas de órbitas vizinhas)
    vistos, unicos = set(), []
    for it in sorted(itens, key=lambda i: i.properties["eo:cloud_cover"]):
        chave = (it.datetime.date(), it.properties["platform"])
        if chave not in vistos:
            vistos.add(chave)
            unicos.append(it)
    return sorted(unicos, key=lambda i: i.datetime)


def ler_banda(href, transform, largura, altura, nearest=False):
    with rasterio.open(href) as src:
        with WarpedVRT(src, crs=C.CRS_METRICO, transform=transform, width=largura, height=altura,
                       resampling=Resampling.nearest if nearest else Resampling.bilinear) as vrt:
            return vrt.read(1).astype("float32"), src.nodata


def mascara_nuvem(qa):
    """True onde o pixel é válido (sem nuvem, sombra, cirrus ou preenchimento)."""
    qa = qa.astype("uint16")
    bits_ruins = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 4)  # fill, dilated, cirrus, cloud, shadow
    return (qa & bits_ruins) == 0


def processar():
    transform, largura, altura = grade_destino()
    itens = buscar_cenas()
    print(f"{len(itens)} cenas de verão com <{MAX_NUVEM}% de nuvens")
    pilhas_lst, pilhas_ndvi, usadas = [], [], []
    for it in itens:
        try:
            qa, _ = ler_banda(it.assets["qa_pixel"].href, transform, largura, altura, nearest=True)
            st, _ = ler_banda(it.assets["lwir11"].href, transform, largura, altura)
            red, _ = ler_banda(it.assets["red"].href, transform, largura, altura)
            nir, _ = ler_banda(it.assets["nir08"].href, transform, largura, altura)
        except Exception as e:  # noqa: BLE001
            print(f"  pulando {it.id}: {e}")
            continue
        ok = mascara_nuvem(qa) & (st > 0) & (red > 0) & (nir > 0)
        frac = ok.mean()
        if frac < 0.8:  # cena cobre pouco da cidade ou tem nuvem sobre ela
            print(f"  {it.datetime:%Y-%m-%d} {it.properties['platform']}: só {frac:.0%} válido - descartada")
            continue
        lst = np.where(ok, st * 0.00341802 + 149.0 - 273.15, np.nan)
        r = red * 0.0000275 - 0.2
        n = nir * 0.0000275 - 0.2
        ndvi = np.where(ok, (n - r) / np.clip(n + r, 1e-6, None), np.nan)
        pilhas_lst.append(lst)
        pilhas_ndvi.append(np.clip(ndvi, -1, 1))
        usadas.append({"id": it.id, "data": f"{it.datetime:%Y-%m-%d}", "plataforma": it.properties["platform"],
                       "nuvens_cena_%": it.properties["eo:cloud_cover"], "lst_media_C": float(np.nanmean(lst))})
        print(f"  {it.datetime:%Y-%m-%d} {it.properties['platform']}: LST média {np.nanmean(lst):.1f} °C")

    if not usadas:
        raise RuntimeError("Nenhuma cena válida encontrada")
    lst_med = np.nanmedian(np.stack(pilhas_lst), axis=0).astype("float32")
    ndvi_med = np.nanmedian(np.stack(pilhas_ndvi), axis=0).astype("float32")

    perfil = dict(driver="GTiff", height=altura, width=largura, count=1, dtype="float32",
                  crs=C.CRS_METRICO, transform=transform, nodata=np.nan, compress="deflate")
    for nome, arr in (("landsat_lst_verao_mediana.tif", lst_med), ("landsat_ndvi_verao_mediana.tif", ndvi_med)):
        with rasterio.open(C.PROCESSED / nome, "w", **perfil) as dst:
            dst.write(arr, 1)
        print(f"salvo data/processed/{nome}")
    (C.PROCESSED / "landsat_cenas_usadas.json").write_text(json.dumps(usadas, indent=2, ensure_ascii=False),
                                                          encoding="utf-8")
    print(f"{len(usadas)} cenas usadas; LST mediana da cidade: {np.nanmedian(lst_med):.1f} °C "
          f"(p5={np.nanpercentile(lst_med, 5):.1f}, p95={np.nanpercentile(lst_med, 95):.1f})")


if __name__ == "__main__":
    processar()

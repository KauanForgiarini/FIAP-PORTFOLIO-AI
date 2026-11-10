"""Download das bases de dados públicas usadas no projeto.

Uso (a partir da pasta GLOBAL-SOLUTION-2):
    python -m src.data.baixar_dados            # baixa tudo
    python -m src.data.baixar_dados clima censo  # apenas algumas fontes

Cada fonte é baixada uma única vez para data/raw/ (se o arquivo já existe,
o download é pulado). Fontes e licenças estão descritas em data/README.md.
"""
from __future__ import annotations

import gzip
import io
import shutil
import sys
import time
import urllib.request
from pathlib import Path

import pandas as pd
import requests

from src import config as C

TIMEOUT = 120


def _baixar(url: str, destino: Path, tentativas: int = 3) -> Path:
    """Baixa `url` para `destino` (http(s) ou ftp), com novas tentativas."""
    if destino.exists() and destino.stat().st_size > 0:
        print(f"  ✓ já existe: {destino.relative_to(C.RAIZ)}")
        return destino
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(destino.suffix + ".part")
    for i in range(1, tentativas + 1):
        try:
            print(f"  ↓ {url}")
            if url.startswith("ftp://"):
                with urllib.request.urlopen(url, timeout=TIMEOUT) as r, open(tmp, "wb") as f:
                    shutil.copyfileobj(r, f)
            else:
                with requests.get(url, stream=True, timeout=TIMEOUT) as r:
                    r.raise_for_status()
                    with open(tmp, "wb") as f:
                        for bloco in r.iter_content(chunk_size=1 << 20):
                            f.write(bloco)
            tmp.replace(destino)
            print(f"    salvo em {destino.relative_to(C.RAIZ)} ({destino.stat().st_size/1e6:.1f} MB)")
            return destino
        except Exception as e:  # noqa: BLE001 - registramos e tentamos de novo
            print(f"    falha (tentativa {i}/{tentativas}): {e}")
            time.sleep(5 * i)
    raise RuntimeError(f"Não foi possível baixar {url}")


# --------------------------------------------------------------------------
# 1. Clima
# --------------------------------------------------------------------------
def clima() -> None:
    """Observações diárias da estação 83936 (Meteostat) + reanálise ERA5 (Open-Meteo)."""
    print("[clima]")
    pasta = C.RAW / "clima"
    # 1a. Estação meteorológica de Santa Maria (observações reais, redistribuídas pelo Meteostat)
    destino = pasta / f"meteostat_{C.ESTACAO_OMM}_diario.csv"
    if not destino.exists():
        url = f"https://bulk.meteostat.net/v2/daily/{C.ESTACAO_OMM}.csv.gz"
        print(f"  ↓ {url}")
        r = requests.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        cols = ["data", "tavg", "tmin", "tmax", "prcp", "snow", "wdir", "wspd", "wpgt", "pres", "tsun"]
        df = pd.read_csv(io.BytesIO(gzip.decompress(r.content)), names=cols, parse_dates=["data"])
        pasta.mkdir(parents=True, exist_ok=True)
        df.to_csv(destino, index=False)
        print(f"    {len(df)} dias ({df.data.min():%d/%m/%Y} a {df.data.max():%d/%m/%Y})")
    else:
        print(f"  ✓ já existe: {destino.relative_to(C.RAIZ)}")

    # 1b. Série longa (1991-2025) da reanálise ERA5 via Open-Meteo, para climatologia e tendência
    destino = pasta / "openmeteo_era5_diario_1991_2025.csv"
    if not destino.exists():
        params = {
            "latitude": C.CENTRO_LAT, "longitude": C.CENTRO_LON,
            "start_date": "1991-01-01", "end_date": "2025-12-31",
            "daily": "temperature_2m_max,temperature_2m_min,temperature_2m_mean,"
                     "apparent_temperature_max,relative_humidity_2m_mean,precipitation_sum",
            "timezone": "America/Sao_Paulo",
        }
        print("  ↓ Open-Meteo archive (ERA5) 1991-2025")
        r = requests.get("https://archive-api.open-meteo.com/v1/archive", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        df = pd.DataFrame(r.json()["daily"]).rename(columns={"time": "data"})
        df.to_csv(destino, index=False)
        print(f"    {len(df)} dias")
    else:
        print(f"  ✓ já existe: {destino.relative_to(C.RAIZ)}")


# --------------------------------------------------------------------------
# 2. IBGE - Censo 2022
# --------------------------------------------------------------------------
IBGE_AGREG = "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios"


def censo() -> None:
    """Malha de setores do RS com atributos + tabelas de demografia (idade) por setor."""
    print("[censo]")
    pasta = C.RAW / "ibge"
    _baixar(f"{IBGE_AGREG}/malha_com_atributos/setores/gpkg/UF/RS/RS_setores_CD2022.gpkg",
            pasta / "RS_setores_CD2022.gpkg")
    _baixar(f"{IBGE_AGREG}/malha_com_atributos/bairros/gpkg/UF/RS/RS_bairros_CD2022.gpkg",
            pasta / "RS_bairros_CD2022.gpkg")
    _baixar(f"{IBGE_AGREG}/Agregados_por_Setor_csv/Agregados_por_setores_demografia_BR.zip",
            pasta / "Agregados_por_setores_demografia_BR.zip")
    _baixar(f"{IBGE_AGREG}/Agregados_por_Setor_csv/Agregados_por_setores_alfabetizacao_BR.zip",
            pasta / "Agregados_por_setores_alfabetizacao_BR.zip")
    _baixar(f"{IBGE_AGREG}/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx",
            pasta / "dicionario_agregados_setores.xlsx")


# --------------------------------------------------------------------------
# 3. DATASUS - mortalidade (SIM) e internações (SIH) do RS
# --------------------------------------------------------------------------
def datasus(anos_sim=range(2020, 2025), anos_sih=range(2021, 2026)) -> None:
    print("[datasus]")
    pasta = C.RAW / "datasus"
    for ano in anos_sim:
        _baixar(f"ftp://ftp.datasus.gov.br/dissemin/publicos/SIM/CID10/DORES/DORS{ano}.dbc",
                pasta / "sim" / f"DORS{ano}.dbc")
    for ano in anos_sih:
        for mes in range(1, 13):
            nome = f"RDRS{ano % 100:02d}{mes:02d}.dbc"
            try:
                _baixar(f"ftp://ftp.datasus.gov.br/dissemin/publicos/SIHSUS/200801_/Dados/{nome}",
                        pasta / "sih" / nome, tentativas=2)
            except RuntimeError:
                print(f"    (sem arquivo {nome} - provavelmente ainda não publicado)")


# --------------------------------------------------------------------------
# 4. EuroSAT (imagens Sentinel-2 rotuladas, para treinar a CNN)
# --------------------------------------------------------------------------
def eurosat() -> None:
    print("[eurosat]")
    _baixar("https://zenodo.org/records/7711810/files/EuroSAT_RGB.zip?download=1",
            C.RAW / "eurosat" / "EuroSAT_RGB.zip")


# --------------------------------------------------------------------------
# 5. OpenStreetMap (árvores, parques, equipamentos públicos)
# --------------------------------------------------------------------------
OVERPASS = ["https://overpass-api.de/api/interpreter",
            "https://overpass.private.coffee/api/interpreter",
            "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]


def osm() -> None:
    print("[osm]")
    destino = C.RAW / "osm" / "santa_maria_osm.json"
    if destino.exists():
        print(f"  ✓ já existe: {destino.relative_to(C.RAIZ)}")
        return
    lon0, lat0, lon1, lat1 = C.BBOX_URBANA
    bbox = f"{lat0},{lon0},{lat1},{lon1}"
    consulta = f"""[out:json][timeout:180];
(
  node["natural"="tree"]({bbox});
  way["leisure"~"^(park|garden)$"]({bbox});
  relation["leisure"="park"]({bbox});
  way["landuse"~"^(forest|grass|recreation_ground)$"]({bbox});
  nwr["amenity"~"^(hospital|clinic|doctors|library|community_centre|social_facility|place_of_worship|townhall)$"]({bbox});
  nwr["healthcare"]({bbox});
  nwr["shop"="mall"]({bbox});
);
out center tags;"""
    for url in OVERPASS:
        try:
            print(f"  ↓ Overpass: {url}")
            # A política de uso do Overpass pede um User-Agent que identifique a aplicação
            r = requests.post(url, data={"data": consulta}, timeout=240,
                              headers={"User-Agent": "Refugio-GS-FIAP/1.0 (projeto academico, Santa Maria-RS)"})
            r.raise_for_status()
            js = r.json()
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(r.text, encoding="utf-8")
            print(f"    {len(js.get('elements', []))} elementos")
            return
        except Exception as e:  # noqa: BLE001
            print(f"    falha: {e}")
    print("  ! OSM indisponível no momento — rode novamente mais tarde: python -m src.data.baixar_dados osm")


FONTES = {"clima": clima, "censo": censo, "datasus": datasus, "eurosat": eurosat, "osm": osm}

if __name__ == "__main__":
    escolhidas = sys.argv[1:] or list(FONTES)
    for nome in escolhidas:
        FONTES[nome]()
    print("Concluído.")

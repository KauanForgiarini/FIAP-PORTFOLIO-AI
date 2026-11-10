"""Candidatos a refúgio climático e instituições de idosos a partir do OpenStreetMap.

Refúgio climático: local público ou de acesso livre onde uma pessoa idosa pode
passar as horas mais quentes do dia em segurança (ambiente climatizado ou
sombreado, com água e alguém por perto). Categorias consideradas:

    saude        Unidades Básicas de Saúde / ESF / hospitais públicos (têm equipe e água)
    assistencia  CRAS, centros comunitários e restaurantes populares
    biblioteca   bibliotecas
    shopping     shoppings (climatizados, abertos todos os dias)
    parque       parques e praças com sombra (só de dia; refúgio "ao ar livre")

Também extraímos as ILPIs (instituições de longa permanência para idosos), que
recebem alerta prioritário.

Horários de funcionamento: quando o OSM não informa, usamos um horário típico da
categoria (premissa documentada em HORARIO_PADRAO).

Saída: data/processed/refugios.geojson e data/processed/ilpis.geojson
Uso  : python -m src.data.processar_osm
"""
from __future__ import annotations

import json
import re

import geopandas as gpd
import pandas as pd
from shapely.geometry import Point

from src import config as C

# (dias da semana 0=seg..6=dom, hora_inicio, hora_fim)
HORARIO_PADRAO = {
    "saude": ([0, 1, 2, 3, 4], 8, 17),
    "assistencia": ([0, 1, 2, 3, 4], 8, 17),
    "biblioteca": ([0, 1, 2, 3, 4], 8, 18),
    "shopping": ([0, 1, 2, 3, 4, 5, 6], 10, 22),
    "parque": ([0, 1, 2, 3, 4, 5, 6], 6, 20),
}
CLIMATIZADO = {"saude": True, "assistencia": True, "biblioteca": True, "shopping": True, "parque": False}
SAUDE_PUBLICA = re.compile(r"(unidade b[aá]sica|estrat[eé]gia sa[uú]de|\bUBS\b|\bESF\b|hospital|pronto|UPA|policl)",
                           re.I)


def categoria(tags: dict) -> str | None:
    amen, nome = tags.get("amenity", ""), tags.get("name", "")
    if amen in ("clinic", "hospital", "doctors") or tags.get("healthcare") in ("clinic", "hospital"):
        return "saude" if SAUDE_PUBLICA.search(nome) else None  # consultórios privados ficam de fora
    if amen == "library":
        return "biblioteca"
    if amen in ("community_centre",) or (amen == "social_facility" and re.search(r"CRAS|restaurante popular", nome, re.I)):
        return "assistencia"
    if tags.get("shop") == "mall":
        return "shopping"
    if tags.get("leisure") in ("park", "garden") and nome:
        return "parque"
    return None


def main():
    elementos = json.loads((C.RAW / "osm" / "santa_maria_osm.json").read_text(encoding="utf-8"))["elements"]
    refugios, ilpis = [], []
    for e in elementos:
        tags = e.get("tags", {})
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None:
            continue
        if tags.get("social_facility") == "nursing_home" or re.search(r"geri[aá]tric|lar de idosos|ILPI", tags.get("name", ""), re.I):
            ilpis.append({"nome": tags.get("name", "ILPI sem nome"), "osm_id": f"{e['type']}/{e['id']}",
                          "geometry": Point(lon, lat)})
            continue
        cat = categoria(tags)
        if cat is None:
            continue
        dias, h0, h1 = HORARIO_PADRAO[cat]
        refugios.append({"nome": tags.get("name", cat.capitalize()), "categoria": cat,
                         "climatizado": CLIMATIZADO[cat], "dias_abertos": ",".join(map(str, dias)),
                         "abre": h0, "fecha": h1, "horario_osm": tags.get("opening_hours", ""),
                         "endereco": " ".join(filter(None, [tags.get("addr:street"), tags.get("addr:housenumber")])),
                         "osm_id": f"{e['type']}/{e['id']}", "geometry": Point(lon, lat)})

    ref = gpd.GeoDataFrame(refugios, crs=4326).drop_duplicates(subset=["nome", "categoria"])
    # mantém apenas o que está dentro da mancha urbana analisada
    setores = gpd.read_file(C.PROCESSED / "setores_santa_maria.gpkg").to_crs(4326)
    area = setores.union_all().buffer(0.005)
    ref = ref[ref.within(area)].reset_index(drop=True)
    ref.to_file(C.PROCESSED / "refugios.geojson", driver="GeoJSON")
    ilp = gpd.GeoDataFrame(ilpis, crs=4326)
    ilp.to_file(C.PROCESSED / "ilpis.geojson", driver="GeoJSON")
    print(f"{len(ref)} refúgios candidatos:\n{ref.categoria.value_counts().to_string()}")
    print(f"{len(ilp)} ILPIs: {', '.join(ilp.nome)}")


if __name__ == "__main__":
    main()

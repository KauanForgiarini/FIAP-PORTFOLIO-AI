"""Cria e carrega o banco relacional do Refúgio (SQLite) e executa as consultas de negócio.

    python -m src.db.banco            # recria data/processed/refugio.db e roda as consultas

Tabelas com dados reais: bairro, setor, refugio, ilpi, clima_diario, saude_diaria.
Tabelas com dados SIMULADOS (coluna simulado = 1): pessoa_idosa, cuidador,
pessoa_cuidador, sensor, leitura_sensor, alerta. Os nomes são fictícios, gerados
a partir de listas de nomes comuns, e os telefones são mascarados.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from src import config as C

DB = C.PROCESSED / "refugio.db"
PASTA = Path(__file__).parent

NOMES_F = ["Maria", "Ana", "Terezinha", "Lourdes", "Iracema", "Neusa", "Zilá", "Olga", "Ilse", "Nair", "Elza",
           "Dirce", "Gertrudes", "Celina", "Ivone", "Marlene", "Lúcia", "Vera", "Irma", "Zulmira"]
NOMES_M = ["João", "José", "Antônio", "Pedro", "Valdir", "Arno", "Darci", "Ivo", "Nelson", "Osvaldo", "Alcides",
           "Ernesto", "Lauro", "Hélio", "Silvino", "Dorvalino", "Ari", "Celso", "Jacó", "Orlando"]
SOBRENOMES = ["Silva", "Santos", "Oliveira", "Pereira", "Rodrigues", "Machado", "Rossato", "Pozzobon", "Dalla Corte",
              "Brondani", "Cassol", "Londero", "Mello", "Fagundes", "Ribeiro", "Moraes", "Flores", "Carvalho"]


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.execute("PRAGMA foreign_keys = ON")
    return con


def _executar_script(con, arquivo: str):
    con.executescript((PASTA / arquivo).read_text(encoding="utf-8"))


def carregar_reais(con):
    s = gpd.read_file(C.PROCESSED / "setores_santa_maria.gpkg")
    pts = s.geometry.representative_point().to_crs(4326)
    bairros = pd.DataFrame({"nome": sorted(s["bairro"].dropna().unique())})
    bairros["id_bairro"] = range(1, len(bairros) + 1)
    bairros.to_sql("bairro", con, if_exists="append", index=False)
    idb = dict(zip(bairros.nome, bairros.id_bairro))

    def col(nome, padrao=np.nan):
        return s[nome] if nome in s else padrao

    setor = pd.DataFrame({
        "cd_setor": s["CD_SETOR"], "id_bairro": s["bairro"].map(idb), "area_km2": s["area_km2"],
        "moradores": col("moradores"), "idosos_60_mais": col("idosos_60_mais"), "pct_idosos": col("pct_idosos"),
        "pct_70_mais": col("pct_70_mais"), "pct_idosos_nao_alfab": col("pct_idosos_nao_alfabetizados"),
        "lst_media": col("lst_media"), "ndvi_media": col("ndvi_media"),
        "frac_construida_cnn": col("frac_construida_cnn"), "dist_refugio_km": col("dist_refugio_km"),
        "indice_risco": col("indice_risco"), "prioridade": col("prioridade", None),
        "cluster": col("cluster"), "perfil_cluster": col("perfil_cluster", None),
        "resfriamento_pot_c": col("resfriamento_potencial_C"), "rank_plantio": col("rank_plantio"),
        "lat": pts.y.values, "lon": pts.x.values})
    setor.to_sql("setor", con, if_exists="append", index=False)

    setores_4326 = s[["CD_SETOR", "geometry"]].to_crs(4326)
    for arq, tabela in (("refugios.geojson", "refugio"), ("ilpis.geojson", "ilpi")):
        g = gpd.read_file(C.PROCESSED / arq)
        g = gpd.sjoin(g, setores_4326, how="left", predicate="within").drop_duplicates("osm_id")
        df = pd.DataFrame({"nome": g["nome"], "lat": g.geometry.y, "lon": g.geometry.x, "cd_setor": g["CD_SETOR"]})
        if tabela == "refugio":
            df = df.assign(categoria=g["categoria"], climatizado=g["climatizado"].astype(int),
                           dias_abertos=g["dias_abertos"], hora_abre=g["abre"], hora_fecha=g["fecha"],
                           osm_id=g["osm_id"])
        df.to_sql(tabela, con, if_exists="append", index=False)

    clima = pd.read_csv(C.PROCESSED / "clima_diario.csv", parse_dates=["data"])
    pd.DataFrame({"data": clima.data.dt.strftime("%Y-%m-%d"), "tmax": clima.tmax, "tmin_estacao": clima.tmin_estacao,
                  "fonte_tmax": clima.fonte_tmax, "dia_quente": clima.dia_quente_abs.astype(int),
                  "onda_calor": clima.onda_calor.astype(int)}).to_sql("clima_diario", con, if_exists="append", index=False)

    saude = pd.read_csv(C.PROCESSED / "saude_diaria.csv")
    saude.rename(columns={"obitos_idosos_sensivel_calor": "obitos_idosos_sens_calor",
                          "internacoes_idosos_sensivel_calor": "intern_idosos_sens_calor"})[
        ["data", "recorte", "obitos_idosos", "obitos_idosos_sens_calor", "internacoes_idosos",
         "intern_idosos_sens_calor"]].to_sql("saude_diaria", con, if_exists="append", index=False)


def carregar_simulados(con, n_pessoas: int = 300, semente: int = 7):
    """Cadastro FICTÍCIO de idosos e cuidadores, distribuído como a população real (Censo)."""
    rng = np.random.default_rng(semente)
    setores = pd.read_sql("SELECT cd_setor, idosos_60_mais, pct_idosos_nao_alfab FROM setor", con).fillna(0)
    p = setores.idosos_60_mais / setores.idosos_60_mais.sum()
    escolhidos = rng.choice(setores.index, size=n_pessoas, p=p)
    pessoas, cuidadores, vinculos = [], [], []
    for i, idx in enumerate(escolhidos, start=1):
        st = setores.loc[idx]
        mulher = rng.random() < 0.57  # mulheres são maioria entre idosos
        nome = f"{rng.choice(NOMES_F if mulher else NOMES_M)} {rng.choice(SOBRENOMES)} (fictício)"
        idade = int(min(100, 60 + rng.gamma(2.2, 6.5)))
        pessoas.append({
            "id_pessoa": i, "nome": nome, "ano_nascimento": 2026 - idade, "cd_setor": st.cd_setor,
            "alfabetizada": int(rng.random() > st.pct_idosos_nao_alfab / 100),
            "mobilidade_m": int(rng.choice([300, 500, 800, 1500], p=[0.2, 0.3, 0.35, 0.15]) if idade < 85 else 300),
            "necessidade": rng.choice(["climatizado", "atendimento", "sombra"], p=[0.7, 0.2, 0.1]),
            "mora_sozinha": int(rng.random() < 0.18),
            "consentimento_lgpd": 1, "data_consentimento": "2026-11-01", "simulado": 1})
        relacao = rng.choice(["familiar", "cuidador", "agente_saude", "vizinho"], p=[0.6, 0.15, 0.15, 0.1])
        canal = "ligacao_voz" if not pessoas[-1]["alfabetizada"] else rng.choice(["whatsapp", "sms"], p=[0.8, 0.2])
        cuidadores.append({"id_cuidador": i, "nome": f"Contato de {nome.split(' (')[0]}", "relacao": relacao,
                           "telefone_mascarado": f"(55) 9****-{rng.integers(1000, 9999)}",
                           "canal_preferido": canal, "simulado": 1})
        vinculos.append({"id_pessoa": i, "id_cuidador": i, "principal": 1})
    pd.DataFrame(pessoas).to_sql("pessoa_idosa", con, if_exists="append", index=False)
    pd.DataFrame(cuidadores).to_sql("cuidador", con, if_exists="append", index=False)
    pd.DataFrame(vinculos).to_sql("pessoa_cuidador", con, if_exists="append", index=False)

    # sensores simulados (Wokwi) em dois pontos de contraste: bairro quente x área arborizada
    con.executemany("INSERT INTO sensor VALUES (?,?,?,?,?,?)", [
        ("ESP32-SM-01", "Tancredo Neves - área sem arborização", "wokwi_simulado", -29.6955, -53.8580,
         _setor_do_ponto(con, -29.6955, -53.8580)),
        ("ESP32-SM-02", "Praça arborizada - Centro", "wokwi_simulado", -29.6866, -53.8066,
         _setor_do_ponto(con, -29.6866, -53.8066)),
    ])


def _setor_do_ponto(con, lat, lon):
    df = pd.read_sql("SELECT cd_setor, lat, lon FROM setor", con)
    return df.loc[((df.lat - lat) ** 2 + (df.lon - lon) ** 2).idxmin(), "cd_setor"]


def consultas(con) -> dict[str, pd.DataFrame]:
    """Executa cada consulta nomeada de consultas.sql (blocos iniciados por '-- @nome')."""
    texto = (PASTA / "consultas.sql").read_text(encoding="utf-8")
    blocos = re.split(r"^-- @(\w+).*$", texto, flags=re.M)[1:]
    return {nome: pd.read_sql(sql.strip().rstrip(";"), con) for nome, sql in zip(blocos[::2], blocos[1::2])}


def main():
    if DB.exists():
        DB.unlink()
    with closing(conectar()) as con:
        _executar_script(con, "schema.sql")
        carregar_reais(con)
        carregar_simulados(con)
        con.commit()
        for t in ("bairro", "setor", "refugio", "ilpi", "clima_diario", "saude_diaria", "pessoa_idosa", "cuidador",
                  "sensor"):
            print(f"  {t:14s} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:>6} linhas")
        pd.set_option("display.width", 200)
        pd.set_option("display.max_columns", 20)
        for nome, df in consultas(con).items():
            print(f"\n== {nome} ==\n{df.head(8).to_string(index=False)}")
    print(f"\nBanco salvo em {DB.relative_to(C.RAIZ)}")


if __name__ == "__main__":
    main()

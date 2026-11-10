"""Ferramentas do assistente: funções Python determinísticas que a IA pode chamar.

Cada ferramenta tem um esquema JSON estrito (`strict: true`), então a IA só
consegue chamá-la com argumentos válidos. As respostas são JSON curtos e
**nunca** contêm dados pessoais (nome, telefone) - minimização de dados (LGPD).
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from sklearn.feature_extraction.text import TfidfVectorizer

from src import config as C
from src.ml.recomendacao import DIAS, Perfil, recomendar_refugios

FUSO = ZoneInfo("America/Sao_Paulo")
DB = C.PROCESSED / "refugio.db"
LIMIAR_P90 = 33.3  # percentil 90 da Tmax de verão 1991-2020 (src/data/processar_clima.py)


# ------------------------------------------------------------------ previsão do tempo
def previsao_tempo(lat: float, lon: float, dias: int = 3) -> dict:
    """Previsão diária (Open-Meteo, gratuita e sem chave) de máxima e sensação térmica."""
    r = requests.get("https://api.open-meteo.com/v1/forecast", timeout=20, params={
        "latitude": lat, "longitude": lon, "forecast_days": max(1, min(dias, 7)),
        "daily": "temperature_2m_max,apparent_temperature_max,temperature_2m_min",
        "timezone": "America/Sao_Paulo"})
    r.raise_for_status()
    d = r.json()["daily"]
    out = [{"data": t, "tmax": tx, "sensacao_max": sx, "tmin": tn}
           for t, tx, sx, tn in zip(d["time"], d["temperature_2m_max"], d["apparent_temperature_max"],
                                    d["temperature_2m_min"])]
    seguidos = 0
    for dia in out:
        seguidos = seguidos + 1 if dia["tmax"] >= LIMIAR_P90 else 0
        dia["onda_de_calor"] = seguidos >= 3
    return {"fonte": "Open-Meteo", "dias": out}


# ------------------------------------------------------------------ risco do local
def _con():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def setor_mais_proximo(lat: float, lon: float) -> dict:
    with _con() as con:
        linhas = con.execute("SELECT s.*, b.nome AS bairro FROM setor s JOIN bairro b USING(id_bairro)").fetchall()
    melhor = min(linhas, key=lambda r: (r["lat"] - lat) ** 2 + (r["lon"] - lon) ** 2)
    return dict(melhor)


def risco_do_local(lat: float | None = None, lon: float | None = None, bairro: str | None = None) -> dict:
    """Risco ao calor do setor (por coordenada) ou do bairro (por nome), com base no índice do projeto."""
    with _con() as con:
        if bairro:
            r = con.execute("SELECT * FROM vw_risco_bairro WHERE lower(bairro) = lower(?)", (bairro.strip(),)).fetchone()
            if not r:
                nomes = [x[0] for x in con.execute("SELECT nome FROM bairro ORDER BY nome")]
                return {"erro": "bairro não encontrado", "bairros_validos": nomes}
            return {"bairro": r["bairro"], "risco_medio_0_100": r["risco_medio"], "idosos": r["idosos"],
                    "temperatura_superficie_verao_C": r["lst_media"], "vegetacao_ndvi": r["ndvi_medio"]}
    s = setor_mais_proximo(lat, lon)
    return {"bairro": s["bairro"], "setor": s["cd_setor"], "indice_risco_0_100": round(s["indice_risco"] or 0, 1),
            "prioridade": s["prioridade"], "perfil": s["perfil_cluster"],
            "temperatura_superficie_verao_C": round(s["lst_media"], 1), "vegetacao_ndvi": round(s["ndvi_media"], 2)}


# ------------------------------------------------------------------ refúgio
def recomendar_refugio(lat: float, lon: float, mobilidade_m: int = 800, necessidade: str = "climatizado",
                       dia_semana: int | None = None, hora: int | None = None) -> dict:
    agora = datetime.now(FUSO)
    p = Perfil(lat, lon, agora.weekday() if dia_semana is None else dia_semana,
               agora.hour if hora is None else hora, int(mobilidade_m), necessidade)
    rec = recomendar_refugios(p, top_n=3)
    if rec.empty:
        return {"refugios": [], "aviso": f"Nenhum refúgio aberto ao alcance ({DIAS[p.dia_semana]}, {p.hora}h). "
                                          "Oriente a pessoa a ficar no cômodo mais fresco da casa."}
    return {"quando": f"{DIAS[p.dia_semana]}, {p.hora}h", "refugios": [
        {"nome": r.nome, "tipo": r.categoria, "climatizado": bool(r.climatizado),
         "distancia_km": round(r.distancia_m / 1000, 1), "aberto_ate": f"{int(r.fecha)}h"}
        for r in rec.itertuples()]}


# ------------------------------------------------------------------ orientações oficiais (RAG)
@lru_cache(maxsize=1)
def _base():
    texto = (Path(__file__).parent / "base_conhecimento.md").read_text(encoding="utf-8")
    secoes = {m.group(1): " ".join(m.group(2).split())
              for m in re.finditer(r"^## (\w+)\n(.*?)(?=^## |\Z)", texto, re.S | re.M)}
    # n-gramas de caracteres: "tonta" encontra "tontura", "confusa" encontra "confusão"
    vet = TfidfVectorizer(strip_accents="unicode", lowercase=True, analyzer="char_wb", ngram_range=(3, 5))
    matriz = vet.fit_transform([f"{k.replace('_', ' ')} {v}" for k, v in secoes.items()])
    return list(secoes.items()), vet, matriz


def consultar_orientacoes(pergunta: str, k: int = 2) -> dict:
    secoes, vet, matriz = _base()
    sims = (matriz @ vet.transform([pergunta]).T).toarray().ravel()
    idx = sims.argsort()[::-1][:k]
    return {"fonte": "Ministério da Saúde (resumo do grupo, ver base_conhecimento.md)",
            "trechos": [{"tema": secoes[i][0], "texto": secoes[i][1]} for i in idx if sims[i] > 0]}


# ------------------------------------------------------------------ esquemas para a API
FERRAMENTAS = [
    {"name": "previsao_tempo", "strict": True,
     "description": "Previsão do tempo diária (máxima, mínima e sensação térmica) para uma coordenada, com marcação "
                    "de onda de calor. Use para saber se os próximos dias serão perigosos.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["lat", "lon", "dias"],
                      "properties": {"lat": {"type": "number"}, "lon": {"type": "number"},
                                     "dias": {"type": "integer", "description": "1 a 7"}}}},
    {"name": "risco_do_local", "strict": True,
     "description": "Risco ao calor para idosos de um bairro de Santa Maria/RS (índice 0-100, temperatura de "
                    "superfície e vegetação). Informe o nome do bairro.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["bairro"],
                      "properties": {"bairro": {"type": "string"}}}},
    {"name": "recomendar_refugio", "strict": True,
     "description": "Recomenda até 3 refúgios climáticos ABERTOS no dia/hora, perto da coordenada, conforme a "
                    "mobilidade (metros que a pessoa anda) e a necessidade.",
     "input_schema": {"type": "object", "additionalProperties": False,
                      "required": ["lat", "lon", "mobilidade_m", "necessidade", "dia_semana", "hora"],
                      "properties": {"lat": {"type": "number"}, "lon": {"type": "number"},
                                     "mobilidade_m": {"type": "integer"},
                                     "necessidade": {"type": "string", "enum": ["climatizado", "sombra", "atendimento"]},
                                     "dia_semana": {"type": "integer", "description": "0=segunda ... 6=domingo"},
                                     "hora": {"type": "integer", "description": "0 a 23"}}}},
    {"name": "consultar_orientacoes", "strict": True,
     "description": "Busca orientações OFICIAIS de saúde sobre calor (hidratação, sinais de alerta, emergência, "
                    "ambiente, remédios, refúgio, cuidadores). Use sempre antes de dar qualquer orientação de saúde.",
     "input_schema": {"type": "object", "additionalProperties": False, "required": ["pergunta"],
                      "properties": {"pergunta": {"type": "string"}}}},
]

_FUNCOES = {"previsao_tempo": previsao_tempo, "risco_do_local": risco_do_local,
            "recomendar_refugio": recomendar_refugio, "consultar_orientacoes": consultar_orientacoes}


def executar(nome: str, args: dict) -> str:
    """Executa uma ferramenta pela lista de permissão (allowlist) e devolve JSON."""
    if nome not in _FUNCOES:
        raise ValueError(f"ferramenta não permitida: {nome}")
    return json.dumps(_FUNCOES[nome](**args), ensure_ascii=False, default=str)

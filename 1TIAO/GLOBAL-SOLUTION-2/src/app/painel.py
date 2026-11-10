"""Painel do Refúgio (Streamlit).

Rodar a partir da pasta GLOBAL-SOLUTION-2:
    streamlit run src/app/painel.py
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

import folium  # noqa: E402
import pandas as pd  # noqa: E402
import plotly.express as px  # noqa: E402
import streamlit as st  # noqa: E402
from streamlit_folium import st_folium  # noqa: E402

from src import config as C  # noqa: E402
from src.agente import llm  # noqa: E402
from src.agente.alerta import gerar_alerta  # noqa: E402
from src.agente.assistente import responder  # noqa: E402
from src.agente.ferramentas import FUSO  # noqa: E402
from src.ml.recomendacao import DIAS, Perfil, recomendar_refugios  # noqa: E402

DB = C.PROCESSED / "refugio.db"
CORES_PRIORIDADE = {"Baixa": "#fde7da", "Média": "#f6a57f", "Alta": "#eb6834", "Muito alta": "#6e2709"}

st.set_page_config(page_title="Refúgio – calor e idosos em Santa Maria", page_icon="🌳", layout="wide")


# ----------------------------------------------------------------------------- dados
@st.cache_data
def carregar():
    setores = json.loads((C.PROCESSED / "setores_santa_maria.geojson").read_text(encoding="utf-8"))
    tab = pd.read_csv(C.PROCESSED / "setores_santa_maria.csv", dtype={"CD_SETOR": str})
    clima = pd.read_csv(C.PROCESSED / "clima_diario.csv", parse_dates=["data"])
    saude = pd.read_csv(C.PROCESSED / "resultado_calor_saude.csv")
    refugios = json.loads((C.PROCESSED / "refugios.geojson").read_text(encoding="utf-8"))
    metr = {n: json.loads((C.MODELOS / f"metricas_{n}.json").read_text(encoding="utf-8"))
            for n in ("cnn", "clusters", "recomendacao")}
    return setores, tab, clima, saude, refugios, metr


def consulta(sql: str, params=()) -> pd.DataFrame:
    with sqlite3.connect(DB) as con:
        return pd.read_sql(sql, con, params=params)


setores_geo, tab, clima, saude, refugios_geo, metr = carregar()
bairros = sorted(tab["bairro"].dropna().unique())
pontos = consulta("SELECT b.nome AS bairro, AVG(s.lat) lat, AVG(s.lon) lon FROM setor s JOIN bairro b USING(id_bairro) "
                  "GROUP BY b.nome").set_index("bairro")

# ----------------------------------------------------------------------------- cabeçalho
st.title("🌳 Refúgio")
st.caption("IA contra o calor extremo para os idosos de Santa Maria/RS · Global Solution FIAP 2026.2 · "
           "dados públicos reais (IBGE, Landsat, Sentinel-2, DATASUS, estação 83936). Pessoas, sensores e "
           "alertas exibidos são **simulados**.")

c1, c2, c3, c4, c5 = st.columns(5)
idosos = int(tab["idosos_60_mais"].sum())
alta = int(tab.loc[tab["prioridade"].isin(["Alta", "Muito alta"]), "idosos_60_mais"].sum())
anual = (clima[clima.data.dt.year <= 2025].tmax_era5_corrigido >= 35).groupby(clima.data.dt.year).sum()
rr = saude.loc[saude.desfecho == "obitos_idosos"].iloc[0]
c1.metric("Idosos (60+) na área urbana", f"{idosos:,}".replace(",", "."))
c2.metric("Em setores de prioridade alta", f"{alta:,}".replace(",", "."), f"{100 * alta / idosos:.0f}% do total",
          delta_color="off")
c3.metric("Dias ≥ 35 °C por ano", f"{anual.loc[2016:2025].mean():.1f}".replace(".", ","),
          f"+{anual.loc[2016:2025].mean() - anual.loc[1991:2000].mean():.1f} vs 1991–2000".replace(".", ","),
          delta_color="inverse")
c4.metric("Óbitos de idosos em dias ≥ 35 °C", f"+{(rr.rr - 1) * 100:.0f}%",
          f"IC95% {(rr.ic_inf - 1) * 100:+.0f}% a {(rr.ic_sup - 1) * 100:+.0f}%", delta_color="off")
dom = metr["recomendacao"]["refugios"]["domingo_14h"]["idosos_com_refugio_climatizado_aberto_ate_800m_%"]
c5.metric("Refúgio aberto a ≤ 800 m (domingo)", f"{dom:.0f}%", "contra 89% em dia útil", delta_color="off")

aba_mapa, aba_ref, aba_alerta, aba_chat, aba_iot, aba_dados = st.tabs(
    ["🗺️ Mapa de risco", "🏛️ Onde se refrescar", "📣 Alertas", "💬 Assistente", "📡 Sensores", "📊 Dados e modelos"])

# ----------------------------------------------------------------------------- mapa
with aba_mapa:
    camada = st.radio("Mostrar", ["Prioridade (índice de risco)", "Temperatura de superfície no verão",
                                  "Vegetação (NDVI)", "% de idosos"], horizontal=True)
    col_mapa, col_lado = st.columns([3, 1])
    with col_mapa:
        m = folium.Map(location=[C.CENTRO_LAT, C.CENTRO_LON], zoom_start=12, tiles="OpenStreetMap")
        if camada.startswith("Prioridade"):
            folium.GeoJson(setores_geo, style_function=lambda f: {
                "fillColor": CORES_PRIORIDADE.get(f["properties"].get("prioridade"), "#ccc"), "color": "#fff",
                "weight": 0.3, "fillOpacity": 0.8},
                tooltip=folium.GeoJsonTooltip(["bairro", "prioridade", "indice_risco", "idosos_60_mais", "lst_media"],
                                              aliases=["Bairro", "Prioridade", "Índice de risco", "Idosos 60+",
                                                       "Temp. superfície (°C)"], localize=True)).add_to(m)
        else:
            col = {"Temperatura de superfície no verão": ("lst_media", "OrRd"), "Vegetação (NDVI)": ("ndvi_media", "Greens"),
                   "% de idosos": ("pct_idosos", "Blues")}[camada]
            folium.Choropleth(setores_geo, data=tab, columns=["CD_SETOR", col[0]], key_on="feature.properties.CD_SETOR",
                              fill_color=col[1], line_weight=0.2, fill_opacity=0.8, legend_name=camada).add_to(m)
        for f in refugios_geo["features"]:
            p = f["properties"]
            if p["climatizado"]:
                lon, lat = f["geometry"]["coordinates"]
                folium.CircleMarker([lat, lon], radius=3, color="#0b0b0b", fill=True,
                                    tooltip=f"{p['nome']} ({p['categoria']})").add_to(m)
        st_folium(m, height=520, use_container_width=True, returned_objects=[])
    with col_lado:
        st.subheader("Bairros de maior risco")
        top = (consulta("SELECT bairro, idosos, risco_medio, lst_media FROM vw_risco_bairro ORDER BY risco_medio DESC LIMIT 10")
               .rename(columns={"bairro": "Bairro", "idosos": "Idosos", "risco_medio": "Risco", "lst_media": "°C sup."}))
        st.dataframe(top, hide_index=True, use_container_width=True)
        st.caption("Risco = perigo × exposição × vulnerabilidade (referencial do IPCC), de 0 a 100. "
                   "Pontos pretos: refúgios climatizados.")

# ----------------------------------------------------------------------------- refúgio
with aba_ref:
    st.subheader("Recomendação de refúgio climático")
    a, b, c, d, e = st.columns(5)
    bairro = a.selectbox("Bairro", bairros, index=bairros.index("Tancredo Neves") if "Tancredo Neves" in bairros else 0)
    agora = datetime.now(FUSO)
    dia = b.selectbox("Dia", list(range(7)), index=agora.weekday(), format_func=lambda i: DIAS[i])
    hora = c.slider("Hora", 6, 21, 14)
    mob = d.select_slider("Consegue andar", [300, 500, 800, 1500, 3000], 800, format_func=lambda v: f"{v} m")
    nec = e.selectbox("Precisa de", ["climatizado", "sombra", "atendimento"],
                      format_func={"climatizado": "ar-condicionado", "sombra": "sombra ao ar livre",
                                   "atendimento": "atendimento de saúde"}.get)
    lat, lon = pontos.loc[bairro, ["lat", "lon"]]
    rec = recomendar_refugios(Perfil(lat, lon, dia, hora, mob, nec), top_n=3)
    if rec.empty:
        st.warning("Nenhum refúgio adequado aberto ao alcance neste dia e horário. Oriente a pessoa a ficar no "
                   "cômodo mais fresco da casa, e a Prefeitura pode considerar abrir um ponto nesta região.")
    else:
        for i, r in enumerate(rec.itertuples(), 1):
            st.markdown(f"**{i}. {r.nome}** · {r.categoria} · {r.distancia_m / 1000:.1f} km · aberto até {int(r.fecha)}h "
                        f"· pontuação {r.pontuacao:.2f} (proximidade {r.s_proximidade:.2f}, adequação {r.s_adequacao:.2f}, "
                        f"frescor {r.s_frescor:.2f})".replace(".", ","))
    st.caption("Pontuação = 0,45 × proximidade + 0,35 × adequação à necessidade + 0,20 × frescor do entorno. "
               "Só entram locais abertos no dia e na hora escolhidos.")

# ----------------------------------------------------------------------------- alertas
with aba_alerta:
    st.subheader("Simulação de alerta para quem cuida")
    st.caption(f"Assistente: {llm.descricao()}. O nível é decidido por regra; a IA só redige a mensagem.")
    pessoas = consulta("""SELECT p.id_pessoa, p.nome, 2026 - p.ano_nascimento AS idade, b.nome AS bairro,
                          s.prioridade, p.mora_sozinha, p.alfabetizada, c.canal_preferido
                          FROM pessoa_idosa p JOIN setor s USING(cd_setor) JOIN bairro b USING(id_bairro)
                          JOIN pessoa_cuidador pc ON pc.id_pessoa = p.id_pessoa
                          JOIN cuidador c ON c.id_cuidador = pc.id_cuidador
                          ORDER BY s.indice_risco DESC""")
    a, b, c = st.columns([2, 1, 1])
    pid = a.selectbox("Pessoa (cadastro simulado)", pessoas.id_pessoa,
                      format_func=lambda i: "{nome}, {idade} anos – {bairro} ({prioridade})".format(
                          **pessoas.set_index("id_pessoa").loc[i].to_dict()))
    usar_prev = b.toggle("Usar previsão real (Open-Meteo)", value=False)
    tmax = None if usar_prev else b.slider("Máxima simulada (°C)", 28.0, 41.0, 36.0, 0.5)
    sos = c.toggle("Botão PEDIR AJUDA (ESP32)")
    if st.button("Gerar alerta", type="primary"):
        r = gerar_alerta(int(pid), sos=sos, tmax_simulada=tmax)
        if r["nivel"] is None:
            st.success(r["mensagem"])
        else:
            cor = {"atencao": "warning", "alerta": "warning", "emergencia": "error"}[r["nivel"]]
            getattr(st, cor)(f"Nível: **{r['nivel'].upper()}** · máxima {r['tmax_prevista']} °C · canal: "
                             f"{r['canal']} · origem: {r['gerado_por']} · envio SNS: {r['status_envio']}")
            col1, col2 = st.columns(2)
            col1.markdown("**Mensagem (WhatsApp/SMS)**")
            col1.info(r["mensagem"])
            col2.markdown("**Roteiro da ligação de voz** (para quem não lê)")
            col2.info(r["roteiro_voz"])
    st.markdown("**Últimos alertas registrados**")
    st.dataframe(consulta("""SELECT a.data_hora, p.nome, a.nivel, a.tmax_prevista, a.canal, a.gerado_por, a.status_envio
                             FROM alerta a JOIN pessoa_idosa p USING(id_pessoa) ORDER BY a.id_alerta DESC LIMIT 10"""),
                 hide_index=True, use_container_width=True)

# ----------------------------------------------------------------------------- assistente
with aba_chat:
    st.subheader("Converse com o assistente")
    st.caption("Exemplos: \"Minha mãe está tonta, o que eu faço?\" · \"Quanta água devo oferecer?\" · "
               "\"Onde posso levar meu pai agora?\". Não substitui atendimento médico: em emergência, ligue 192.")
    bairro_chat = st.selectbox("Seu bairro", bairros, key="bairro_chat",
                               index=bairros.index("Centro") if "Centro" in bairros else 0)
    if "chat" not in st.session_state:
        st.session_state.chat = []
    for papel, texto in st.session_state.chat:
        st.chat_message(papel).write(texto)
    if pergunta := st.chat_input("Digite sua pergunta"):
        st.chat_message("user").write(pergunta)
        la, lo = pontos.loc[bairro_chat, ["lat", "lon"]]
        r = responder(pergunta, lat=float(la), lon=float(lo))
        st.chat_message("assistant").write(r["resposta"])
        if r["alerta_injecao"]:
            st.caption("⚠️ Padrão de manipulação detectado na pergunta: tratado como texto comum.")
        st.session_state.chat += [("user", pergunta), ("assistant", r["resposta"])]

# ----------------------------------------------------------------------------- sensores
with aba_iot:
    st.subheader("Estação comunitária ESP32 (Wokwi – dados simulados)")
    leit = consulta("SELECT id_sensor, data_hora, temperatura_c, umidade_pct, indice_calor_c FROM leitura_sensor "
                    "ORDER BY id_leitura DESC LIMIT 200")
    if leit.empty:
        st.info("Nenhuma leitura ainda. Rode a ponte MQTT: `python -m src.iot.ponte_mqtt --simular 20` "
                "ou inicie o circuito no Wokwi.")
    else:
        leit["data_hora"] = pd.to_datetime(leit["data_hora"])
        ult = leit.iloc[0]
        a, b, c = st.columns(3)
        a.metric("Temperatura", f"{ult.temperatura_c:.1f} °C")
        b.metric("Umidade", f"{ult.umidade_pct:.0f}%")
        c.metric("Sensação térmica", f"{ult.indice_calor_c:.1f} °C")
        fig = px.line(leit.sort_values("data_hora"), x="data_hora", y=["temperatura_c", "indice_calor_c"],
                      labels={"value": "°C", "data_hora": "", "variable": ""},
                      color_discrete_sequence=["#2a78d6", "#eb6834"])
        fig.add_hline(y=41, line_dash="dot", annotation_text="perigo (41 °C)")
        fig.add_hline(y=32, line_dash="dot", annotation_text="alerta (32 °C)")
        st.plotly_chart(fig, use_container_width=True)
    st.caption("Mensagens via MQTT/TLS com assinatura HMAC-SHA256 e proteção anti-replay; leituras gravadas no "
               "SQLite e no Amazon DynamoDB.")

# ----------------------------------------------------------------------------- dados e modelos
with aba_dados:
    a, b = st.columns(2)
    with a:
        st.markdown("**Dias com máxima ≥ 35 °C por ano**")
        st.plotly_chart(px.bar(anual.rename("dias").reset_index().rename(columns={"data": "ano"}), x="ano", y="dias",
                               color_discrete_sequence=["#2a78d6"]), use_container_width=True)
    with b:
        st.markdown("**Calor e saúde dos idosos (razão observado/esperado)**")
        fig = px.scatter(saude, x="rr", y="rotulo", error_x=saude.ic_sup - saude.rr,
                         error_x_minus=saude.rr - saude.ic_inf, color_discrete_sequence=["#2a78d6"],
                         labels={"rr": "razão (1 = sem efeito)", "rotulo": ""})
        fig.add_vline(x=1, line_dash="dot")
        st.plotly_chart(fig, use_container_width=True)
    cnn = metr["cnn"]
    st.markdown("**Visão computacional (EuroSAT, conjunto de teste)**")
    st.dataframe(pd.DataFrame([{"modelo": k, "acurácia": cnn[k]["acuracia_teste"], "F1-macro": cnn[k]["f1_macro_teste"]}
                               for k in ("baseline_rf_histograma", "cnn_pequena", "resnet18_transfer")]),
                 hide_index=True)
    st.image(str(C.DOCS_IMG / "cnn_santa_maria.png"), caption="CNN aplicada à imagem Sentinel-2 de Santa Maria")

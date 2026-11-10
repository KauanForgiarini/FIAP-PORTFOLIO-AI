"""Séries diárias de óbitos (SIM) e internações (SIH) de idosos - Santa Maria e RS.

Entrada : data/raw/datasus/sim/DORS*.dbc e data/raw/datasus/sih/RDRS*.dbc
Saída   : data/processed/saude_diaria.csv  (uma linha por dia e recorte geográfico)

Somente contagens agregadas por dia são salvas: nenhum dado individual sai de
data/raw/ (cuidado de privacidade - LGPD).

Grupos de causa (CID-10) considerados sensíveis ao calor, conforme a literatura
de saúde ambiental: doenças do aparelho circulatório (I00-I99), respiratório
(J00-J99), insuficiência renal (N17-N19), desidratação/hipovolemia (E86) e
efeitos diretos do calor (T67, X30).

Uso: python -m src.data.processar_saude
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pandas as pd

from src import config as C
from src.data.leitor_dbc import ler_dbc

COLS_SIM = ["DTOBITO", "IDADE", "CODMUNRES", "CAUSABAS"]
COLS_SIH = ["DT_INTER", "IDADE", "COD_IDADE", "MUNIC_RES", "DIAG_PRINC", "IDENT"]


def _grupo_cid(cid: pd.Series) -> pd.DataFrame:
    cid = cid.fillna("").str.upper()
    letra, num = cid.str[0], pd.to_numeric(cid.str[1:3], errors="coerce")
    circ = letra.eq("I")
    resp = letra.eq("J")
    renal = letra.eq("N") & num.between(17, 19)
    calor = cid.str.startswith(("T67", "X30", "E86"))
    return pd.DataFrame({"circulatorio": circ, "respiratorio": resp,
                         "sensivel_calor": circ | resp | renal | calor})


def _idade_sim(idade: pd.Series) -> pd.Series:
    unidade = idade.str[0]
    valor = pd.to_numeric(idade.str[1:], errors="coerce")
    return valor.where(unidade.eq("4"), (100 + valor).where(unidade.eq("5"), 0))


def _resumir(df: pd.DataFrame, col_data: str, fmt: str, col_mun: str, fonte: str) -> pd.DataFrame:
    df = df.assign(data=pd.to_datetime(df[col_data], format=fmt, errors="coerce")).dropna(subset=["data"])
    grupos = _grupo_cid(df["cid"])
    df = pd.concat([df[["data", "idade", col_mun]], grupos], axis=1)
    df["idoso"] = df["idade"] >= 60
    saidas = []
    for recorte, filtro in (("santa_maria", df[col_mun].eq(C.COD_IBGE_6)), ("rs", pd.Series(True, index=df.index))):
        d = df[filtro]
        agg = pd.DataFrame({
            f"{fonte}_total": d.groupby("data").size(),
            f"{fonte}_idosos": d[d.idoso].groupby("data").size(),
            f"{fonte}_idosos_sensivel_calor": d[d.idoso & d.sensivel_calor].groupby("data").size(),
            f"{fonte}_idosos_circulatorio": d[d.idoso & d.circulatorio].groupby("data").size(),
            f"{fonte}_idosos_respiratorio": d[d.idoso & d.respiratorio].groupby("data").size(),
        }).fillna(0).astype(int)
        agg["recorte"] = recorte
        saidas.append(agg.reset_index())
    return pd.concat(saidas)


def processar_sim(caminho: Path) -> pd.DataFrame:
    df = ler_dbc(caminho, COLS_SIM)
    df = df.assign(idade=_idade_sim(df["IDADE"]), cid=df["CAUSABAS"])
    return _resumir(df, "DTOBITO", "%d%m%Y", "CODMUNRES", "obitos")


def processar_sih(caminho: Path) -> pd.DataFrame:
    df = ler_dbc(caminho, COLS_SIH)
    df = df[df["IDENT"].eq("1")]  # 1 = AIH normal (exclui continuação de longa permanência)
    idade = pd.to_numeric(df["IDADE"], errors="coerce")
    df = df.assign(idade=idade.where(df["COD_IDADE"].eq("4"), 0), cid=df["DIAG_PRINC"])
    return _resumir(df, "DT_INTER", "%Y%m%d", "MUNIC_RES", "internacoes")


def main() -> None:
    sim = sorted((C.RAW / "datasus" / "sim").glob("DORS*.dbc"))
    sih = sorted((C.RAW / "datasus" / "sih").glob("RDRS*.dbc"))
    print(f"{len(sim)} arquivos SIM, {len(sih)} arquivos SIH")
    with ProcessPoolExecutor(max_workers=max(1, (os.cpu_count() or 2) - 1)) as ex:
        r_sim = list(ex.map(processar_sim, sim))
        print("SIM ok")
        r_sih = list(ex.map(processar_sih, sih))
        print("SIH ok")
    chave = ["data", "recorte"]
    obitos = pd.concat(r_sim).groupby(chave).sum()
    intern = pd.concat(r_sih).groupby(chave).sum()  # internação de um mês pode aparecer em arquivos seguintes
    saude = obitos.join(intern, how="outer").fillna(0).astype(int).reset_index().sort_values(chave)
    destino = C.PROCESSED / "saude_diaria.csv"
    saude.to_csv(destino, index=False)
    print(f"salvo {destino.relative_to(C.RAIZ)}: {len(saude)} linhas")
    sm = saude[saude.recorte.eq("santa_maria")]
    print(sm.groupby(sm.data.dt.year)[["obitos_idosos", "internacoes_idosos"]].sum())


if __name__ == "__main__":
    main()

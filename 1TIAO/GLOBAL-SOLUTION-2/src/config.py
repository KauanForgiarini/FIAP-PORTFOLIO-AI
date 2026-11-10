"""Configurações centrais do projeto (caminhos, área de estudo e fontes de dados).

Todos os scripts importam daqui para que exista um único lugar com os
parâmetros da cidade estudada. Para adaptar a solução a outra cidade, basta
alterar o bloco "Área de estudo".
"""
import sys
from pathlib import Path

# Garante acentos e símbolos no terminal do Windows (que usa cp1252 por padrão)
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass

# --------------------------------------------------------------------------
# Caminhos
# --------------------------------------------------------------------------
RAIZ = Path(__file__).resolve().parents[1]
DATA = RAIZ / "data"
RAW = DATA / "raw"            # dados brutos baixados (não versionados no git)
PROCESSED = DATA / "processed"  # dados tratados, pequenos, versionados
DOCS_IMG = RAIZ / "docs" / "img"
MODELOS = RAIZ / "src" / "ml" / "modelos"

for _p in (RAW, PROCESSED, DOCS_IMG, MODELOS):
    _p.mkdir(parents=True, exist_ok=True)

# --------------------------------------------------------------------------
# Área de estudo: Santa Maria / RS
# --------------------------------------------------------------------------
MUNICIPIO = "Santa Maria"
UF = "RS"
COD_IBGE_7 = "4316907"      # código IBGE de 7 dígitos (Censo, malhas)
COD_IBGE_6 = "431690"       # código de 6 dígitos usado pelo DATASUS
CENTRO_LAT, CENTRO_LON = -29.6868, -53.8149
# Retângulo que envolve os 406 setores urbanos do distrito-sede no Censo 2022
# (limites -53.892, -29.750, -53.668, -29.622) com ~500 m de margem.
# (lon_min, lat_min, lon_max, lat_max)
BBOX_URBANA = (-53.897, -29.755, -53.663, -29.617)
CRS_METRICO = "EPSG:31982"  # SIRGAS 2000 / UTM zona 22S (metros)

# Estação meteorológica de Santa Maria (OMM 83936 / INMET A803)
ESTACAO_OMM = "83936"

# --------------------------------------------------------------------------
# Limiares de calor (referências usadas no projeto)
# --------------------------------------------------------------------------
# Dia de calor extremo: Tmax >= 35 °C (limiar absoluto, comum em alertas)
# ou Tmax acima do percentil 90 dos verões da série histórica (limiar relativo).
LIMIAR_TMAX_ABSOLUTO = 35.0
PERCENTIL_ONDA_CALOR = 90
DIAS_MIN_ONDA_CALOR = 3  # dias consecutivos para caracterizar onda de calor

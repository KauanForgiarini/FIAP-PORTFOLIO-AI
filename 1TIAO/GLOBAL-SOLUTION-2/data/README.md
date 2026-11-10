# Dados do projeto

Todos os dados brutos são **públicos e reais** e são baixados automaticamente por
`python -m src.data.baixar_dados` para `data/raw/`. Essa pasta não vai para o Git
por causa do tamanho (~650 MB). Os arquivos tratados, pequenos, ficam em `data/processed/`.

Dados **simulados** (sensores do ESP32 no Wokwi) são sempre identificados como tal no nome do
arquivo e na interface.

## Fontes

| # | Fonte | O que usamos | Período | Licença / acesso |
|---|-------|--------------|---------|------------------|
| 1 | **Landsat 8 e 9 – Collection 2 Level-2** (USGS/NASA), via catálogo STAC do Microsoft Planetary Computer | Temperatura de superfície (banda térmica ST_B10), vermelho e infravermelho próximo (NDVI), máscara de nuvem (QA_PIXEL) | Verões (dez–mar) de 2022/23, 2023/24 e 2024/25 | Domínio público (USGS) |
| 2 | **Estação meteorológica de Santa Maria** (OMM 83936), via Meteostat | Temperatura máxima, mínima e média diárias, chuva | 02/01/2021 – 07/03/2026 | CC BY-NC 4.0 (Meteostat) |
| 3 | **Reanálise ERA5** (ECMWF/Copernicus), via Open-Meteo | Série diária longa de temperatura, sensação térmica, umidade e chuva | 1991 – 2025 | CC BY 4.0 |
| 4 | **IBGE – Censo Demográfico 2022, agregados por setor censitário** | Malha dos setores com atributos básicos, moradores por faixa etária e alfabetização por faixa etária | 2022 | Dados públicos (IBGE) |
| 5 | **DATASUS – SIM** (Sistema de Informações sobre Mortalidade), RS | Data do óbito, idade, município de residência e causa básica (CID-10) | 2020 – 2024 | Dados públicos (Ministério da Saúde) |
| 6 | **DATASUS – SIH/SUS** (Sistema de Informações Hospitalares), RS | Data da internação, idade, município de residência e diagnóstico principal | 2021 – 2025 | Dados públicos (Ministério da Saúde) |
| 7 | **EuroSAT RGB** (Helber et al., 2019), via Zenodo | 27.000 recortes Sentinel-2 rotulados em 10 classes de uso do solo, usados para treinar a CNN | – | MIT |
| 8 | **OpenStreetMap** (Overpass API) | Árvores, parques, unidades de saúde e equipamentos públicos (candidatos a refúgio climático) | Atual | ODbL |

## Tratamentos realizados

- **Satélite** (`src/data/processar_landsat.py`): seleção de cenas com menos de 10% de nuvens,
  remoção de pixels de nuvem/sombra, conversão do número digital para °C e refletância, e
  **mediana** de todas as cenas válidas para reduzir ruído.
- **Censo** (`src/data/processar_censo.py`): recorte dos 406 setores urbanos do distrito-sede,
  cálculo de % de idosos (60+ e 70+), densidade e % de idosos não alfabetizados. Também cruza
  cada setor com a temperatura de superfície e o NDVI médios (estatística zonal).
- **Saúde** (`src/data/processar_saude.py`): leitura dos arquivos `.dbc` com um descompressor em
  Python puro (`src/data/leitor_dbc.py`) e contagem **diária e agregada** de óbitos e internações
  de pessoas com 60 anos ou mais. Nenhum registro individual sai de `data/raw/` (LGPD).
- **Clima** (`src/data/processar_clima.py`): união da estação com o ERA5, correção do viés da
  reanálise (+0,34 °C na Tmax; correlação de 0,983 com a estação) e marcação de dias ≥ 35 °C e de
  ondas de calor (≥ 3 dias acima do percentil 90 dos verões de 1991–2020, que é 33,3 °C).

## Qualidade e limitações

- **Temperatura de superfície ≠ temperatura do ar.** O Landsat mede a temperatura do telhado, do
  asfalto ou da copa das árvores às ~10h30 da manhã (horário da passagem do satélite). Ela indica
  onde a cidade acumula calor, mas não é a temperatura que a pessoa sente.
- **A máxima diária do Meteostat pode subestimar picos.** Ela vem dos boletins sinóticos da
  estação convencional. Por exemplo, a imprensa noticiou 40,2 °C pelo INMET em 16/01/2022, e a
  série registra 38,6 °C. O portal do INMET bloqueia download automatizado; os dados da estação
  automática A803 podem ser baixados manualmente e substituídos aqui.
- **O ERA5 tem resolução de ~25 km** e suaviza extremos locais. Por isso é usado só para a série
  longa e para preencher lacunas, depois de corrigido pelo viés.
- **Censo:** setores muito pequenos têm valores sigilosos ("X" no IBGE), tratados como ausentes
  (15 de 406 setores na variável de idosos).
- **DATASUS:** os dados de 2024 (SIM) e 2025 (SIH) ainda podem ser revisados pelo Ministério da
  Saúde. Internações de dezembro de 2020 aparecem parcialmente e não são usadas na análise.
- **OpenStreetMap:** o mapeamento colaborativo é incompleto em cidades médias, então a contagem de
  árvores do OSM não representa a arborização real. Para vegetação usamos o NDVI do satélite.

# Arquitetura do Refúgio

## Visão geral

```mermaid
flowchart LR
    subgraph Fontes["Dados públicos reais"]
        L[Landsat 8/9<br/>temperatura de superfície]
        S2[Sentinel-2<br/>imagem RGB]
        IBGE[IBGE Censo 2022<br/>idosos por setor]
        CL[Estação 83936 + ERA5<br/>clima 1991-2026]
        SUS[DATASUS SIM/SIH<br/>óbitos e internações]
        OSM[OpenStreetMap<br/>refúgios e ILPIs]
    end

    subgraph Analise["Análise e IA (Python)"]
        EDA[EDA e calor x saúde]
        CNN[CNN uso do solo<br/>EuroSAT -> Santa Maria]
        RISCO[Índice de risco +<br/>K-Means]
        REC[Recomendação<br/>refúgio e plantio]
    end

    subgraph Campo["Sensores (Wokwi - simulado)"]
        ESP[ESP32 + DHT22<br/>LCD, LEDs, botão de ajuda]
    end

    subgraph Nuvem["Nuvem / serviços"]
        MQTT[(Broker MQTT TLS<br/>HiveMQ / AWS IoT Core)]
        DDB[(DynamoDB<br/>leituras - NoSQL)]
        LLM[Agente de IA generativa]
        PREV[Open-Meteo<br/>previsão]
    end

    DB[(SQLite / Oracle<br/>modelo relacional)]
    APP[Painel Streamlit]
    CUID[Cuidador / familiar /<br/>agente de saúde]

    L & IBGE & CL & SUS & OSM --> EDA
    S2 --> CNN --> RISCO
    L & IBGE & OSM --> RISCO --> REC
    EDA & RISCO & REC --> DB
    ESP -- "MQTT/TLS + HMAC" --> MQTT --> PONTE[Ponte MQTT<br/>validação] --> DB
    PONTE --> DDB
    PREV --> LLM
    DB --> LLM
    REC --> LLM
    LLM -- "alerta em linguagem simples" --> CUID
    DB --> APP
    LLM --> APP
```

## Modelo de dados (DER)

```mermaid
erDiagram
    BAIRRO ||--o{ SETOR : contem
    SETOR ||--o{ REFUGIO : localiza
    SETOR ||--o{ ILPI : localiza
    SETOR ||--o{ PESSOA_IDOSA : "mora em"
    SETOR ||--o{ SENSOR : "instalado em"
    PESSOA_IDOSA ||--o{ PESSOA_CUIDADOR : tem
    CUIDADOR ||--o{ PESSOA_CUIDADOR : cuida
    SENSOR ||--o{ LEITURA_SENSOR : gera
    PESSOA_IDOSA ||--o{ ALERTA : recebe
    CUIDADOR ||--o{ ALERTA : "é avisado"
    REFUGIO ||--o{ ALERTA : "é recomendado"

    BAIRRO { int id_bairro PK
             text nome }
    SETOR { text cd_setor PK
            int id_bairro FK
            int idosos_60_mais
            real lst_media
            real ndvi_media
            real frac_construida_cnn
            real indice_risco
            text prioridade
            int cluster }
    REFUGIO { int id_refugio PK
              text nome
              text categoria
              int climatizado
              text dias_abertos }
    PESSOA_IDOSA { int id_pessoa PK
                   text cd_setor FK
                   int alfabetizada
                   int mobilidade_m
                   text necessidade
                   int consentimento_lgpd }
    CUIDADOR { int id_cuidador PK
               text relacao
               text canal_preferido
               text telefone_mascarado }
    ALERTA { int id_alerta PK
             int id_pessoa FK
             text nivel
             int id_refugio FK
             text mensagem
             text gerado_por }
    SENSOR { text id_sensor PK
             text cd_setor FK }
    LEITURA_SENSOR { int id_leitura PK
                     text id_sensor FK
                     real temperatura_c
                     real indice_calor_c }
```

Tabelas independentes: `CLIMA_DIARIO` (série diária) e `SAUDE_DIARIA` (contagens agregadas de
óbitos e internações, sem dados individuais).

## Decisões de projeto

| Decisão | Motivo |
|---|---|
| **SQLite** local + **script Oracle** equivalente | Roda em qualquer máquina sem servidor. O script Oracle (`src/db/schema_oracle.sql`) mostra a modelagem no SGBD usado nas aulas |
| **NoSQL (DynamoDB)** para leituras de sensores | Série temporal de alto volume, chave natural `id_sensor` + `seq` e sem joins |
| **Relacional** para o domínio (setores, pessoas, alertas) | Integridade referencial, restrições (`CHECK`) e consultas analíticas com joins |
| Cálculo de risco no **dispositivo** (edge) | O LED e o buzzer avisam quem está perto mesmo sem internet |
| **HMAC + TLS** no MQTT | O broker de demonstração é público: garante autenticidade, integridade e confidencialidade |
| Dados de saúde **só agregados** | LGPD: dados de saúde são sensíveis (art. 11). Nada individual sai de `data/raw/` |
| Cadastro de idosos **simulado** | Não coletamos dados pessoais reais. O cadastro fictício segue a distribuição real do Censo |

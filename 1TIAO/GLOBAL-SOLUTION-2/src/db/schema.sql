-- =============================================================================
-- Refúgio - modelo relacional (SQLite; versão Oracle em schema_oracle.sql)
-- =============================================================================
-- Dados REAIS: bairro, setor, refugio, ilpi, clima_diario, saude_diaria
-- Dados SIMULADOS (identificados pela coluna simulado = 1): pessoa_idosa,
--   cuidador, sensor, leitura_sensor e alerta - nenhum dado pessoal real é usado.
-- Princípios LGPD aplicados: minimização (só o necessário para o alerta),
--   consentimento registrado, telefone mascarado, saúde apenas agregada.
-- =============================================================================
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS bairro (
    id_bairro        INTEGER PRIMARY KEY,
    nome             TEXT    NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS setor (
    cd_setor               TEXT    PRIMARY KEY,          -- código IBGE (15 dígitos)
    id_bairro              INTEGER NOT NULL REFERENCES bairro(id_bairro),
    area_km2               REAL,
    moradores              INTEGER,
    idosos_60_mais         INTEGER,
    pct_idosos             REAL,
    pct_70_mais            REAL,
    pct_idosos_nao_alfab   REAL,
    lst_media              REAL,                          -- temperatura de superfície (°C)
    ndvi_media             REAL,
    frac_construida_cnn    REAL,                          -- saída da CNN (0-1)
    dist_refugio_km        REAL,
    indice_risco           REAL CHECK (indice_risco BETWEEN 0 AND 100),
    prioridade             TEXT CHECK (prioridade IN ('Baixa','Média','Alta','Muito alta')),
    cluster                INTEGER,
    perfil_cluster         TEXT,
    resfriamento_pot_c     REAL,                          -- recomendação de plantio
    rank_plantio           INTEGER,
    lat                    REAL,
    lon                    REAL
);

CREATE TABLE IF NOT EXISTS refugio (
    id_refugio     INTEGER PRIMARY KEY,
    nome           TEXT    NOT NULL,
    categoria      TEXT    NOT NULL CHECK (categoria IN ('saude','assistencia','biblioteca','shopping','parque')),
    climatizado    INTEGER NOT NULL CHECK (climatizado IN (0,1)),
    dias_abertos   TEXT    NOT NULL,                      -- "0,1,2,3,4" (0 = segunda)
    hora_abre      INTEGER NOT NULL CHECK (hora_abre BETWEEN 0 AND 23),
    hora_fecha     INTEGER NOT NULL CHECK (hora_fecha BETWEEN 1 AND 24),
    lat            REAL    NOT NULL,
    lon            REAL    NOT NULL,
    cd_setor       TEXT    REFERENCES setor(cd_setor),
    osm_id         TEXT
);

CREATE TABLE IF NOT EXISTS ilpi (                         -- instituição de longa permanência p/ idosos
    id_ilpi        INTEGER PRIMARY KEY,
    nome           TEXT NOT NULL,
    lat            REAL NOT NULL,
    lon            REAL NOT NULL,
    cd_setor       TEXT REFERENCES setor(cd_setor)
);

CREATE TABLE IF NOT EXISTS clima_diario (
    data           TEXT PRIMARY KEY,                      -- AAAA-MM-DD
    tmax           REAL,
    tmin_estacao   REAL,
    fonte_tmax     TEXT CHECK (fonte_tmax IN ('estacao','era5_corrigido')),
    dia_quente     INTEGER CHECK (dia_quente IN (0,1)),   -- Tmax >= 35 °C
    onda_calor     INTEGER CHECK (onda_calor IN (0,1))
);

CREATE TABLE IF NOT EXISTS saude_diaria (                 -- somente contagens agregadas (LGPD)
    data                      TEXT NOT NULL,
    recorte                   TEXT NOT NULL CHECK (recorte IN ('santa_maria','rs')),
    obitos_idosos             INTEGER,
    obitos_idosos_sens_calor  INTEGER,
    internacoes_idosos        INTEGER,
    intern_idosos_sens_calor  INTEGER,
    PRIMARY KEY (data, recorte)
);

-- ---------------------------------------------------------------- simulados --
CREATE TABLE IF NOT EXISTS pessoa_idosa (
    id_pessoa            INTEGER PRIMARY KEY,
    nome                 TEXT    NOT NULL,
    ano_nascimento       INTEGER NOT NULL CHECK (ano_nascimento BETWEEN 1910 AND 1966),
    cd_setor             TEXT    NOT NULL REFERENCES setor(cd_setor),
    alfabetizada         INTEGER NOT NULL CHECK (alfabetizada IN (0,1)),
    mobilidade_m         INTEGER NOT NULL DEFAULT 800,
    necessidade          TEXT    NOT NULL DEFAULT 'climatizado'
                         CHECK (necessidade IN ('climatizado','sombra','atendimento')),
    mora_sozinha         INTEGER NOT NULL CHECK (mora_sozinha IN (0,1)),
    consentimento_lgpd   INTEGER NOT NULL CHECK (consentimento_lgpd = 1),
    data_consentimento   TEXT    NOT NULL,
    simulado             INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS cuidador (
    id_cuidador          INTEGER PRIMARY KEY,
    nome                 TEXT NOT NULL,
    relacao              TEXT NOT NULL CHECK (relacao IN ('familiar','cuidador','agente_saude','vizinho','ilpi')),
    telefone_mascarado   TEXT NOT NULL,                   -- ex.: (55) 9****-1234
    canal_preferido      TEXT NOT NULL CHECK (canal_preferido IN ('sms','whatsapp','ligacao_voz','email')),
    simulado             INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS pessoa_cuidador (              -- N:N
    id_pessoa     INTEGER NOT NULL REFERENCES pessoa_idosa(id_pessoa) ON DELETE CASCADE,
    id_cuidador   INTEGER NOT NULL REFERENCES cuidador(id_cuidador) ON DELETE CASCADE,
    principal     INTEGER NOT NULL DEFAULT 0 CHECK (principal IN (0,1)),
    PRIMARY KEY (id_pessoa, id_cuidador)
);

CREATE TABLE IF NOT EXISTS sensor (
    id_sensor     TEXT PRIMARY KEY,                       -- ex.: ESP32-SM-01
    descricao     TEXT,
    tipo          TEXT NOT NULL DEFAULT 'wokwi_simulado',
    lat           REAL,
    lon           REAL,
    cd_setor      TEXT REFERENCES setor(cd_setor)
);

CREATE TABLE IF NOT EXISTS leitura_sensor (               -- resumo relacional; série bruta fica no NoSQL
    id_leitura     INTEGER PRIMARY KEY,
    id_sensor      TEXT NOT NULL REFERENCES sensor(id_sensor),
    data_hora      TEXT NOT NULL,
    temperatura_c  REAL CHECK (temperatura_c BETWEEN -20 AND 70),
    umidade_pct    REAL CHECK (umidade_pct BETWEEN 0 AND 100),
    indice_calor_c REAL,
    simulado       INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS alerta (
    id_alerta        INTEGER PRIMARY KEY,
    data_hora        TEXT    NOT NULL,
    id_pessoa        INTEGER NOT NULL REFERENCES pessoa_idosa(id_pessoa),
    id_cuidador      INTEGER REFERENCES cuidador(id_cuidador),
    nivel            TEXT    NOT NULL CHECK (nivel IN ('atencao','alerta','emergencia')),
    tmax_prevista    REAL,
    id_refugio       INTEGER REFERENCES refugio(id_refugio),
    canal            TEXT,
    mensagem         TEXT    NOT NULL,
    gerado_por       TEXT    NOT NULL CHECK (gerado_por IN ('agente_ia','regra_fallback')),
    status_envio     TEXT    NOT NULL DEFAULT 'simulado' CHECK (status_envio IN ('simulado','enviado','falhou')),
    simulado         INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS ix_setor_bairro   ON setor(id_bairro);
CREATE INDEX IF NOT EXISTS ix_setor_risco    ON setor(indice_risco);
CREATE INDEX IF NOT EXISTS ix_pessoa_setor   ON pessoa_idosa(cd_setor);
CREATE INDEX IF NOT EXISTS ix_alerta_data    ON alerta(data_hora);
CREATE INDEX IF NOT EXISTS ix_leitura_sensor ON leitura_sensor(id_sensor, data_hora);

-- Visão usada pelo painel e pelo agente: risco consolidado por bairro
CREATE VIEW IF NOT EXISTS vw_risco_bairro AS
SELECT b.nome                                   AS bairro,
       COUNT(*)                                 AS setores,
       SUM(s.idosos_60_mais)                    AS idosos,
       ROUND(AVG(s.lst_media), 1)               AS lst_media,
       ROUND(AVG(s.ndvi_media), 2)              AS ndvi_medio,
       ROUND(AVG(s.indice_risco), 1)            AS risco_medio,
       SUM(CASE WHEN s.prioridade IN ('Alta','Muito alta') THEN s.idosos_60_mais ELSE 0 END) AS idosos_alta_prioridade
FROM setor s JOIN bairro b ON b.id_bairro = s.id_bairro
GROUP BY b.nome;

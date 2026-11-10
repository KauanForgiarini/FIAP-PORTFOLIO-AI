-- =============================================================================
-- Refúgio - modelo relacional para Oracle Database (equivalente a schema.sql)
-- Executar no SQL Developer / SQL*Plus com o usuário do grupo.
-- Dados simulados identificados pela coluna SIMULADO = 1.
-- =============================================================================

CREATE TABLE t_ref_bairro (
    id_bairro   NUMBER(5)      CONSTRAINT pk_bairro PRIMARY KEY,
    nome        VARCHAR2(80)   NOT NULL CONSTRAINT uq_bairro_nome UNIQUE
);

CREATE TABLE t_ref_setor (
    cd_setor              VARCHAR2(15)  CONSTRAINT pk_setor PRIMARY KEY,
    id_bairro             NUMBER(5)     NOT NULL CONSTRAINT fk_setor_bairro REFERENCES t_ref_bairro(id_bairro),
    area_km2              NUMBER(10,4),
    moradores             NUMBER(6),
    idosos_60_mais        NUMBER(6),
    pct_idosos            NUMBER(5,2),
    pct_70_mais           NUMBER(5,2),
    pct_idosos_nao_alfab  NUMBER(5,2),
    lst_media             NUMBER(5,2),
    ndvi_media            NUMBER(4,3),
    frac_construida_cnn   NUMBER(4,3),
    dist_refugio_km       NUMBER(6,3),
    indice_risco          NUMBER(5,2)   CONSTRAINT ck_setor_risco CHECK (indice_risco BETWEEN 0 AND 100),
    prioridade            VARCHAR2(12)  CONSTRAINT ck_setor_prior CHECK (prioridade IN ('Baixa','Média','Alta','Muito alta')),
    cluster_id            NUMBER(2),
    perfil_cluster        VARCHAR2(120),
    resfriamento_pot_c    NUMBER(5,2),
    rank_plantio          NUMBER(4),
    lat                   NUMBER(9,6),
    lon                   NUMBER(9,6)
);

CREATE TABLE t_ref_refugio (
    id_refugio    NUMBER(6)     CONSTRAINT pk_refugio PRIMARY KEY,
    nome          VARCHAR2(150) NOT NULL,
    categoria     VARCHAR2(12)  NOT NULL CONSTRAINT ck_ref_cat CHECK (categoria IN ('saude','assistencia','biblioteca','shopping','parque')),
    climatizado   NUMBER(1)     NOT NULL CONSTRAINT ck_ref_clim CHECK (climatizado IN (0,1)),
    dias_abertos  VARCHAR2(13)  NOT NULL,
    hora_abre     NUMBER(2)     NOT NULL CONSTRAINT ck_ref_abre CHECK (hora_abre BETWEEN 0 AND 23),
    hora_fecha    NUMBER(2)     NOT NULL CONSTRAINT ck_ref_fecha CHECK (hora_fecha BETWEEN 1 AND 24),
    lat           NUMBER(9,6)   NOT NULL,
    lon           NUMBER(9,6)   NOT NULL,
    cd_setor      VARCHAR2(15)  CONSTRAINT fk_ref_setor REFERENCES t_ref_setor(cd_setor),
    osm_id        VARCHAR2(30)
);

CREATE TABLE t_ref_ilpi (
    id_ilpi    NUMBER(5)     CONSTRAINT pk_ilpi PRIMARY KEY,
    nome       VARCHAR2(150) NOT NULL,
    lat        NUMBER(9,6)   NOT NULL,
    lon        NUMBER(9,6)   NOT NULL,
    cd_setor   VARCHAR2(15)  CONSTRAINT fk_ilpi_setor REFERENCES t_ref_setor(cd_setor)
);

CREATE TABLE t_ref_clima_diario (
    data          DATE         CONSTRAINT pk_clima PRIMARY KEY,
    tmax          NUMBER(4,1),
    tmin_estacao  NUMBER(4,1),
    fonte_tmax    VARCHAR2(15) CONSTRAINT ck_clima_fonte CHECK (fonte_tmax IN ('estacao','era5_corrigido')),
    dia_quente    NUMBER(1)    CONSTRAINT ck_clima_dq CHECK (dia_quente IN (0,1)),
    onda_calor    NUMBER(1)    CONSTRAINT ck_clima_oc CHECK (onda_calor IN (0,1))
);

CREATE TABLE t_ref_saude_diaria (
    data                      DATE         NOT NULL,
    recorte                   VARCHAR2(12) NOT NULL CONSTRAINT ck_saude_rec CHECK (recorte IN ('santa_maria','rs')),
    obitos_idosos             NUMBER(5),
    obitos_idosos_sens_calor  NUMBER(5),
    internacoes_idosos        NUMBER(5),
    intern_idosos_sens_calor  NUMBER(5),
    CONSTRAINT pk_saude PRIMARY KEY (data, recorte)
);

CREATE TABLE t_ref_pessoa_idosa (
    id_pessoa           NUMBER(8)     CONSTRAINT pk_pessoa PRIMARY KEY,
    nome                VARCHAR2(120) NOT NULL,
    ano_nascimento      NUMBER(4)     NOT NULL CONSTRAINT ck_pessoa_ano CHECK (ano_nascimento BETWEEN 1910 AND 1966),
    cd_setor            VARCHAR2(15)  NOT NULL CONSTRAINT fk_pessoa_setor REFERENCES t_ref_setor(cd_setor),
    alfabetizada        NUMBER(1)     NOT NULL CONSTRAINT ck_pessoa_alf CHECK (alfabetizada IN (0,1)),
    mobilidade_m        NUMBER(5)     DEFAULT 800 NOT NULL,
    necessidade         VARCHAR2(12)  DEFAULT 'climatizado' NOT NULL
                        CONSTRAINT ck_pessoa_nec CHECK (necessidade IN ('climatizado','sombra','atendimento')),
    mora_sozinha        NUMBER(1)     NOT NULL CONSTRAINT ck_pessoa_soz CHECK (mora_sozinha IN (0,1)),
    consentimento_lgpd  NUMBER(1)     NOT NULL CONSTRAINT ck_pessoa_lgpd CHECK (consentimento_lgpd = 1),
    data_consentimento  DATE          NOT NULL,
    simulado            NUMBER(1)     DEFAULT 1 NOT NULL
);

CREATE TABLE t_ref_cuidador (
    id_cuidador         NUMBER(8)     CONSTRAINT pk_cuidador PRIMARY KEY,
    nome                VARCHAR2(120) NOT NULL,
    relacao             VARCHAR2(15)  NOT NULL CONSTRAINT ck_cuid_rel CHECK (relacao IN ('familiar','cuidador','agente_saude','vizinho','ilpi')),
    telefone_mascarado  VARCHAR2(20)  NOT NULL,
    canal_preferido     VARCHAR2(12)  NOT NULL CONSTRAINT ck_cuid_canal CHECK (canal_preferido IN ('sms','whatsapp','ligacao_voz','email')),
    simulado            NUMBER(1)     DEFAULT 1 NOT NULL
);

CREATE TABLE t_ref_pessoa_cuidador (
    id_pessoa    NUMBER(8) NOT NULL CONSTRAINT fk_pc_pessoa REFERENCES t_ref_pessoa_idosa(id_pessoa) ON DELETE CASCADE,
    id_cuidador  NUMBER(8) NOT NULL CONSTRAINT fk_pc_cuidador REFERENCES t_ref_cuidador(id_cuidador) ON DELETE CASCADE,
    principal    NUMBER(1) DEFAULT 0 NOT NULL CONSTRAINT ck_pc_principal CHECK (principal IN (0,1)),
    CONSTRAINT pk_pessoa_cuidador PRIMARY KEY (id_pessoa, id_cuidador)
);

CREATE TABLE t_ref_sensor (
    id_sensor   VARCHAR2(20)  CONSTRAINT pk_sensor PRIMARY KEY,
    descricao   VARCHAR2(150),
    tipo        VARCHAR2(20)  DEFAULT 'wokwi_simulado' NOT NULL,
    lat         NUMBER(9,6),
    lon         NUMBER(9,6),
    cd_setor    VARCHAR2(15)  CONSTRAINT fk_sensor_setor REFERENCES t_ref_setor(cd_setor)
);

CREATE TABLE t_ref_leitura_sensor (
    id_leitura      NUMBER(12)   GENERATED ALWAYS AS IDENTITY CONSTRAINT pk_leitura PRIMARY KEY,
    id_sensor       VARCHAR2(20) NOT NULL CONSTRAINT fk_leitura_sensor REFERENCES t_ref_sensor(id_sensor),
    data_hora       TIMESTAMP    NOT NULL,
    temperatura_c   NUMBER(4,1)  CONSTRAINT ck_leit_temp CHECK (temperatura_c BETWEEN -20 AND 70),
    umidade_pct     NUMBER(4,1)  CONSTRAINT ck_leit_umid CHECK (umidade_pct BETWEEN 0 AND 100),
    indice_calor_c  NUMBER(4,1),
    simulado        NUMBER(1)    DEFAULT 1 NOT NULL
);

CREATE TABLE t_ref_alerta (
    id_alerta      NUMBER(12)     GENERATED ALWAYS AS IDENTITY CONSTRAINT pk_alerta PRIMARY KEY,
    data_hora      TIMESTAMP      NOT NULL,
    id_pessoa      NUMBER(8)      NOT NULL CONSTRAINT fk_alerta_pessoa REFERENCES t_ref_pessoa_idosa(id_pessoa),
    id_cuidador    NUMBER(8)      CONSTRAINT fk_alerta_cuidador REFERENCES t_ref_cuidador(id_cuidador),
    nivel          VARCHAR2(12)   NOT NULL CONSTRAINT ck_alerta_nivel CHECK (nivel IN ('atencao','alerta','emergencia')),
    tmax_prevista  NUMBER(4,1),
    id_refugio     NUMBER(6)      CONSTRAINT fk_alerta_refugio REFERENCES t_ref_refugio(id_refugio),
    canal          VARCHAR2(12),
    mensagem       VARCHAR2(1000) NOT NULL,
    gerado_por     VARCHAR2(15)   NOT NULL CONSTRAINT ck_alerta_origem CHECK (gerado_por IN ('agente_ia','regra_fallback')),
    status_envio   VARCHAR2(10)   DEFAULT 'simulado' NOT NULL CONSTRAINT ck_alerta_status CHECK (status_envio IN ('simulado','enviado','falhou')),
    simulado       NUMBER(1)      DEFAULT 1 NOT NULL
);

CREATE INDEX ix_setor_bairro   ON t_ref_setor(id_bairro);
CREATE INDEX ix_setor_risco    ON t_ref_setor(indice_risco);
CREATE INDEX ix_pessoa_setor   ON t_ref_pessoa_idosa(cd_setor);
CREATE INDEX ix_alerta_data    ON t_ref_alerta(data_hora);
CREATE INDEX ix_leitura_sensor ON t_ref_leitura_sensor(id_sensor, data_hora);

CREATE OR REPLACE VIEW vw_ref_risco_bairro AS
SELECT b.nome                            AS bairro,
       COUNT(*)                          AS setores,
       SUM(s.idosos_60_mais)             AS idosos,
       ROUND(AVG(s.lst_media), 1)        AS lst_media,
       ROUND(AVG(s.ndvi_media), 2)       AS ndvi_medio,
       ROUND(AVG(s.indice_risco), 1)     AS risco_medio,
       SUM(CASE WHEN s.prioridade IN ('Alta','Muito alta') THEN s.idosos_60_mais ELSE 0 END) AS idosos_alta_prioridade
FROM t_ref_setor s JOIN t_ref_bairro b ON b.id_bairro = s.id_bairro
GROUP BY b.nome;

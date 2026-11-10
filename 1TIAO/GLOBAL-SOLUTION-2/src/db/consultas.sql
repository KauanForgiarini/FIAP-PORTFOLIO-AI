-- =============================================================================
-- Consultas de negócio do Refúgio (cada bloco começa com "-- @nome")
-- =============================================================================

-- @bairros_maior_risco  Q1. Ranking de bairros pelo risco médio (usa a visão)
SELECT bairro, setores, idosos, lst_media, ndvi_medio, risco_medio, idosos_alta_prioridade
FROM vw_risco_bairro
ORDER BY risco_medio DESC
LIMIT 10;

-- @dias_calor_por_ano  Q2. Dias de calor extremo e ondas de calor por ano
SELECT substr(data, 1, 4)  AS ano,
       SUM(dia_quente)     AS dias_35C,
       SUM(onda_calor)     AS dias_em_onda_calor,
       ROUND(MAX(tmax), 1) AS tmax_ano
FROM clima_diario
WHERE data >= '2015-01-01'
GROUP BY ano
ORDER BY ano;

-- @obitos_dia_quente_vs_normal  Q3. Média diária de óbitos de idosos (nov-mar) em dias quentes x demais
SELECT CASE c.dia_quente WHEN 1 THEN 'Tmax >= 35 °C' ELSE 'Tmax < 35 °C' END AS tipo_de_dia,
       COUNT(*)                         AS dias,
       ROUND(AVG(s.obitos_idosos), 2)   AS obitos_idosos_por_dia
FROM saude_diaria s
JOIN clima_diario c ON c.data = s.data
WHERE s.recorte = 'santa_maria'
  AND s.data BETWEEN '2020-01-01' AND '2024-12-31'
  AND CAST(substr(s.data, 6, 2) AS INTEGER) IN (11, 12, 1, 2, 3)
GROUP BY c.dia_quente;

-- @idosos_cadastrados_alto_risco  Q4. Pessoas cadastradas (simuladas) em setores de prioridade alta,
--                                     com o contato principal e o canal adequado
SELECT p.nome, (2026 - p.ano_nascimento) AS idade, b.nome AS bairro, s.prioridade,
       ROUND(s.lst_media, 1) AS lst_setor, p.mora_sozinha,
       c.relacao, c.canal_preferido, c.telefone_mascarado
FROM pessoa_idosa p
JOIN setor s            ON s.cd_setor = p.cd_setor
JOIN bairro b           ON b.id_bairro = s.id_bairro
JOIN pessoa_cuidador pc ON pc.id_pessoa = p.id_pessoa AND pc.principal = 1
JOIN cuidador c         ON c.id_cuidador = pc.id_cuidador
WHERE s.prioridade IN ('Alta', 'Muito alta')
ORDER BY s.indice_risco DESC, idade DESC;

-- @refugios_por_categoria_domingo  Q5. Refúgios climatizados abertos no domingo, por categoria
SELECT categoria,
       COUNT(*) AS total,
       SUM(CASE WHEN instr(dias_abertos, '6') > 0 THEN 1 ELSE 0 END) AS abertos_domingo
FROM refugio
WHERE climatizado = 1
GROUP BY categoria
ORDER BY total DESC;

-- @bairros_prioritarios_plantio  Q6. Bairros com maior benefício esperado do plantio de árvores
SELECT b.nome AS bairro,
       SUM(s.idosos_60_mais)                                 AS idosos,
       ROUND(AVG(s.ndvi_media), 2)                           AS ndvi_medio,
       ROUND(SUM(s.resfriamento_pot_c * s.idosos_60_mais))   AS beneficio_idoso_grau,
       MIN(s.rank_plantio)                                   AS melhor_setor_no_ranking
FROM setor s JOIN bairro b ON b.id_bairro = s.id_bairro
GROUP BY b.nome
ORDER BY beneficio_idoso_grau DESC
LIMIT 10;

-- @idosos_sozinhos_sem_alfabetizacao  Q7. Público que exige alerta por VOZ: mora só e não é alfabetizado
SELECT b.nome AS bairro, COUNT(*) AS pessoas
FROM pessoa_idosa p
JOIN setor s  ON s.cd_setor = p.cd_setor
JOIN bairro b ON b.id_bairro = s.id_bairro
WHERE p.mora_sozinha = 1 OR p.alfabetizada = 0
GROUP BY b.nome
ORDER BY pessoas DESC
LIMIT 10;

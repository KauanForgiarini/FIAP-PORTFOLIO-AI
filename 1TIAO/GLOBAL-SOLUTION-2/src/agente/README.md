# Assistente de alertas (IA generativa + agente)

## O que faz

| Função | Para quem | Como |
|---|---|---|
| `alerta.gerar_alerta()` | Familiar, cuidador ou agente de saúde | **Fluxo controlado por código:** o **nível** é decidido por regra; a IA só **redige** a mensagem (texto para WhatsApp/SMS ou roteiro de **ligação de voz** para quem não lê) |
| `assistente.responder()` | Quem cuida (chat no painel) | **Agente com ferramentas:** a IA decide quais ferramentas chamar (previsão, risco do bairro, refúgio aberto, orientações oficiais) e responde com base nelas |

**Modelo:** Claude Opus 5.5, via **Amazon Bedrock** (`anthropic.claude-opus-5-5`) ou pela API da
Anthropic. O provedor é escolhido em `.env` (`REFUGIO_LLM_PROVEDOR`). Se uma requisição for recusada,
o SDK repete com um modelo alternativo (Claude Opus 4.8).

## Por que o nível do alerta NÃO é decidido pela IA

Quem decide se a situação é de atenção, alerta ou emergência é uma regra explícita e testada
(`definir_nivel`). Ela usa a previsão, o limiar do projeto (percentil 90 = 33,3 °C; 35 °C; 38 °C), a
prioridade do setor, se a pessoa mora sozinha, a idade e o botão de ajuda. Isso torna a decisão
**auditável, reproduzível e independente da IA**. A IA melhora a comunicação, mas nunca deixa um alerta
de fora.

## Segurança e confiabilidade (OWASP Top 10 para LLM)

| Risco | Defesa no código |
|---|---|
| Prompt injection (LLM01) | Detecção de padrões (`seguranca.suspeita_injecao`); dados externos entram em `<dados>` com instrução de serem tratados como informação; ferramentas só leem dados, sem efeito colateral |
| Vazamento de dados (LLM02) | A IA recebe só o primeiro nome, a idade e o bairro, sem sobrenome, telefone ou endereço; a saída passa por `mascarar_pii` |
| Desinformação (LLM09) | Orientações de saúde só da base oficial (RAG, `base_conhecimento.md`); validação exige 192 em emergência e o refúgio citado; sem diagnóstico |
| Indisponibilidade | Qualquer falha (credencial, rede, cota, recusa, JSON inválido) leva à **mensagem de modelo fixo**, que passa na mesma validação |
| Agência excessiva (LLM06) | Lista de permissão de ferramentas, esquemas `strict`, limite de 6 passos por conversa; o envio (SNS) é feito pelo código, não pela IA |

## Testes

`python -m pytest tests/test_agente.py`: 25 testes cobrem a regra de nível, a validação de saída, a
detecção de injeção, o mascaramento de dados pessoais, a recuperação das orientações oficiais (5 de 5
temas corretos) e o alerta completo no modo offline.

## Custos

Um alerta usa ~1.500 tokens de entrada e ~400 de saída. No Claude Opus 5.5 (US$ 4 / US$ 20 por milhão
de tokens na API da Anthropic; preços do Bedrock podem variar), isso dá **cerca de US$ 0,014 por
alerta**: 1.000 alertas custam cerca de US$ 14. O esforço de raciocínio é `low` para a redação
(tarefa simples) e `medium` para o chat.

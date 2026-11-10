# Continuar o projeto em outro computador

> Arquivo de passagem de bastão (sessão do Claude de 08–10/11/2026, no notebook). Numa sessão nova,
> peça: **"leia o 1TIAO/GLOBAL-SOLUTION-2/CONTINUAR.md e continue a GS"**.

## Contexto

- **Global Solution 2026.2 (CitizenTech)**, FIAP IA, Fase 7. Prazo: **19/11/2026 às 23h59** (o repositório
  congela depois). Objetivo: nota máxima e pódio.
- **Projeto Refúgio:** calor extremo × idosos em **Santa Maria/RS**.
- **Grupo:** Kauan Maciel Forgiarini (RM 574005) e Wagner Adriano de Souza Silva Junior (RM 569431). É
  uma **dupla**, e o enunciado pede 3 a 5 integrantes: aguardando confirmação por escrito da tutoria.
- **Turma:** ainda não informada. O projeto está em `1TIAO/` por suposição; se for 2TIAO, mova com
  `git mv 1TIAO/GLOBAL-SOLUTION-2 2TIAO/`.

## O que já está pronto (tudo testado: `python -m pytest` → 43 passed)

| Módulo | Onde | Situação |
|---|---|---|
| Dados reais (Landsat, Sentinel-2, Censo, clima, DATASUS, OSM, EuroSAT) | `src/data/` | ✅ `data/raw` fica fora do Git: rode `python -m src.data.baixar_dados` |
| Calor × saúde (+14% de óbitos de idosos em dias ≥ 35 °C) | `src/analise/` | ✅ |
| CNN ResNet-18 (98,0% de acurácia), aplicada ao Sentinel-2 | `src/ml/cnn_eurosat.py`, `aplicar_cnn.py` | ✅ modelo em `src/ml/modelos/` |
| Índice de risco IPCC + K-Means (k=3) | `src/ml/vulnerabilidade.py` | ✅ |
| Recomendação de refúgio e de plantio | `src/ml/recomendacao.py` | ✅ |
| Banco SQLite + Oracle, 7 consultas | `src/db/` | ✅ `data/processed/refugio.db` |
| ESP32 (Wokwi) + ponte MQTT com TLS + HMAC | `src/iot/` | ✅ compila no Wokwi; ⏳ teste em tempo real |
| Assistente de alertas (Bedrock / offline) | `src/agente/` | ✅ em **modo offline**: a conta AWS Academy bloqueia o Bedrock |
| AWS: DynamoDB `refugio-leituras` + SNS `refugio-alertas` | `src/cloud/provisionar_aws.py` | ✅ criados e testados em 08/11 |
| Painel Streamlit | `src/app/painel.py` | ✅ |
| Notebooks 01 e 02 (executados) | `notebooks/` | ✅ |
| PDF da entrega (9 páginas) | `docs/relatorio/` | ✅ falta preencher os campos em amarelo |
| Roteiro do vídeo | `docs/roteiro_video.md` | ✅ |

## Configurar o computador novo

```bash
git clone <URL do repositório privado>
cd FIAP-PORTFOLIO-AI/1TIAO/GLOBAL-SOLUTION-2
python -m venv .venv
.venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
pip install -r requirements.txt pytest "anthropic[bedrock]" pypdf
copy .env.example .env
```

No `.env`, defina `REFUGIO_LLM_PROVEDOR=offline`. Os valores da AWS (`REFUGIO_DYNAMO_TABELA=refugio-leituras`
e o ARN do tópico `refugio-alertas`) também vão no `.env`, que **não vai para o Git**.

Opcional, para baixar os dados brutos de novo (~650 MB): `python -m src.data.baixar_dados`. Os dados
processados, o banco e o modelo já estão no repositório, então o painel e os testes funcionam sem esse passo.

Credenciais da AWS: inicie o laboratório no AWS Academy, abra "AWS Details", copie o bloco "AWS CLI" e
cole em `%USERPROFILE%\.aws\credentials`. Elas expiram a cada sessão.

## Pendências até 19/11

1. Confirmação da tutoria sobre a dupla; definir o **nome do grupo**, a **turma** e o **tutor** (README e
   `docs/relatorio/relatorio.html`, campos `[ ... ]`).
2. Testar o ESP32 no Wokwi em tempo real (ver `src/iot/README.md`) e colocar o print no PDF.
3. Gravar o vídeo (≤ 5 min, "QUERO CONCORRER" no início), publicar como **não listado** e colocar o link
   no PDF e no README.
4. Gerar o PDF final: imprimir `docs/relatorio/relatorio.html` com o Edge ("Salvar como PDF", sem
   cabeçalho e rodapé).
5. Repositório **privado**, com convite somente para `fiap-tutoria`.
6. Entregar o PDF único na plataforma antes do prazo.

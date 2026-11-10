"""Cria (de forma idempotente) os recursos AWS do Refúgio.

    python -m src.cloud.provisionar_aws                       # só mostra o plano (nada é criado)
    python -m src.cloud.provisionar_aws --executar --email voce@exemplo.com --salvar-env

Recursos (todos cabem no nível gratuito ou custam centavos):
    1. Amazon DynamoDB  "refugio-leituras"  - leituras dos sensores (NoSQL, cobrança sob demanda)
    2. Amazon SNS       "refugio-alertas"   - envio dos alertas (o e-mail informado recebe a demonstração)
    3. Amazon Bedrock   (Claude)            - teste de acesso ao modelo do assistente
    4. AWS Budgets      US$ 5/mês           - alerta de custo (pode ser bloqueado em contas AWS Academy)

Credenciais: cadeia padrão da AWS (aws configure / ~/.aws/credentials / variáveis de ambiente).
Nenhuma chave fica no código. Em contas AWS Academy, as credenciais expiram a cada sessão do laboratório.
"""
from __future__ import annotations

import argparse
import os
import re

import boto3
from botocore.exceptions import ClientError, NoCredentialsError

from src import config as C

REGIAO = os.environ.get("AWS_REGION", "us-east-1")
TABELA = "refugio-leituras"
TOPICO = "refugio-alertas"


def passo(msg):
    print(f"\n▶ {msg}")


def identidade(sessao):
    try:
        i = sessao.client("sts").get_caller_identity()
    except (ClientError, NoCredentialsError) as e:
        raise SystemExit(f"Credenciais AWS inválidas ou expiradas ({e.__class__.__name__}). "
                         "No AWS Academy: inicie o laboratório, copie as credenciais de 'AWS Details' para "
                         "~/.aws/credentials e rode de novo.")
    print(f"  conta {i['Account']} | {i['Arn'].split('/')[-1]} | região {REGIAO}")
    return i["Account"]


def criar_tabela(sessao, executar):
    ddb = sessao.client("dynamodb", region_name=REGIAO)
    try:
        ddb.describe_table(TableName=TABELA)
        print(f"  ✓ tabela {TABELA} já existe")
        return
    except ClientError as e:
        if e.response["Error"]["Code"] != "ResourceNotFoundException":
            raise
    if not executar:
        print(f"  (plano) criar tabela {TABELA}: chave id_sensor (S) + seq (N), PAY_PER_REQUEST")
        return
    ddb.create_table(TableName=TABELA, BillingMode="PAY_PER_REQUEST",
                     AttributeDefinitions=[{"AttributeName": "id_sensor", "AttributeType": "S"},
                                           {"AttributeName": "seq", "AttributeType": "N"}],
                     KeySchema=[{"AttributeName": "id_sensor", "KeyType": "HASH"},
                                {"AttributeName": "seq", "KeyType": "RANGE"}],
                     Tags=[{"Key": "projeto", "Value": "refugio-gs-fiap"}])
    ddb.get_waiter("table_exists").wait(TableName=TABELA)
    print(f"  ✓ tabela {TABELA} criada")


def criar_topico(sessao, executar, email):
    sns = sessao.client("sns", region_name=REGIAO)
    if not executar:
        print(f"  (plano) criar tópico {TOPICO}" + (f" e inscrever {email}" if email else ""))
        return None
    arn = sns.create_topic(Name=TOPICO, Tags=[{"Key": "projeto", "Value": "refugio-gs-fiap"}])["TopicArn"]
    print(f"  ✓ tópico {arn}")
    if email:
        sns.subscribe(TopicArn=arn, Protocol="email", Endpoint=email)
        print(f"  ✓ inscrição enviada para {email} - confirme clicando no link do e-mail da AWS")
    return arn


def criar_orcamento(sessao, conta, executar, email):
    if not email:
        print("  (pulado) informe --email para receber o alerta de custo")
        return
    if not executar:
        print(f"  (plano) orçamento mensal de US$ 5 com aviso em 80% para {email}")
        return
    try:
        sessao.client("budgets").create_budget(
            AccountId=conta,
            Budget={"BudgetName": "refugio-limite-5usd", "BudgetLimit": {"Amount": "5", "Unit": "USD"},
                    "TimeUnit": "MONTHLY", "BudgetType": "COST"},
            NotificationsWithSubscribers=[{
                "Notification": {"NotificationType": "ACTUAL", "ComparisonOperator": "GREATER_THAN",
                                 "Threshold": 80, "ThresholdType": "PERCENTAGE"},
                "Subscribers": [{"SubscriptionType": "EMAIL", "Address": email}]}])
        print("  ✓ orçamento criado")
    except ClientError as e:
        codigo = e.response["Error"]["Code"]
        if codigo == "DuplicateRecordException":
            print("  ✓ orçamento já existe")
        else:
            print(f"  ! não foi possível criar o orçamento ({codigo}) - comum em contas AWS Academy, que já têm "
                  "limite de crédito próprio")


def testar_bedrock(executar):
    from src.agente import llm
    if not executar:
        print(f"  (plano) chamada de teste ao modelo {llm.MODELO} (custo de frações de centavo)")
        return
    try:
        r = llm.criar(max_tokens=300, output_config={"effort": "low"},
                      messages=[{"role": "user", "content": "Responda só: OK"}])
        print(f"  ✓ modelo respondeu: {llm.texto_da_resposta(r)[:40]!r} ({llm.descricao()})")
    except llm.IAIndisponivel as e:
        print(f"  ! Bedrock indisponível: {e}. O sistema seguirá no modo offline. Verifique se o modelo está "
              "liberado no console do Bedrock (Model access) e se a conta permite o Bedrock.")


def salvar_env(valores: dict):
    caminho = C.RAIZ / ".env"
    texto = caminho.read_text(encoding="utf-8") if caminho.exists() else ""
    for k, v in valores.items():
        if v is None:
            continue
        linha = f"{k}={v}"
        texto = re.sub(rf"^#?\s*{k}=.*$", linha, texto, flags=re.M) if re.search(rf"^#?\s*{k}=", texto, re.M) \
            else texto + ("\n" if texto and not texto.endswith("\n") else "") + linha + "\n"
    caminho.write_text(texto, encoding="utf-8")
    print(f"  ✓ {', '.join(k for k, v in valores.items() if v)} gravados em .env")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--executar", action="store_true", help="cria de fato os recursos")
    ap.add_argument("--email", help="e-mail que recebe o alerta de custo e a demonstração do SNS")
    ap.add_argument("--salvar-env", action="store_true")
    a = ap.parse_args()
    print("MODO:", "EXECUÇÃO" if a.executar else "PLANO (nada será criado; use --executar)")
    sessao = boto3.Session(region_name=REGIAO)
    passo("Identidade AWS")
    conta = identidade(sessao)
    passo("Orçamento (proteção de custo)")
    criar_orcamento(sessao, conta, a.executar, a.email)
    passo("DynamoDB - leituras dos sensores")
    criar_tabela(sessao, a.executar)
    passo("SNS - alertas")
    arn = criar_topico(sessao, a.executar, a.email)
    passo("Bedrock - IA generativa")
    testar_bedrock(a.executar)
    if a.executar and a.salvar_env:
        passo("Configuração local")
        salvar_env({"REFUGIO_DYNAMO_TABELA": TABELA, "REFUGIO_SNS_TOPICO_ARN": arn, "AWS_REGION": REGIAO})


if __name__ == "__main__":
    main()

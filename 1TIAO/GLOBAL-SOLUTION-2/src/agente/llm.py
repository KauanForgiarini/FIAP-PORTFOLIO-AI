"""Acesso ao modelo de IA generativa (Claude), via Amazon Bedrock ou API da Anthropic.

Configuração (.env):
    REFUGIO_LLM_PROVEDOR = bedrock (padrão) | anthropic | offline
    REFUGIO_LLM_MODELO   = anthropic.claude-opus-5-5 (Bedrock) | claude-opus-5-5 (Anthropic)
    AWS_REGION           = us-east-1

Credenciais: nunca no código. Bedrock usa a cadeia padrão da AWS (aws configure,
variáveis de ambiente ou perfil). A API da Anthropic usa ANTHROPIC_API_KEY.

Se o provedor estiver indisponível (sem credencial, sem rede, cota), o sistema
continua funcionando com mensagens de modelo fixo (modo offline). O alerta
nunca deixa de sair por causa da IA.

Recusas: o modelo pode recusar um pedido (stop_reason "refusal"). Ativamos a
troca automática para um modelo alternativo: no Bedrock pelo middleware do SDK,
na API da Anthropic pelo parâmetro `fallbacks` do servidor.
"""
from __future__ import annotations

import os
from contextlib import nullcontext
from functools import lru_cache

from dotenv import load_dotenv

from src import config as C

load_dotenv(C.RAIZ / ".env")

PROVEDOR = os.environ.get("REFUGIO_LLM_PROVEDOR", "bedrock").lower()
REGIAO = os.environ.get("AWS_REGION", "us-east-1")
MODELO = os.environ.get("REFUGIO_LLM_MODELO") or (
    "anthropic.claude-opus-5-5" if PROVEDOR == "bedrock" else "claude-opus-5-5")
MODELO_RESERVA = "anthropic.claude-opus-4-8" if PROVEDOR == "bedrock" else "claude-opus-4-8"


class IAIndisponivel(RuntimeError):
    """O provedor de IA não pode ser usado agora (o chamador deve usar o modo offline)."""


@lru_cache(maxsize=1)
def _cliente():
    if PROVEDOR == "offline":
        raise IAIndisponivel("modo offline configurado")
    if PROVEDOR == "bedrock":
        from anthropic import AnthropicBedrockMantle, BetaRefusalFallbackMiddleware
        return AnthropicBedrockMantle(
            aws_region=REGIAO, max_retries=2, timeout=60,
            middleware=[BetaRefusalFallbackMiddleware([{"model": MODELO_RESERVA}])])
    from anthropic import Anthropic
    return Anthropic(max_retries=2, timeout=60)


def nova_conversa():
    """Estado de fallback por conversa (no Bedrock fixa o modelo que aceitou o pedido)."""
    if PROVEDOR == "bedrock":
        from anthropic import BetaFallbackState
        return BetaFallbackState()
    return nullcontext()


def criar(estado=None, **kwargs):
    """Chama a Messages API (beta) no provedor configurado. Levanta IAIndisponivel em falhas de acesso."""
    import anthropic
    try:
        cli = _cliente()
        extras = {} if PROVEDOR == "bedrock" else {"betas": ["server-side-fallback-2026-07-01"],
                                                   "fallbacks": "default"}
        with (estado if estado is not None else nova_conversa()):
            return cli.beta.messages.create(model=MODELO, **extras, **kwargs)
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError, anthropic.NotFoundError) as e:
        raise IAIndisponivel(f"sem acesso ao modelo {MODELO}: {e.__class__.__name__}") from e
    except anthropic.APIConnectionError as e:
        raise IAIndisponivel(f"sem conexão com o provedor: {e.__class__.__name__}") from e
    except anthropic.RateLimitError as e:
        raise IAIndisponivel("limite de uso atingido") from e
    except anthropic.APIStatusError as e:
        raise IAIndisponivel(f"erro {e.status_code} do provedor") from e
    except Exception as e:  # credenciais AWS ausentes/expiradas chegam como erros do botocore
        if e.__class__.__module__.startswith(("botocore", "anthropic")):
            raise IAIndisponivel(f"{e.__class__.__name__}: {str(e)[:120]}") from e
        raise


def texto_da_resposta(resposta) -> str:
    return "".join(b.text for b in resposta.content if getattr(b, "type", "") == "text").strip()


def descricao() -> str:
    return f"{PROVEDOR} / {MODELO}" if PROVEDOR != "offline" else "offline (mensagens de modelo fixo)"

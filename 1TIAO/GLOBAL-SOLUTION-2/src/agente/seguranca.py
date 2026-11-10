"""Camada de segurança do assistente (cibersegurança + confiabilidade da informação).

Ameaças consideradas (OWASP Top 10 para aplicações com LLM):
- LLM01 Prompt injection: texto malicioso no pedido do usuário ou em dados
  externos (ex.: o nome de um local no OpenStreetMap) tentando mudar as regras.
- LLM02 Vazamento de dados sensíveis: telefone, CPF, e-mail ou endereço na resposta.
- LLM09 Desinformação: orientação de saúde inventada, ou omitir o 192 numa emergência.

Defesas:
1. Entrada: limite de tamanho, remoção de caracteres de controle e detecção de
   padrões de injeção (registrada e tratada como dado, nunca como instrução).
2. Dados externos chegam ao modelo dentro de marcações <dados>, com instrução
   explícita para tratá-los como informação, e não como comandos.
3. Ferramentas: lista de permissão (allowlist), esquemas estritos e nenhuma
   ferramenta com efeito colateral (a IA não envia mensagens nem altera o banco).
4. Saída: validação automática (tamanho, 192 em emergência, refúgio citado,
   ausência de dados pessoais e de links). Se reprovar, usa a mensagem de modelo fixo.
"""
from __future__ import annotations

import re
import unicodedata

PADROES_INJECAO = [
    r"ignor\w*\s+(as\s+|todas\s+as\s+|the\s+)?(instru|regra|previous|above|anteriores)",
    r"desconsider\w*\s+(as\s+)?(instru|regra)",
    r"(system|developer)\s*prompt", r"prompt\s+do\s+sistema",
    r"voc[eê]\s+(agora\s+)?([eé]|ser[aá])\s+(um|uma|o|a)\s+", r"you\s+are\s+now",
    r"</?\s*(system|assistant|dados|instrucoes)\s*>",
    r"revel\w*\s+(suas|as)\s+(instru|regra)", r"jailbreak", r"modo\s+desenvolvedor",
]
_RE_INJ = re.compile("|".join(PADROES_INJECAO), re.I)
_RE_TELEFONE = re.compile(r"(?<!\d)(\(?\d{2}\)?\s?)?9?\d{4}[-\s]?\d{4}(?!\d)")
_RE_CPF = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}")
_RE_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_RE_URL = re.compile(r"https?://|www\.", re.I)


def limpar_entrada(texto: str, max_len: int = 800) -> str:
    texto = "".join(ch for ch in str(texto) if unicodedata.category(ch)[0] != "C" or ch in "\n\t")
    return texto.strip()[:max_len]


def suspeita_injecao(texto: str) -> bool:
    return bool(_RE_INJ.search(texto or ""))


def mascarar_pii(texto: str) -> str:
    texto = _RE_EMAIL.sub("[e-mail removido]", texto)
    texto = _RE_CPF.sub("[documento removido]", texto)
    return _RE_TELEFONE.sub(lambda m: m.group(0) if m.group(0).strip() in {"192", "193", "199"} else "[telefone removido]",
                            texto)


def validar_alerta(saida: dict, ctx: dict) -> list[str]:
    """Retorna a lista de problemas (vazia = aprovado)."""
    problemas = []
    msg, voz = saida.get("mensagem", ""), saida.get("roteiro_voz", "")
    if not (40 <= len(msg) <= 600):
        problemas.append("mensagem com tamanho fora de 40-600 caracteres")
    if len(voz) > 900:
        problemas.append("roteiro de voz longo demais")
    tudo = f"{msg} {voz}"
    if ctx["nivel"] == "emergencia" and "192" not in tudo:
        problemas.append("emergência sem o telefone do SAMU 192")
    if ctx.get("refugio") and ctx["refugio"]["nome"].split(" (")[0][:20].lower() not in tudo.lower():
        problemas.append("refúgio recomendado não foi citado")
    if mascarar_pii(tudo) != tudo:
        problemas.append("resposta contém dado pessoal (telefone, documento ou e-mail)")
    if _RE_URL.search(tudo):
        problemas.append("resposta contém link")
    if suspeita_injecao(tudo):
        problemas.append("resposta contém padrão de injeção")
    return problemas

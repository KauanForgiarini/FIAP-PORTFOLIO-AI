"""Leitor de arquivos .dbc do DATASUS em Python puro (sem compilador C).

O formato .dbc é um arquivo DBF (dBase) cujo corpo foi comprimido com o
algoritmo "PKWare DCL implode". As bibliotecas usuais (pyreaddbc, read.dbc)
dependem de código C; aqui portamos para Python o descompressor de referência
`blast.c`, de Mark Adler (distribuído com o zlib, licença zlib), e lemos o DBF
resultante com numpy, extraindo apenas as colunas necessárias.

Estrutura do .dbc:
    bytes [0, header)          -> cabeçalho DBF sem compressão
    bytes [header, header + 4) -> CRC (ignorado)
    bytes [header + 4, fim)    -> registros comprimidos (PKWare DCL)
onde `header` é o inteiro little-endian dos bytes 8-9.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

MAXBITS = 13

# Tabelas fixas do formato PKWare DCL (copiadas de blast.c)
_LITLEN = bytes([
    11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8,
    9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24, 12, 11, 7, 9, 11, 12, 6, 7, 22, 5,
    7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12,
    8, 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27,
    44, 253, 253, 253, 252, 252, 252, 13, 12, 45, 12, 45, 12, 61, 12, 45,
    44, 173])
_LENLEN = bytes([2, 35, 36, 53, 38, 23])
_DISTLEN = bytes([2, 20, 53, 230, 247, 151, 248])
_BASE = (3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264)
_EXTRA = (0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8)


def _construir(rep: bytes):
    """Monta a tabela de Huffman canônica (contagem por tamanho + símbolos ordenados)."""
    tamanhos: list[int] = []
    for b in rep:
        tamanhos += [b & 15] * ((b >> 4) + 1)
    contagem = [0] * (MAXBITS + 1)
    for t in tamanhos:
        contagem[t] += 1
    offs = [0] * (MAXBITS + 1)
    for t in range(1, MAXBITS):
        offs[t + 1] = offs[t] + contagem[t]
    simbolos = [0] * len(tamanhos)
    for s, t in enumerate(tamanhos):
        if t:
            simbolos[offs[t]] = s
            offs[t] += 1
    return contagem, simbolos


_LIT = _construir(_LITLEN)
_LEN = _construir(_LENLEN)
_DIST = _construir(_DISTLEN)


def blast(dados: bytes) -> bytearray:
    """Descomprime um fluxo PKWare DCL (implode). Porte direto de blast.c."""
    n = len(dados)
    pos = 0
    bitbuf = 0
    bitcnt = 0
    saida = bytearray()

    def bits(need: int) -> int:
        nonlocal pos, bitbuf, bitcnt
        val = bitbuf
        while bitcnt < need:
            if pos >= n:
                raise EOFError("fim inesperado dos dados comprimidos")
            val |= dados[pos] << bitcnt
            pos += 1
            bitcnt += 8
        bitbuf = val >> need
        bitcnt -= need
        return val & ((1 << need) - 1)

    def decode(tabela) -> int:
        nonlocal pos, bitbuf, bitcnt
        contagem, simbolos = tabela
        tam = 1
        code = first = index = 0
        bb = bitbuf
        left = bitcnt
        nxt = 1
        while True:
            while left:
                left -= 1
                code |= (bb & 1) ^ 1  # códigos são armazenados invertidos
                bb >>= 1
                count = contagem[nxt]
                nxt += 1
                if code < first + count:
                    bitbuf = bb
                    bitcnt = (bitcnt - tam) & 7
                    return simbolos[index + (code - first)]
                index += count
                first = (first + count) << 1
                code <<= 1
                tam += 1
            left = (MAXBITS + 1) - tam
            if left == 0:
                raise ValueError("código de Huffman inválido")
            if pos >= n:
                raise EOFError("fim inesperado dos dados comprimidos")
            bb = dados[pos]
            pos += 1
            if left > 8:
                left = 8

    lit = bits(8)
    if lit > 1:
        raise ValueError("cabeçalho DCL inválido (literal)")
    dic = bits(8)
    if dic < 4 or dic > 6:
        raise ValueError("cabeçalho DCL inválido (dicionário)")

    while True:
        if bits(1):
            simbolo = decode(_LEN)
            tamanho = _BASE[simbolo] + bits(_EXTRA[simbolo])
            if tamanho == 519:  # código de fim
                break
            s = 2 if tamanho == 2 else dic
            dist = (decode(_DIST) << s) + bits(s) + 1
            if dist > len(saida):
                raise ValueError("distância maior que o já descomprimido")
            inicio = len(saida) - dist
            if dist >= tamanho:
                saida += saida[inicio:inicio + tamanho]
            else:  # cópia sobreposta: repete o padrão
                padrao = saida[inicio:]
                saida += (padrao * (tamanho // dist + 1))[:tamanho]
        else:
            saida.append(decode(_LIT) if lit else bits(8))
    return saida


def dbc_para_dbf(caminho: str | Path) -> bytes:
    bruto = Path(caminho).read_bytes()
    header = bruto[8] | (bruto[9] << 8)
    return bytes(bruto[:header]) + bytes(blast(bruto[header + 4:]))


def ler_dbf(buf: bytes, colunas: list[str] | None = None) -> pd.DataFrame:
    """Lê um DBF (em memória) como DataFrame de textos, só com as colunas pedidas."""
    nreg = int.from_bytes(buf[4:8], "little")
    hlen = int.from_bytes(buf[8:10], "little")
    rlen = int.from_bytes(buf[10:12], "little")
    campos, off, i = [], 1, 32  # o 1º byte de cada registro é a marca de exclusão
    while buf[i] != 0x0D:
        nome = buf[i:i + 11].split(b"\0")[0].decode("latin-1").strip()
        tam = buf[i + 16]
        campos.append((nome, off, tam))
        off += tam
        i += 32
    if len(buf) < hlen + nreg * rlen:
        raise ValueError(f"DBF truncado: esperado {hlen + nreg * rlen} bytes, obtido {len(buf)}")
    arr = np.frombuffer(buf, dtype=np.uint8, count=nreg * rlen, offset=hlen).reshape(nreg, rlen)
    ativos = arr[:, 0] != ord("*")
    dados = {}
    for nome, off, tam in campos:
        if colunas and nome not in colunas:
            continue
        col = np.ascontiguousarray(arr[ativos, off:off + tam]).view(f"S{tam}").ravel()
        dados[nome] = pd.Series(col).str.decode("latin-1").str.strip()
    return pd.DataFrame(dados)


def ler_dbc(caminho: str | Path, colunas: list[str] | None = None) -> pd.DataFrame:
    return ler_dbf(dbc_para_dbf(caminho), colunas)


if __name__ == "__main__":
    import sys
    import time

    t = time.time()
    df = ler_dbc(sys.argv[1])
    print(f"{len(df)} registros, {df.shape[1]} colunas em {time.time() - t:.1f}s")
    print(df.head())

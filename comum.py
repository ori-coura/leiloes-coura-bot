"""Utilitários partilhados pelas fontes de leilões."""

import re
import unicodedata

import requests

TIMEOUT = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9",
}

CONCELHO = "Paredes de Coura"


class ScrapeError(RuntimeError):
    """A estrutura da fonte mudou — é preciso rever o código."""


def normalizar(texto):
    """minúsculas, sem acentos, espaços colapsados — para comparar nomes."""
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip().lower()


def chave(texto):
    """
    Normaliza uma etiqueta para comparação, sem pontuação.
    'N.º Leilão Finanças:' -> 'no leilao financas'
    (atenção: o 'º' decompõe-se em 'o' no NFKD, daí o 'no'.)
    """
    return re.sub(r"[^a-z0-9 ]", "", normalizar(texto)).strip()


def euros(valor):
    """10000.0 -> '10 000,00 €'"""
    if valor in (None, ""):
        return "?"
    try:
        formatado = "{:,.2f}".format(float(valor))
    except (TypeError, ValueError):
        return str(valor)
    # de 1,234.56 (formato inglês) para 1 234,56
    return formatado.replace(",", " ").replace(".", ",") + " €"


def data_iso(texto):
    """'2026-08-05T11:00:00' -> '2026-08-05 11:00'"""
    if not texto:
        return "?"
    return str(texto).replace("T", " ")[:16]

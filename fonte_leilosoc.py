"""
Fonte: leilosoc.com — leiloeira privada (execuções, insolvências, vendas de banca).

O site é Next.js: os lotes vêm dentro do <script id="__NEXT_DATA__"> de cada
página de categoria, sem ser preciso API nem autenticação.

  GET /pt/category/5-imovel/?page=N  ->  __NEXT_DATA__.props.pageProps.lots

Só se segue a categoria **Imóveis** (id 5). As outras (veículos, maquinaria,
mobiliário…) multiplicariam os pedidos por dez e não é o que procuras — se um dia
quiseres tudo, acrescenta os slugs a CATEGORIAS.
"""

import json
import re

from comum import (
    CONCELHO,
    TIMEOUT,
    SESSAO,
    ScrapeError,
    area,
    data_iso,
    euros,
    normalizar,
)

NOME = "leilosoc"
ETIQUETA = "Leilosoc"

BASE = "https://leilosoc.com"
CATEGORIAS = ["5-imovel"]
LOTE_URL = BASE + "/pt/lot/%s/%s/"
MAX_PAGINAS = 30  # travão de segurança


def _pagina(slug, numero):
    url = "%s/pt/category/%s/?page=%d" % (BASE, slug, numero)
    resposta = SESSAO.get(url, timeout=TIMEOUT)
    resposta.raise_for_status()
    resposta.encoding = "utf-8"

    encontrado = re.search(
        r'id="__NEXT_DATA__"[^>]*>(.*?)</script>', resposta.text, re.S
    )
    if not encontrado:
        raise ScrapeError(
            "Não encontrei __NEXT_DATA__ em %s — o site deixou de ser Next.js?" % url
        )

    try:
        dados = json.loads(encontrado.group(1))
    except ValueError:
        raise ScrapeError("__NEXT_DATA__ não é JSON válido em %s" % url)

    lotes = (dados.get("props", {}).get("pageProps", {}) or {}).get("lots")
    if not isinstance(lotes, dict):
        raise ScrapeError("pageProps.lots ausente ou com forma inesperada em %s" % url)
    return lotes


def _sem_html(texto):
    """As descrições vêm com <p>, <strong>, <br>…"""
    limpo = re.sub(r"<br\s*/?>", " ", texto or "")
    limpo = re.sub(r"<[^>]+>", " ", limpo)
    limpo = (
        limpo.replace("&nbsp;", " ")
        .replace("&amp;", "&")
        .replace("&ordm;", "º")
        .replace("&deg;", "°")
    )
    return re.sub(r"\s+", " ", limpo).strip()


def _normalizado(lote):
    identificador = str(lote.get("batchId") or lote.get("reference"))

    morada = " ".join(
        str(parte)
        for parte in [lote.get("address"), lote.get("addressNumber")]
        if parte
    ).strip()
    local = ", ".join(
        parte
        for parte in [morada, lote.get("addressZipCode"), lote.get("addressLocation")]
        if parte
    )

    extra = [("Modalidade", lote.get("auctionTypeCode") or "Leilão")]
    if lote.get("valueMinimum") and lote.get("valueMinimumPublished"):
        extra.append(("Valor mínimo", euros(lote["valueMinimum"])))
    if lote.get("valueOpen"):
        extra.append(("Licitação inicial", euros(lote["valueOpen"])))
    if lote.get("processNumber"):
        extra.append(("Processo", lote["processNumber"]))
    if lote.get("processEntityName"):
        extra.append(("Entidade", lote["processEntityName"]))

    latitude = lote.get("addressLatitude")
    longitude = lote.get("addressLongitude")

    return {
        "fonte": NOME,
        "id": identificador,
        "titulo": _sem_html(lote.get("title")) or identificador,
        "resumo": " · ".join(
            parte
            for parte in ["Imóvel", lote.get("addressLocation")]
            if parte
        ),
        "descricao": _sem_html(lote.get("description"))[:1200],
        "valor": euros(lote.get("valueBase"))
        if lote.get("valueBasePublished")
        else "sob consulta",
        "data_fim": data_iso(lote.get("auctionEndDate")),
        "rotulo_data": "Termina em",
        "local": local,
        "url": LOTE_URL % (lote.get("auctionId"), identificador),
        "coordenadas": "%s,%s" % (latitude, longitude)
        if latitude and longitude
        else None,
        "extra": extra,
    }


def recolher(registar=print):
    """Devolve a lista de itens normalizados do concelho nesta fonte."""
    alvo = normalizar(CONCELHO)
    itens, total_visto = [], 0

    for slug in CATEGORIAS:
        primeira = _pagina(slug, 1)
        total = primeira.get("totalCount") or 0
        paginas = min(primeira.get("totalPages") or 1, MAX_PAGINAS)
        lotes = list(primeira.get("items") or [])

        for numero in range(2, paginas + 1):
            lotes.extend(_pagina(slug, numero).get("items") or [])

        if total and not lotes:
            raise ScrapeError(
                "%s anuncia %d lotes em %s mas não extraí nenhum." % (ETIQUETA, total, slug)
            )

        total_visto += len(lotes)
        itens.extend(
            _normalizado(lote)
            for lote in lotes
            if normalizar(lote.get("addressLocation")) == alvo
        )

    registar(
        "[%s] %d imóveis no país, %d em %s."
        % (ETIQUETA, total_visto, len(itens), CONCELHO)
    )
    return itens

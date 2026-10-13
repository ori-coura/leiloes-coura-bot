"""
Fonte: pesquisabenspenhorados.com — agregador de bens penhorados.

ATENÇÃO: o site foi reconstruído de raiz em outubro de 2026. Saiu o ASP.NET
(`DirectorySearch.aspx?viewType=1&districtId=174`) e entrou um site com URLs
limpos. O endereço antigo passou a redirecionar para `/distrito/<distrito>`.

O que se perdeu e o que se ganhou
---------------------------------
Desapareceu o truque do "link vs texto simples" — o concelho sem anúncios
aparecia como texto e com anúncios como link, e era daí que se lia o
municipalityId. Agora há um URL direto por concelho:

    /distrito/viana-do-castelo/paredes-de-coura

Sem anúncios, a página diz "Nenhum anúncio corresponde a estes filtros".
Nada de IDs para adivinhar, o que torna isto bem mais sólido do que era.

Ganhou-se uma coisa importante: o agregador passou a incluir **também o
e-leiloes.pt**, que o GitHub Actions não consegue alcançar por bloqueio de IP.
Por aqui esses anúncios chegam na mesma ao CI. Os que vierem do e-leiloes são
marcados com `duplica_de`, para o monitor não avisar duas vezes quando a fonte
direta também correu (no Mac).
"""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from comum import CONCELHO, SESSAO, TIMEOUT, ScrapeError, normalizar

NOME = "financas"  # mantém-se, para não partir o histórico no seen.json
ETIQUETA = "Pesquisa Bens Penhorados"

BASE = "https://www.pesquisabenspenhorados.com"
CONCELHO_URL = BASE + "/distrito/viana-do-castelo/paredes-de-coura"
MAX_PAGINAS = 25

SEM_RESULTADOS = "nenhum anuncio corresponde"
ORIGENS = {"financas": "Finanças", "eleiloes": "e-leilões"}


def obter(url):
    resposta = SESSAO.get(url, timeout=TIMEOUT)
    resposta.raise_for_status()
    resposta.encoding = "utf-8"
    return BeautifulSoup(resposta.text, "html.parser")


def _texto(no):
    return re.sub(r"\s+", " ", no.get_text(" ", strip=True)) if no else ""


def _paginas(sopa):
    """Lê 'N anúncios · página 1 de 3' e devolve o total de páginas."""
    resumo = _texto(sopa.find("p", class_="results-summary"))
    encontrado = re.search(r"p[áa]gina\s+\d+\s+de\s+(\d+)", resumo, re.I)
    return int(encontrado.group(1)) if encontrado else 1


def _cartoes(sopa):
    return sopa.select("ul.listings li.listing")


def _do_cartao(cartao):
    ligacao = cartao.select_one("h2 a[href]")
    if ligacao is None:
        raise ScrapeError("Cartão de anúncio sem <h2><a>.")

    href = ligacao["href"]
    partes = re.match(r"/anuncio/([^/]+)/(.+)$", href)
    if not partes:
        raise ScrapeError("Href de anúncio inesperado: %s" % href)
    origem, referencia = partes.group(1), partes.group(2)

    meta = cartao.select("p.listing-meta > span")
    etiquetas = [_texto(s) for s in meta]
    # O primeiro span é a fonte; os seguintes, categoria e modalidade.
    categoria = etiquetas[1] if len(etiquetas) > 1 else ""
    modalidade = etiquetas[2] if len(etiquetas) > 2 else ""

    valor = _texto(cartao.select_one("span.listing-value")) or "?"

    prazo = ""
    for span in cartao.select("p.listing-numbers > span"):
        texto = _texto(span)
        if texto.lower().startswith("termina"):
            prazo = texto.replace("termina", "").strip()

    return {
        "origem": origem,
        "referencia": referencia,
        "titulo": _texto(ligacao),
        "url": urljoin(BASE, href),
        "categoria": categoria,
        "modalidade": modalidade,
        "valor": valor,
        "data_fim": prazo,
    }


def _detalhe(url):
    """Os factos do anúncio e o link para a fonte original."""
    sopa = obter(url)
    factos = {}
    lista = sopa.find("dl", class_="detail-facts")
    if lista:
        for dt in lista.find_all("dt"):
            dd = dt.find_next_sibling("dd")
            if dd is not None:
                factos[_texto(dt)] = _texto(dd)

    origem = sopa.find("a", class_="detail-origin", href=True)
    return factos, (origem["href"] if origem else None)


def _normalizado(bruto, factos, link_origem):
    extra = [("Fonte original", ORIGENS.get(bruto["origem"], bruto["origem"]))]
    for rotulo in ("Categoria", "Modalidade", "Venda", "Indexado em"):
        if factos.get(rotulo):
            extra.append((rotulo, factos[rotulo]))
    if link_origem:
        extra.append(("Anúncio na fonte", link_origem))

    item = {
        "fonte": NOME,
        "id": "%s/%s" % (bruto["origem"], bruto["referencia"]),
        "titulo": bruto["titulo"],
        "resumo": " · ".join(
            p
            for p in [
                ORIGENS.get(bruto["origem"], bruto["origem"]),
                bruto["categoria"],
                CONCELHO,
            ]
            if p
        ),
        "descricao": factos.get("Localização", ""),
        "valor": bruto["valor"],
        "data_fim": bruto["data_fim"] or factos.get("Venda", "?"),
        "rotulo_data": "Termina em",
        "local": factos.get("Localização", CONCELHO),
        "url": link_origem or bruto["url"],
        "coordenadas": None,
        "extra": extra,
    }

    # Este anúncio também chega pela fonte direta do e-leiloes (só no Mac, que o
    # GitHub não lhe consegue aceder). Marca-se para não haver aviso em dobro.
    if bruto["origem"] == "eleiloes":
        item["duplica_de"] = {"fonte": "eleiloes", "id": bruto["referencia"]}
    return item


def recolher(registar=print):
    """Devolve a lista de itens normalizados do concelho nesta fonte."""
    sopa = obter(CONCELHO_URL)

    titulo = _texto(sopa.find("title"))
    if normalizar(CONCELHO) not in normalizar(titulo):
        raise ScrapeError(
            "A página do concelho tem o título '%s', que não fala de %s."
            % (titulo, CONCELHO)
        )

    cartoes = _cartoes(sopa)
    if not cartoes and SEM_RESULTADOS not in normalizar(_texto(sopa.find("main"))):
        raise ScrapeError(
            "Nem anúncios (ul.listings li.listing) nem a mensagem de lista vazia — "
            "o site mudou outra vez."
        )

    brutos = [_do_cartao(c) for c in cartoes]
    total = _paginas(sopa)
    for pagina in range(2, min(total, MAX_PAGINAS) + 1):
        seguinte = obter("%s?pagina=%d" % (CONCELHO_URL, pagina))
        novos = _cartoes(seguinte)
        if not novos:
            break
        brutos.extend(_do_cartao(c) for c in novos)

    itens = []
    for bruto in brutos:
        factos, link = _detalhe(bruto["url"])
        itens.append(_normalizado(bruto, factos, link))

    registar("[%s] %d anúncios em %s." % (ETIQUETA, len(itens), CONCELHO))
    return itens

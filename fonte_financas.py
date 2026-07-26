"""
Fonte: pesquisabenspenhorados.com — vendas de bens penhorados das Finanças.

Deteção
-------
A página do distrito de Viana do Castelo lista os 10 concelhos. Os concelhos
SEM registos aparecem como texto simples (<li>Paredes De Coura</li>); os que
TÊM registos aparecem como link (<li><a href="...municipalityId=XXXX">…</a></li>).

O municipalityId NUNCA é fixo nem adivinhado: é sempre lido do link detetado.
O site ignora IDs inválidos e devolve outro concelho, por isso confirma-se ainda
que o <h1> da página de destino é mesmo o concelho certo.
"""

import re
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from comum import (
    CONCELHO,
    HEADERS,
    TIMEOUT,
    ScrapeError,
    chave,
    normalizar,
)

NOME = "financas"
ETIQUETA = "Finanças"

BASE = "https://www.pesquisabenspenhorados.com/leiloes-vendas-financas/"
DISTRITO_URL = BASE + "DirectorySearch.aspx?viewType=1&districtId=174"  # Viana do Castelo
MAX_PAGINAS = 25  # travão de segurança

CAMPOS = {
    "localizacao": "localizacao",
    "no leilao financas": "numero",
    "valor base": "valor",
    "data venda": "data_venda",
    "data indexacao": "data_indexacao",
}


def obter(url, tolerar_404=False):
    resposta = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if tolerar_404 and resposta.status_code == 404:
        return None  # página além da última: o site devolve 404, não uma lista vazia
    resposta.raise_for_status()
    resposta.encoding = "utf-8"  # o site declara utf-8; não deixar o requests adivinhar
    return BeautifulSoup(resposta.text, "html.parser")


def procurar_concelho(sopa):
    """
    Devolve o URL da listagem do concelho, ou None se estiver como texto simples.
    Levanta ScrapeError se o concelho nem sequer aparecer na página.
    """
    lista = sopa.find(id="ctl00_body_seeByMunicipalityDiv") or sopa.find(
        class_="link-table"
    )
    if lista is None:
        raise ScrapeError(
            "Não encontrei o bloco de concelhos na página do distrito "
            "(esperava #ctl00_body_seeByMunicipalityDiv ou .link-table)."
        )

    itens = lista.find_all("li")
    if not itens:
        raise ScrapeError("Bloco de concelhos encontrado mas sem <li> lá dentro.")

    alvo = normalizar(CONCELHO)
    for li in itens:
        if normalizar(li.get_text()) != alvo:
            continue
        ligacao = li.find("a", href=True)
        if ligacao is None:
            return None  # texto simples => sem registos
        return urljoin(BASE, ligacao["href"])

    raise ScrapeError(
        "'%s' não aparece na lista de concelhos. Encontrados: %s"
        % (CONCELHO, ", ".join(li.get_text(strip=True) for li in itens))
    )


def _valor_do_campo(etiqueta):
    """
    O site escreve <b>Valor Base:</b>&nbsp;742,55&nbsp;€ — o valor é o texto do
    contentor menos o texto da própria etiqueta.
    """
    contentor = etiqueta.parent
    texto = contentor.get_text(" ", strip=True)
    texto = texto.replace(etiqueta.get_text(" ", strip=True), "", 1)
    texto = texto.replace("\xa0", " ").replace(">>>", "")
    return re.sub(r"\s+", " ", texto).strip(" :")


def _id_do_link(href):
    """ID estável a partir de detalheVenda.action?idVenda=1&sf=2321&ano=2023."""
    params = parse_qs(urlparse(href).query)
    try:
        return "%s.%s.%s" % (params["sf"][0], params["ano"][0], params["idVenda"][0])
    except (KeyError, IndexError):
        return None


def _contentor_do_item(etiqueta):
    """
    Sobe a partir do <b>N.º Leilão Finanças:</b> até à <div class="row"> que já
    contém o item completo (localização + valor + data de venda).
    """
    for ancestral in etiqueta.parents:
        if ancestral.name != "div":
            continue
        if "row" not in (ancestral.get("class") or []):
            continue
        texto = normalizar(ancestral.get_text(" ", strip=True))
        if "valor base" in texto and "data venda" in texto and "localizacao" in texto:
            return ancestral
    return None


def extrair_itens(sopa):
    itens = []
    for etiqueta in sopa.find_all("b"):
        if chave(etiqueta.get_text()) != "no leilao financas":
            continue

        contentor = _contentor_do_item(etiqueta)
        if contentor is None:
            raise ScrapeError(
                "Encontrei 'N.º Leilão Finanças' mas não consegui isolar o bloco do item."
            )

        ligacao = contentor.find("a", href=lambda h: h and "detalheVenda.action" in h)
        if ligacao is None:
            raise ScrapeError("Item sem link detalheVenda.action.")

        url = urljoin(BASE, ligacao["href"])
        bruto = {"id": _id_do_link(url) or _valor_do_campo(etiqueta), "url": url}

        for negrito in contentor.find_all("b"):
            campo = CAMPOS.get(chave(negrito.get_text()))
            if campo:
                bruto[campo] = _valor_do_campo(negrito)

        # A descrição é o bloco destacado (col-sm-12) no topo do item.
        descricao = contentor.find("div", class_=lambda c: c and "col-sm-12" in c)
        bruto["descricao"] = (
            re.sub(r"\s+", " ", descricao.get_text(" ", strip=True))
            if descricao
            else ""
        )
        itens.append(bruto)
    return itens


def total_de_registos(sopa):
    """Lê 'Resultados 1 - 10 de 16.' -> 16. Devolve None se não existir."""
    div = sopa.find(id="ctl00_body_numberOfRecordsInformationDiv")
    if div is None:
        return None
    encontrado = re.search(r"de\s+(\d+)", div.get_text())
    return int(encontrado.group(1)) if encontrado else None


def listar_todos(url_concelho, validar_titulo=True):
    """Percorre todas as páginas (&page=N) e devolve (itens_brutos, total_anunciado)."""
    sopa = obter(url_concelho)

    titulo = sopa.find("h1")
    if (
        validar_titulo
        and titulo
        and normalizar(titulo.get_text()) != normalizar(CONCELHO)
    ):
        raise ScrapeError(
            "O link levou a '%s' e não a '%s' — o site trocou o concelho."
            % (titulo.get_text(strip=True), CONCELHO)
        )

    total = total_de_registos(sopa)
    itens = extrair_itens(sopa)

    if total is not None and total > 0 and not itens:
        raise ScrapeError(
            "O site anuncia %d registos mas não extraí nenhum — os seletores mudaram."
            % total
        )

    pagina = 1
    while total is not None and len(itens) < total and pagina < MAX_PAGINAS:
        pagina += 1
        separador = "&" if "?" in url_concelho else "?"
        sopa_seguinte = obter(
            "%s%spage=%d" % (url_concelho, separador, pagina), tolerar_404=True
        )
        if sopa_seguinte is None:
            break
        seguinte = extrair_itens(sopa_seguinte)
        if not seguinte:
            break
        itens.extend(seguinte)

    vistos, unicos = set(), []
    for item in itens:
        if item["id"] not in vistos:
            vistos.add(item["id"])
            unicos.append(item)
    return unicos, total


def _normalizado(bruto):
    return {
        "fonte": NOME,
        "id": bruto["id"],
        "titulo": "Leilão n.º %s" % bruto.get("numero", bruto["id"]),
        "descricao": bruto.get("descricao", ""),
        "valor": bruto.get("valor", "?"),
        "data_fim": bruto.get("data_venda", "?"),
        "rotulo_data": "Data da venda",
        "local": bruto.get("localizacao", CONCELHO),
        "url": bruto["url"],
        "extra": [],
    }


def recolher(registar=print):
    """Devolve a lista de itens normalizados do concelho nesta fonte."""
    registar("[%s] a verificar a página do distrito..." % ETIQUETA)
    url_concelho = procurar_concelho(obter(DISTRITO_URL))

    if url_concelho is None:
        registar("[%s] %s está como texto simples — sem registos." % (ETIQUETA, CONCELHO))
        return []

    registar("[%s] %s está como LINK: %s" % (ETIQUETA, CONCELHO, url_concelho))
    brutos, total = listar_todos(url_concelho)
    registar("[%s] %d itens (o site anuncia %s)." % (ETIQUETA, len(brutos), total))
    return [_normalizado(b) for b in brutos]

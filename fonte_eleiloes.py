"""
Fonte: e-leiloes.pt — leilões e negócios particulares de execuções judiciais
(Ordem dos Solicitadores e dos Agentes de Execução).

É aqui que aparecem casas e terrenos; as Finanças raramente têm imóveis.

O site é uma SPA em Vue com uma API JSON pública (sem autenticação):

  GET /api/EventosMapa/?tableParams=<json>  -> TODOS os eventos do país de uma vez
  GET /api/Eventos/<referencia>/            -> detalhe de um evento

Nota: /api/Eventos/?tableParams=... existe mas pagina a 12 e ignora os filtros
no formato óbvio, por isso usa-se o endpoint do mapa e filtra-se aqui.
"""

import json
from urllib.parse import quote

import requests

from comum import (
    CONCELHO,
    HEADERS,
    TIMEOUT,
    ScrapeError,
    data_iso,
    euros,
    normalizar,
)

NOME = "eleiloes"
ETIQUETA = "e-leiloes.pt"

API = "https://www.e-leiloes.pt/api/"
EVENTO_URL = "https://www.e-leiloes.pt/evento/%s"

# Se puseres True, só avisa de imóveis (tipoId 1) e ignora veículos, máquinas,
# direitos, etc. Por omissão avisa de tudo o que houver no concelho: o volume em
# Paredes de Coura é baixíssimo (2 eventos em julho de 2026) e mais vale ver a
# mais do que perder uma casa por estar mal classificada.
SO_IMOVEIS = False

MODALIDADES = {1: "Leilão online", 2: "Negócio particular"}


def obter_json(url):
    resposta = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resposta.raise_for_status()
    try:
        return resposta.json()
    except ValueError:
        raise ScrapeError("Resposta não-JSON de %s" % url)


def todos_os_eventos():
    """O endpoint do mapa devolve o país inteiro numa só resposta."""
    parametros = quote(json.dumps({"first": 0, "rows": 12, "filters": {}}))
    dados = obter_json(API + "EventosMapa/?tableParams=" + parametros)
    lista = dados.get("list")

    if not lista:
        raise ScrapeError("EventosMapa devolveu uma lista vazia — API mudou?")

    # Sanidade: se a API passasse a paginar, viriam poucos concelhos distintos.
    concelhos = {e.get("moradaConcelho") for e in lista if e.get("moradaConcelho")}
    if len(concelhos) < 20:
        raise ScrapeError(
            "EventosMapa devolveu só %d eventos em %d concelhos — parece estar a "
            "paginar, o filtro por concelho deixaria de ser fiável."
            % (len(lista), len(concelhos))
        )
    return lista


def detalhe(referencia):
    dados = obter_json(API + "Eventos/%s/" % referencia)
    return dados.get("item") or {}


def _normalizado(evento, pormenor):
    referencia = evento.get("referencia")
    tipo = pormenor.get("tipo") or ""
    subtipo = pormenor.get("subtipo") or ""
    tipologia = pormenor.get("tipologia") or ""

    titulo = pormenor.get("titulo") or evento.get("titulo") or referencia
    if subtipo:
        titulo = "%s — %s" % (subtipo, titulo)

    morada = " ".join(
        parte
        for parte in [
            pormenor.get("morada") or evento.get("morada"),
            str(pormenor.get("moradaNumero") or evento.get("moradaNumero") or ""),
        ]
        if parte
    ).strip()
    local = ", ".join(
        parte
        for parte in [morada, pormenor.get("moradaFreguesia"), CONCELHO]
        if parte
    )

    extra = []
    if tipo:
        extra.append(("Tipo", " / ".join(p for p in [tipo, subtipo] if p)))
    if tipologia and normalizar(tipologia) != "nao aplicavel":
        extra.append(("Tipologia", tipologia))
    extra.append(("Modalidade", MODALIDADES.get(evento.get("modalidadeId"), "?")))
    if pormenor.get("valorMinimo"):
        extra.append(("Valor mínimo", euros(pormenor["valorMinimo"])))
    if evento.get("lanceAtual"):
        extra.append(("Lance atual", euros(evento["lanceAtual"])))
    if pormenor.get("areaTotal"):
        extra.append(("Área", "%s m²" % pormenor["areaTotal"]))
    if pormenor.get("processoNumero"):
        extra.append(("Processo", pormenor["processoNumero"]))

    return {
        "fonte": NOME,
        "id": referencia,
        "titulo": titulo,
        "descricao": pormenor.get("descricao") or "",
        "valor": euros(pormenor.get("valorBase") or evento.get("valorBase")),
        "data_fim": data_iso(pormenor.get("dataFim") or evento.get("dataFim")),
        "rotulo_data": "Termina em",
        "local": local,
        "url": EVENTO_URL % referencia,
        "extra": extra,
    }


def recolher(registar=print):
    """Devolve a lista de itens normalizados do concelho nesta fonte."""
    registar("[%s] a obter o catálogo nacional..." % ETIQUETA)
    eventos = todos_os_eventos()

    alvo = normalizar(CONCELHO)
    no_concelho = [
        e for e in eventos if normalizar(e.get("moradaConcelho")) == alvo
    ]
    registar(
        "[%s] %d eventos no país, %d em %s."
        % (ETIQUETA, len(eventos), len(no_concelho), CONCELHO)
    )

    if SO_IMOVEIS:
        no_concelho = [e for e in no_concelho if e.get("tipoId") == 1]
        registar("[%s] %d são imóveis (SO_IMOVEIS=True)." % (ETIQUETA, len(no_concelho)))

    itens = []
    for evento in no_concelho:
        referencia = evento.get("referencia")
        if not referencia:
            raise ScrapeError("Evento sem 'referencia': %s" % evento)
        itens.append(_normalizado(evento, detalhe(referencia)))
    return itens

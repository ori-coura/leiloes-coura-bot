"""
Fonte: Portal Citius — "Venda de Bens Penhorados em Processos Executivos".

É o registo oficial das vendas judiciais e cobre modalidades que o e-leiloes.pt
não mostra: venda por negociação particular, carta fechada, adjudicação. Foi
assim que se descobriu (05/08/2026) um terreno em Formariz, Paredes de Coura,
vendido por negociação particular — nunca teria aparecido nas outras fontes.

Três armadilhas que custaram a descobrir:

1. Sem marcar "Ignorar Datas" (`chkDatas=on`) a pesquisa devolve sempre 0.
2. A listagem trunca a descrição, e o concelho costuma ficar do lado cortado.
   Tem de se abrir o detalhe de cada registo, em ConsultasVenda.aspx/GetHtmlDetails
   com {"htmlId": N} — repare-se que o parâmetro é `htmlId` e não `id`.
3. O filtro é por TRIBUNAL, que é onde corre o processo e não onde está o bem.
   O terreno de Formariz estava no Juízo Central Cível de Viana do Castelo.
   Por isso varrem-se os dez tribunais da comarca e procura-se o concelho no texto.

Varre-se só a comarca de Viana do Castelo e só o estado "Em venda" — cerca de 95
registos, contra 3655 em venda no país inteiro. Um imóvel em Paredes de Coura
corre nesta comarca; varrer o país todo seria abusar de um site do Estado.
"""

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from bs4 import BeautifulSoup

from comum import CONCELHO, SESSAO, TIMEOUT, ScrapeError, normalizar

NOME = "citius"
ETIQUETA = "Citius"

BASE = "https://www.citius.mj.pt/portal/consultas/"
URL = BASE + "consultasvenda.aspx"
DETALHE = BASE + "ConsultasVenda.aspx/GetHtmlDetails"
P = "ctl00$ContentPlaceHolder1$"

EM_VENDA = "927"
MAX_PAGINAS = 40

# Os dez tribunais da comarca de Viana do Castelo.
TRIBUNAIS = {
    "2871842": "Arcos de Valdevez",
    "2871850": "Caminha",
    "2871854": "Melgaço",
    "2871858": "Monção",
    "3994085": "Paredes de Coura",
    "2871846": "Ponte da Barca",
    "2871862": "Ponte de Lima",
    "2871867": "Valença",
    "2871821": "Viana do Castelo",
    "2871872": "Vila Nova de Cerveira",
}

# "Paredes de Coura" é a prova; as freguesias servem de rede para descrições que
# só nomeiem o lugar. Só se incluem nomes pouco comuns noutros concelhos — por
# isso ficam de fora Ferreira, Parada, Cunha, Castanheira, Linhares e Resende.
FREGUESIAS = [
    "rubiaes", "vascoes", "romarigaes", "cossourado", "insalde",
    "agualonga", "padornelo", "mozelos", "formariz", "infesta", "porreiras",
]

CAMPOS = ["Tipo de Bem", "Estado", "Valor Base", "Modalidade", "Espécie", "Processo"]


def _ocultos(html):
    sopa = BeautifulSoup(html, "html.parser")
    return {
        i["name"]: i.get("value", "")
        for i in sopa.find_all("input", {"type": "hidden"})
        if i.get("name")
    }


def _base_do_pedido(tribunal):
    return {
        P + "ddlTribunais": tribunal,
        P + "ddlTiposBem": "0",
        P + "ddlModalidades": "0",
        P + "ddlEstados": EM_VENDA,
        P + "txtCalendarDesde": "01-01-2000",
        P + "txtCalendarAte": "31-12-2030",
        P + "chkDatas": "on",  # Ignorar Datas — sem isto vem sempre 0
    }


def _registos_da_pagina(html):
    """Cada registo é uma <div class="resultadopubvenda">."""
    sopa = BeautifulSoup(html, "html.parser")
    fora = []
    for div in sopa.find_all("div", class_="resultadopubvenda"):
        ligacao = div.find("a", onclick=lambda o: o and "Viewer.Abrir" in o)
        if not ligacao:
            continue
        encontrado = re.search(r"Viewer\.Abrir\([^,]*,\s*(\d+)", ligacao["onclick"])
        if not encontrado:
            continue
        texto = re.sub(r"\s+", " ", div.get_text(" ", strip=True))
        campos = {}
        for i, nome in enumerate(CAMPOS):
            a_seguir = CAMPOS[i + 1] if i + 1 < len(CAMPOS) else "ver mais"
            m = re.search(
                re.escape(nome) + r":\s*(.*?)\s*(?:" + re.escape(a_seguir) + r":|ver mais)",
                texto,
            )
            if m:
                campos[nome] = m.group(1).strip()
        campos["htmlId"] = encontrado.group(1)
        fora.append(campos)
    return fora


def _do_tribunal(tribunal):
    sessao = SESSAO
    html = sessao.get(URL, timeout=TIMEOUT).text
    dados = _ocultos(html)
    dados.update(_base_do_pedido(tribunal))
    dados[P + "btnSearch"] = "Pesquisar"
    html = sessao.post(URL, data=dados, timeout=TIMEOUT * 2).text

    anunciado = re.search(r"Numero de Registos:\s*(\d+)", html)
    total = int(anunciado.group(1)) if anunciado else 0
    registos = _registos_da_pagina(html)

    if total and not registos:
        raise ScrapeError(
            "O Citius anuncia %d registos no tribunal %s mas não extraí nenhum."
            % (total, TRIBUNAIS.get(tribunal, tribunal))
        )

    vistos = {r["htmlId"] for r in registos}
    pagina = 1
    while len(vistos) < total and pagina < MAX_PAGINAS and "Pager2_lnkNext" in html:
        pagina += 1
        dados = _ocultos(html)
        dados.update(_base_do_pedido(tribunal))
        dados["__EVENTTARGET"] = P + "Pager2$lnkNext"
        dados["__EVENTARGUMENT"] = ""
        html = sessao.post(URL, data=dados, timeout=TIMEOUT * 2).text
        novos = [r for r in _registos_da_pagina(html) if r["htmlId"] not in vistos]
        if not novos:
            break
        registos.extend(novos)
        vistos.update(r["htmlId"] for r in novos)
    return registos


def _detalhe(html_id):
    resposta = SESSAO.post(DETALHE, json={"htmlId": int(html_id)}, timeout=TIMEOUT)
    resposta.raise_for_status()
    bruto = (resposta.json() or {}).get("d") or ""
    limpo = re.sub(r"<[^>]+>", " ", bruto).replace("&#160;", " ").replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", limpo).strip()


def _e_do_concelho(texto):
    n = normalizar(texto)
    if normalizar(CONCELHO) in n:
        return True
    return any(re.search(r"\b%s\b" % f, n) for f in FREGUESIAS)


def _normalizado(registo, texto):
    descricao = ""
    m = re.search(r"Descrição do Bem:\s*(.*?)(?:\s*Intervenientes|$)", texto)
    if m:
        descricao = m.group(1).strip()

    extra = []
    for rotulo in ("Estado", "Modalidade", "Espécie", "Processo"):
        if registo.get(rotulo):
            extra.append((rotulo, registo[rotulo]))

    agente = re.search(
        r"Agente de Execução[^:]*:\s*Nome:\s*(.*?)\s*Morada:", texto
    ) or re.search(r"Encarregado da Venda\s*Nome:\s*(.*?)\s*Morada:", texto)
    if agente:
        extra.append(("Agente de execução", agente.group(1).strip()))
    contacto = re.search(r"Email:\s*([\w.@-]+)", texto)
    if contacto:
        extra.append(("Contacto", contacto.group(1)))

    tipo = registo.get("Tipo de Bem", "Bem")
    return {
        "fonte": NOME,
        "id": "citius-%s" % registo["htmlId"],
        "titulo": "%s — %s" % (tipo, descricao[:70] or registo["htmlId"]),
        "resumo": " · ".join(
            p for p in [tipo, registo.get("Modalidade"), CONCELHO] if p
        ),
        "descricao": descricao,
        "valor": registo.get("Valor Base", "?"),
        # O Citius não publica data de venda; o que interessa é o estado.
        "data_fim": registo.get("Estado", "Em venda"),
        "rotulo_data": "Estado",
        "local": CONCELHO,
        "url": URL,
        "coordenadas": None,
        "extra": extra,
    }


def recolher(registar=print):
    """Devolve a lista de itens normalizados do concelho nesta fonte."""
    registos = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futuros = {executor.submit(_do_tribunal, t): t for t in TRIBUNAIS}
        for futuro in as_completed(futuros):
            registos.extend(futuro.result())

    itens = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futuros = {executor.submit(_detalhe, r["htmlId"]): r for r in registos}
        for futuro in as_completed(futuros):
            registo = futuros[futuro]
            try:
                texto = futuro.result()
            except Exception:
                continue  # um detalhe em falta não estraga a recolha
            if _e_do_concelho(texto):
                itens.append(_normalizado(registo, texto))

    registar(
        "[%s] %d vendas em curso na comarca, %d em %s."
        % (ETIQUETA, len(registos), len(itens), CONCELHO)
    )
    return itens

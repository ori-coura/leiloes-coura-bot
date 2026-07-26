#!/usr/bin/env python3
"""
Monitor de leilões/vendas de bens penhorados das Finanças em Paredes de Coura.

Fonte: pesquisabenspenhorados.com (agrega o Portal das Finanças).

Como funciona a deteção
-----------------------
A página do distrito de Viana do Castelo lista os 10 concelhos. Os concelhos
SEM registos aparecem como texto simples (<li>Paredes De Coura</li>); os que
TÊM registos aparecem como link (<li><a href="...municipalityId=XXXX">...</a></li>).

Por isso o municipalityId NUNCA é fixo nem adivinhado: é sempre lido do link
detetado na página do distrito. Se o concelho não estiver como link, não há
nada para ver e o script termina sem enviar email.
"""

import argparse
import json
import os
import re
import smtplib
import sys
import unicodedata
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib.parse import parse_qs, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# --- Configuração -----------------------------------------------------------

BASE = "https://www.pesquisabenspenhorados.com/leiloes-vendas-financas/"
DISTRITO_URL = BASE + "DirectorySearch.aspx?viewType=1&districtId=174"  # Viana do Castelo
CONCELHO = "Paredes De Coura"

SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")
TIMEOUT = 30
MAX_PAGINAS = 25  # travão de segurança

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-PT,pt;q=0.9",
}


class ScrapeError(RuntimeError):
    """A estrutura do site mudou — é preciso rever os seletores."""


# --- Utilitários ------------------------------------------------------------


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


def obter(url, tolerar_404=False):
    resposta = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    if tolerar_404 and resposta.status_code == 404:
        return None  # página além da última: o site devolve 404, não uma lista vazia
    resposta.raise_for_status()
    resposta.encoding = "utf-8"  # o site declara utf-8; não deixar o requests adivinhar
    return BeautifulSoup(resposta.text, "html.parser")


# --- Passo 1: o concelho está como link ou como texto simples? --------------


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


# --- Passo 2: extrair os itens da listagem ----------------------------------

CAMPOS = {
    "localizacao": "localizacao",
    "no leilao financas": "numero",
    "valor base": "valor",
    "data venda": "data_venda",
    "data indexacao": "data_indexacao",
}


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
    """Constrói um ID estável a partir de detalheVenda.action?idVenda=1&sf=2321&ano=2023."""
    params = parse_qs(urlparse(href).query)
    try:
        return "%s.%s.%s" % (
            params["sf"][0],
            params["ano"][0],
            params["idVenda"][0],
        )
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
        classes = ancestral.get("class") or []
        if "row" not in classes:
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

        ligacao = contentor.find(
            "a", href=lambda h: h and "detalheVenda.action" in h
        )
        if ligacao is None:
            raise ScrapeError("Item sem link detalheVenda.action.")

        url = urljoin(BASE, ligacao["href"])
        identificador = _id_do_link(url) or _valor_do_campo(etiqueta)

        item = {"id": identificador, "url": url}
        for negrito in contentor.find_all("b"):
            campo = CAMPOS.get(chave(negrito.get_text()))
            if campo:
                item[campo] = _valor_do_campo(negrito)

        # A descrição é o bloco destacado (col-sm-12) no topo do item.
        descricao = contentor.find(
            "div", class_=lambda c: c and "col-sm-12" in c
        )
        item["descricao"] = (
            re.sub(r"\s+", " ", descricao.get_text(" ", strip=True))
            if descricao
            else ""
        )
        itens.append(item)
    return itens


def total_de_registos(sopa):
    """Lê 'Resultados 1 - 10 de 16.' -> 16. Devolve None se não existir."""
    div = sopa.find(id="ctl00_body_numberOfRecordsInformationDiv")
    if div is None:
        return None
    encontrado = re.search(r"de\s+(\d+)", div.get_text())
    return int(encontrado.group(1)) if encontrado else None


def listar_todos(url_concelho, validar_titulo=True):
    """Percorre todas as páginas (&page=N) e devolve (itens, total_anunciado)."""
    sopa = obter(url_concelho)

    titulo = sopa.find("h1")
    if validar_titulo and titulo and normalizar(titulo.get_text()) != normalizar(
        CONCELHO
    ):
        # Salvaguarda: o site ignora municipalityId inválidos e devolve outro
        # concelho. Se isso acontecer, é melhor falhar do que avisar do concelho errado.
        raise ScrapeError(
            "O link levou a '%s' e não a '%s' — o site trocou o concelho."
            % (titulo.get_text(strip=True), CONCELHO)
        )

    total = total_de_registos(sopa)
    itens = extrair_itens(sopa)

    if total is not None and not itens and total > 0:
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

    # Deduplicar mantendo a ordem
    vistos, unicos = set(), []
    for item in itens:
        if item["id"] not in vistos:
            vistos.add(item["id"])
            unicos.append(item)
    return unicos, total


# --- Passo 3: estado (seen.json) --------------------------------------------


def ler_estado():
    if not os.path.exists(SEEN_FILE):
        return {"itens": {}}
    with open(SEEN_FILE, encoding="utf-8") as ficheiro:
        dados = json.load(ficheiro)
    dados.setdefault("itens", {})
    return dados


def gravar_estado(estado):
    estado["atualizado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(SEEN_FILE, "w", encoding="utf-8") as ficheiro:
        json.dump(estado, ficheiro, ensure_ascii=False, indent=2, sort_keys=True)
        ficheiro.write("\n")


# --- Passo 4: email ---------------------------------------------------------


def enviar_email(assunto, texto, html):
    utilizador = os.environ.get("EMAIL_USER")
    palavra_passe = os.environ.get("EMAIL_PASS")
    destino = os.environ.get("EMAIL_TO") or utilizador

    if not (utilizador and palavra_passe and destino):
        raise RuntimeError(
            "Faltam variáveis de ambiente EMAIL_USER / EMAIL_PASS / EMAIL_TO."
        )

    mensagem = EmailMessage()
    mensagem["Subject"] = assunto
    mensagem["From"] = utilizador
    mensagem["To"] = destino
    mensagem.set_content(texto)
    mensagem.add_alternative(html, subtype="html")

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=TIMEOUT) as servidor:
        servidor.login(utilizador, palavra_passe)
        servidor.send_message(mensagem)


def compor_email(novos):
    assunto = "%d novo(s) leilão(ões) em %s" % (len(novos), CONCELHO)

    linhas = ["Novos bens penhorados à venda em %s:" % CONCELHO, ""]
    blocos = []
    for item in novos:
        linhas += [
            "• N.º %s" % item.get("numero", item["id"]),
            "  %s" % item.get("descricao", "")[:400],
            "  Valor base: %s" % item.get("valor", "?"),
            "  Data da venda: %s" % item.get("data_venda", "?"),
            "  %s" % item["url"],
            "",
        ]
        blocos.append(
            """
            <div style="border:1px solid #ddd;border-radius:6px;padding:14px;margin-bottom:14px">
              <p style="margin:0 0 8px;font-size:15px">{descricao}</p>
              <p style="margin:0;color:#555;font-size:14px">
                <b>N.º Leilão:</b> {numero}<br>
                <b>Valor base:</b> {valor}<br>
                <b>Data da venda:</b> {data_venda}<br>
                <b>Local:</b> {localizacao}
              </p>
              <p style="margin:10px 0 0"><a href="{url}">Ver no Portal das Finanças &raquo;</a></p>
            </div>
            """.format(
                descricao=item.get("descricao", "(sem descrição)"),
                numero=item.get("numero", item["id"]),
                valor=item.get("valor", "?"),
                data_venda=item.get("data_venda", "?"),
                localizacao=item.get("localizacao", CONCELHO),
                url=item["url"],
            )
        )

    html = """<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif">
      <h2 style="margin:0 0 4px">{titulo}</h2>
      <p style="color:#666;margin:0 0 18px">Fonte: pesquisabenspenhorados.com (Portal das Finanças)</p>
      {blocos}
    </body></html>""".format(
        titulo=assunto, blocos="".join(blocos)
    )

    return assunto, "\n".join(linhas), html


# --- Principal --------------------------------------------------------------


def main():
    analisador = argparse.ArgumentParser(description=__doc__)
    analisador.add_argument(
        "--dry-run",
        action="store_true",
        help="mostra o que faria, sem enviar email nem gravar seen.json",
    )
    analisador.add_argument(
        "--init",
        action="store_true",
        help="marca tudo o que existe agora como visto, sem enviar email",
    )
    analisador.add_argument(
        "--url",
        help="testar o parser contra a listagem de outro concelho (salta a deteção)",
    )
    argumentos = analisador.parse_args()

    if argumentos.url:
        itens, total = listar_todos(argumentos.url, validar_titulo=False)
        print("Total anunciado: %s | itens extraídos: %d" % (total, len(itens)))
        for item in itens:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        return 0

    print("A verificar %s..." % DISTRITO_URL)
    url_concelho = procurar_concelho(obter(DISTRITO_URL))

    if url_concelho is None:
        print("%s aparece como texto simples — sem leilões." % CONCELHO)
        if not argumentos.dry_run:
            # Grava mesmo assim: o commit diário mantém o repositório "ativo" e
            # impede o GitHub de desativar o agendamento por 60 dias sem atividade.
            gravar_estado(ler_estado())
        return 0

    print("%s está como LINK: %s" % (CONCELHO, url_concelho))
    itens, total = listar_todos(url_concelho)
    print("Encontrados %d itens (o site anuncia %s)." % (len(itens), total))

    estado = ler_estado()
    novos = [item for item in itens if item["id"] not in estado["itens"]]

    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for item in itens:
        estado["itens"].setdefault(
            item["id"],
            {
                "visto_em": agora,
                "url": item["url"],
                "numero": item.get("numero"),
                "data_venda": item.get("data_venda"),
            },
        )

    if not novos:
        print("Nenhum leilão novo.")
        if not argumentos.dry_run:
            gravar_estado(estado)
        return 0

    print("%d leilão(ões) NOVO(S):" % len(novos))
    for item in novos:
        print("  - %s | %s" % (item["id"], item.get("descricao", "")[:80]))

    if argumentos.init:
        print("Modo --init: marcados como vistos, sem email.")
    elif argumentos.dry_run:
        assunto, texto, _ = compor_email(novos)
        print("\n--- email que seria enviado ---\n%s\n\n%s" % (assunto, texto))
        return 0
    else:
        assunto, texto, html = compor_email(novos)
        enviar_email(assunto, texto, html)
        print("Email enviado para %s." % (os.environ.get("EMAIL_TO") or os.environ.get("EMAIL_USER")))

    gravar_estado(estado)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ScrapeError as erro:
        # Falha estrutural: o site mudou. Sai com erro para o GitHub Actions avisar.
        print("ERRO DE SCRAPING: %s" % erro, file=sys.stderr)
        sys.exit(2)

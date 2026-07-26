#!/usr/bin/env python3
"""
Avisa por email quando aparece um novo leilão/venda de bens penhorados em
Paredes de Coura.

Avisa de duas coisas: leilões novos e alterações aos que já conhece
(sobretudo o lance atual e a data de fecho).

Fontes:
  • Finanças, via pesquisabenspenhorados.com  (fonte_financas.py)
  • e-leiloes.pt, execuções judiciais         (fonte_eleiloes.py)
  • Leilosoc, leiloeira privada               (fonte_leilosoc.py)

Cada fonte tem o seu espaço próprio no seen.json, para que os IDs não colidam.
"""

import argparse
import json
import os
import smtplib
import sys
from datetime import datetime, timezone
from email.message import EmailMessage

import fonte_eleiloes
import fonte_financas
import fonte_leilosoc
from comum import CONCELHO, TIMEOUT, ScrapeError

FONTES = [fonte_financas, fonte_eleiloes, fonte_leilosoc]

# Campos cuja mudança vale um aviso. O resto (descrição reformatada, morada
# corrigida) muda sem consequência prática e só daria ruído.
CAMPOS_VIGIADOS = [
    ("valor", "Valor base"),
    ("data_fim", "Data"),
    ("Lance atual", "Lance atual"),
    ("Valor mínimo", "Valor mínimo"),
    ("Licitação inicial", "Licitação inicial"),
    ("Modalidade", "Modalidade"),
]
SEEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "seen.json")


# --- Estado -----------------------------------------------------------------


def ler_estado():
    if not os.path.exists(SEEN_FILE):
        estado = {}
    else:
        with open(SEEN_FILE, encoding="utf-8") as ficheiro:
            estado = json.load(ficheiro)

    estado.setdefault("fontes", {})

    # Migração do formato antigo (só Finanças): {"itens": {...}}
    antigos = estado.pop("itens", None)
    if antigos:
        estado["fontes"].setdefault(fonte_financas.NOME, {"itens": {}})
        estado["fontes"][fonte_financas.NOME]["itens"].update(antigos)

    for modulo in FONTES:
        estado["fontes"].setdefault(modulo.NOME, {"itens": {}})
        estado["fontes"][modulo.NOME].setdefault("itens", {})
    return estado


def gravar_estado(estado):
    estado["atualizado_em"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with open(SEEN_FILE, "w", encoding="utf-8") as ficheiro:
        json.dump(estado, ficheiro, ensure_ascii=False, indent=2, sort_keys=True)
        ficheiro.write("\n")


# --- Email ------------------------------------------------------------------


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
    return destino


def _campos(item):
    """Achata o item para comparação: campos de topo + os pares de 'extra'."""
    valores = dict(item.get("extra") or [])
    valores["valor"] = item.get("valor")
    valores["data_fim"] = item.get("data_fim")
    return valores


def comparar(antigo, novo):
    """Devolve [(rótulo, antes, depois)] para os campos vigiados que mudaram."""
    antes, depois = _campos(antigo), _campos(novo)
    mudancas = []
    for chave, rotulo in CAMPOS_VIGIADOS:
        anterior, atual = antes.get(chave), depois.get(chave)
        if anterior != atual and (anterior or atual):
            mudancas.append((rotulo, anterior or "—", atual or "—"))
    return mudancas


def _etiqueta(nome_fonte):
    for modulo in FONTES:
        if modulo.NOME == nome_fonte:
            return modulo.ETIQUETA
    return nome_fonte


def _bloco_html(item, mudancas=None):
    detalhes = "".join(
        "<b>%s:</b> %s<br>" % (rotulo, valor) for rotulo, valor in item["extra"]
    )
    aviso = ""
    if mudancas:
        aviso = (
            '<div style="background:#fff6e0;border-radius:6px;padding:10px;margin:0 0 10px;font-size:14px">'
            + "".join(
                "<b>%s:</b> <s>%s</s> &rarr; <b>%s</b><br>" % (rotulo, antes, depois)
                for rotulo, antes, depois in mudancas
            )
            + "</div>"
        )
    return """
        <div style="border:1px solid #ddd;border-radius:6px;padding:14px;margin-bottom:14px">
          <p style="margin:0 0 6px;color:#888;font-size:12px;text-transform:uppercase">{fonte}</p>
          <p style="margin:0 0 8px;font-size:16px;font-weight:600">{titulo}</p>
          {aviso}
          <p style="margin:0 0 10px;font-size:14px">{descricao}</p>
          <p style="margin:0;color:#555;font-size:14px">
            <b>Valor base:</b> {valor}<br>
            <b>{rotulo_data}:</b> {data_fim}<br>
            {detalhes}
            <b>Local:</b> {local}
          </p>
          <p style="margin:10px 0 0"><a href="{url}">Ver anúncio &raquo;</a></p>
        </div>
        """.format(
        fonte=_etiqueta(item["fonte"]),
        titulo=item["titulo"],
        aviso=aviso,
        descricao=item["descricao"] or "(sem descrição)",
        valor=item["valor"],
        rotulo_data=item["rotulo_data"],
        data_fim=item["data_fim"],
        detalhes=detalhes,
        local=item["local"],
        url=item["url"],
    )


def _linhas_texto(item, mudancas=None):
    linhas = ["• [%s] %s" % (_etiqueta(item["fonte"]), item["titulo"])]
    if mudancas:
        for rotulo, antes, depois in mudancas:
            linhas.append("  %s: %s -> %s" % (rotulo, antes, depois))
    if item["descricao"]:
        linhas.append("  %s" % item["descricao"][:400])
    linhas.append("  Valor base: %s" % item["valor"])
    linhas.append("  %s: %s" % (item["rotulo_data"], item["data_fim"]))
    for rotulo, valor in item["extra"]:
        linhas.append("  %s: %s" % (rotulo, valor))
    linhas.append("  %s" % item["url"])
    linhas.append("")
    return linhas


def compor_email(novos, alterados):
    partes = []
    if novos:
        partes.append("%d novo%s" % (len(novos), "s" if len(novos) > 1 else ""))
    if alterados:
        partes.append(
            "%d alteraç%s" % (len(alterados), "ões" if len(alterados) > 1 else "ão")
        )
    assunto = "%s em %s" % (" e ".join(partes), CONCELHO)

    linhas, blocos = [], []

    if novos:
        linhas += ["NOVOS", ""]
        blocos.append('<h3 style="margin:0 0 10px">Novos</h3>')
        for item in novos:
            linhas += _linhas_texto(item)
            blocos.append(_bloco_html(item))

    if alterados:
        linhas += ["ALTERAÇÕES", ""]
        blocos.append('<h3 style="margin:22px 0 10px">Alterações</h3>')
        for item, mudancas in alterados:
            linhas += _linhas_texto(item, mudancas)
            blocos.append(_bloco_html(item, mudancas))

    html = """<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif">
      <h2 style="margin:0 0 4px">{assunto}</h2>
      <p style="color:#666;margin:0 0 18px">
        Fontes: Portal das Finanças, e-leiloes.pt e Leilosoc ·
        <a href="https://ori-coura.github.io/leiloes-coura-bot/">ver todos</a>
      </p>
      {blocos}
    </body></html>""".format(
        assunto=assunto, blocos="".join(blocos)
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
        "--testar-email",
        action="store_true",
        help="envia um email de teste e termina (para validar os secrets)",
    )
    analisador.add_argument(
        "--fonte",
        choices=[modulo.NOME for modulo in FONTES],
        help="correr só uma das fontes",
    )
    analisador.add_argument(
        "--url",
        help="testar o parser das Finanças contra a listagem de outro concelho",
    )
    argumentos = analisador.parse_args()

    if argumentos.testar_email:
        destino = enviar_email(
            "Teste do monitor de leilões de %s" % CONCELHO,
            "Se estás a ler isto, o envio por Gmail está a funcionar.\n\n"
            "A partir de agora só recebes email quando houver mesmo novidades ou\n"
            "alterações. A página com tudo está em\n"
            "https://ori-coura.github.io/leiloes-coura-bot/\n",
            '<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif">'
            "<h2>Teste do monitor de leilões</h2>"
            "<p>Se estás a ler isto, o envio por Gmail está a funcionar.</p>"
            "<p>A partir de agora só recebes email quando houver mesmo novidades ou "
            "alterações. A página com tudo está em "
            '<a href="https://ori-coura.github.io/leiloes-coura-bot/">'
            "ori-coura.github.io/leiloes-coura-bot</a>.</p></body></html>",
        )
        print("Email de teste enviado para %s." % destino)
        return 0

    if argumentos.url:
        itens, total = fonte_financas.listar_todos(argumentos.url, validar_titulo=False)
        print("Total anunciado: %s | itens extraídos: %d" % (total, len(itens)))
        for item in itens:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        return 0

    # O e-leiloes.pt filtra a porta 443 a IPs estrangeiros/datacenter, por isso é
    # inalcançável a partir do GitHub Actions (diagnosticado a 26/07/2026: DNS
    # resolve, TCP 443 não abre). O workflow salta-o com SALTAR_FONTES=eleiloes;
    # no Mac, com IP português, corre normalmente.
    saltar = {
        nome.strip()
        for nome in os.environ.get("SALTAR_FONTES", "").split(",")
        if nome.strip()
    }

    modulos = [
        modulo
        for modulo in FONTES
        if (argumentos.fonte is None or modulo.NOME == argumentos.fonte)
        and modulo.NOME not in saltar
    ]
    for nome in sorted(saltar):
        print("[%s] saltada (SALTAR_FONTES)" % nome)

    estado = ler_estado()
    novos, alterados = [], []
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    falhas = []
    for modulo in modulos:
        try:
            itens = modulo.recolher()
        except Exception as erro:
            # Uma fonte em baixo não pode calar as outras: regista-se e segue-se.
            print(
                "[%s] FALHOU: %s: %s" % (modulo.ETIQUETA, type(erro).__name__, erro),
                file=sys.stderr,
            )
            falhas.append((modulo.ETIQUETA, erro))
            continue

        estado["fontes"][modulo.NOME]["verificado_em"] = agora
        vistos = estado["fontes"][modulo.NOME]["itens"]
        ativos_agora = set()

        for item in itens:
            ativos_agora.add(item["id"])
            registo = vistos.get(item["id"])
            if registo is None:
                novos.append(item)
                registo = {"visto_em": agora}
                vistos[item["id"]] = registo
            elif registo.get("item"):
                mudancas = comparar(registo["item"], item)
                if mudancas:
                    alterados.append((item, mudancas))
            # O item é reescrito a cada passagem: o lance atual muda todos os dias.
            registo["item"] = item
            registo["ultima_vez_ativo"] = agora
            registo["ativo"] = True

        # O que já cá estava e deixou de aparecer na fonte passa a arquivo.
        for identificador, registo in vistos.items():
            if identificador not in ativos_agora:
                registo["ativo"] = False

    if not novos and not alterados:
        print("Nada de novo.")
        if falhas:
            if not argumentos.dry_run:
                gravar_estado(estado)
            print(
                "Fonte(s) em falha: %s" % ", ".join(e for e, _ in falhas),
                file=sys.stderr,
            )
            return 2
        if not argumentos.dry_run:
            # Grava mesmo assim: o commit diário mantém o repositório "ativo" e
            # impede o GitHub de desativar o agendamento por 60 dias sem atividade.
            gravar_estado(estado)
        return 0

    for item in novos:
        print("  NOVO      [%s] %s | %s" % (item["fonte"], item["id"], item["titulo"][:60]))
    for item, mudancas in alterados:
        print("  ALTERADO  [%s] %s | %s" % (item["fonte"], item["id"], item["titulo"][:60]))
        for rotulo, antes, depois in mudancas:
            print("            %s: %s -> %s" % (rotulo, antes, depois))

    if argumentos.init:
        print("Modo --init: marcados como vistos, sem email.")
    elif argumentos.dry_run:
        assunto, texto, _ = compor_email(novos, alterados)
        print("\n--- email que seria enviado ---\n%s\n\n%s" % (assunto, texto))
        return 0
    else:
        assunto, texto, html = compor_email(novos, alterados)
        destino = enviar_email(assunto, texto, html)
        print("Email enviado para %s." % destino)

    gravar_estado(estado)
    if falhas:
        print(
            "Terminado com %d fonte(s) em falha: %s"
            % (len(falhas), ", ".join(e for e, _ in falhas)),
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ScrapeError as erro:
        # Falha estrutural: a fonte mudou. Sai com erro para o GitHub Actions avisar.
        print("ERRO DE SCRAPING: %s" % erro, file=sys.stderr)
        sys.exit(2)

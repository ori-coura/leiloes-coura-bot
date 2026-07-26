#!/usr/bin/env python3
"""
Avisa por email quando aparece um novo leilão/venda de bens penhorados em
Paredes de Coura.

Fontes:
  • Finanças, via pesquisabenspenhorados.com  (fonte_financas.py)
  • e-leiloes.pt, execuções judiciais         (fonte_eleiloes.py)

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
from comum import CONCELHO, TIMEOUT, ScrapeError

FONTES = [fonte_financas, fonte_eleiloes]
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


def _etiqueta(nome_fonte):
    for modulo in FONTES:
        if modulo.NOME == nome_fonte:
            return modulo.ETIQUETA
    return nome_fonte


def compor_email(novos):
    plural = "s" if len(novos) > 1 else ""
    assunto = "%d novo%s em %s: %s" % (
        len(novos),
        plural,
        CONCELHO,
        ", ".join(sorted({item["titulo"].split(" — ")[0] for item in novos}))[:60],
    )

    linhas = ["Novidades em %s:" % CONCELHO, ""]
    blocos = []
    for item in novos:
        linhas.append("• [%s] %s" % (_etiqueta(item["fonte"]), item["titulo"]))
        if item["descricao"]:
            linhas.append("  %s" % item["descricao"][:400])
        linhas.append("  Valor base: %s" % item["valor"])
        linhas.append("  %s: %s" % (item["rotulo_data"], item["data_fim"]))
        for rotulo, valor in item["extra"]:
            linhas.append("  %s: %s" % (rotulo, valor))
        linhas.append("  %s" % item["url"])
        linhas.append("")

        detalhes = "".join(
            "<b>%s:</b> %s<br>" % (rotulo, valor) for rotulo, valor in item["extra"]
        )
        blocos.append(
            """
            <div style="border:1px solid #ddd;border-radius:6px;padding:14px;margin-bottom:14px">
              <p style="margin:0 0 6px;color:#888;font-size:12px;text-transform:uppercase">{fonte}</p>
              <p style="margin:0 0 8px;font-size:16px;font-weight:600">{titulo}</p>
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
                descricao=item["descricao"] or "(sem descrição)",
                valor=item["valor"],
                rotulo_data=item["rotulo_data"],
                data_fim=item["data_fim"],
                detalhes=detalhes,
                local=item["local"],
                url=item["url"],
            )
        )

    html = """<html><body style="font-family:-apple-system,Segoe UI,Arial,sans-serif">
      <h2 style="margin:0 0 4px">Novidades em {concelho}</h2>
      <p style="color:#666;margin:0 0 18px">Fontes: Portal das Finanças e e-leiloes.pt</p>
      {blocos}
    </body></html>""".format(
        concelho=CONCELHO, blocos="".join(blocos)
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
        "--fonte",
        choices=[modulo.NOME for modulo in FONTES],
        help="correr só uma das fontes",
    )
    analisador.add_argument(
        "--url",
        help="testar o parser das Finanças contra a listagem de outro concelho",
    )
    argumentos = analisador.parse_args()

    if argumentos.url:
        itens, total = fonte_financas.listar_todos(argumentos.url, validar_titulo=False)
        print("Total anunciado: %s | itens extraídos: %d" % (total, len(itens)))
        for item in itens:
            print(json.dumps(item, ensure_ascii=False, indent=2))
        return 0

    modulos = [
        modulo
        for modulo in FONTES
        if argumentos.fonte is None or modulo.NOME == argumentos.fonte
    ]

    estado = ler_estado()
    novos = []
    agora = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for modulo in modulos:
        itens = modulo.recolher()
        vistos = estado["fontes"][modulo.NOME]["itens"]
        ativos_agora = set()

        for item in itens:
            ativos_agora.add(item["id"])
            registo = vistos.get(item["id"])
            if registo is None:
                novos.append(item)
                registo = {"visto_em": agora}
                vistos[item["id"]] = registo
            # O item é reescrito a cada passagem: o lance atual muda todos os dias.
            registo["item"] = item
            registo["ultima_vez_ativo"] = agora
            registo["ativo"] = True

        # O que já cá estava e deixou de aparecer na fonte passa a arquivo.
        for identificador, registo in vistos.items():
            if identificador not in ativos_agora:
                registo["ativo"] = False

    if not novos:
        print("Nada de novo.")
        if not argumentos.dry_run:
            # Grava mesmo assim: o commit diário mantém o repositório "ativo" e
            # impede o GitHub de desativar o agendamento por 60 dias sem atividade.
            gravar_estado(estado)
        return 0

    print("%d novidade(s):" % len(novos))
    for item in novos:
        print("  - [%s] %s | %s" % (item["fonte"], item["id"], item["titulo"][:70]))

    if argumentos.init:
        print("Modo --init: marcados como vistos, sem email.")
    elif argumentos.dry_run:
        assunto, texto, _ = compor_email(novos)
        print("\n--- email que seria enviado ---\n%s\n\n%s" % (assunto, texto))
        return 0
    else:
        assunto, texto, html = compor_email(novos)
        destino = enviar_email(assunto, texto, html)
        print("Email enviado para %s." % destino)

    gravar_estado(estado)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except ScrapeError as erro:
        # Falha estrutural: a fonte mudou. Sai com erro para o GitHub Actions avisar.
        print("ERRO DE SCRAPING: %s" % erro, file=sys.stderr)
        sys.exit(2)

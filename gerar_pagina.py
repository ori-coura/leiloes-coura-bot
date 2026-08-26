#!/usr/bin/env python3
"""
Gera docs/index.html a partir do seen.json, para publicar no GitHub Pages.

Não vai à internet: usa só o que o monitor.py já recolheu e guardou.
"""

import html
import json
import os
from datetime import datetime, timezone

from comum import CONCELHO

RAIZ = os.path.dirname(os.path.abspath(__file__))
SEEN_FILE = os.path.join(RAIZ, "seen.json")
SAIDA = os.path.join(RAIZ, "docs", "index.html")

ETIQUETAS = {
    "financas": "Finanças",
    "eleiloes": "e-leiloes.pt",
    "leilosoc": "Leilosoc",
    "citius": "Citius",
}
MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()


def data_pt(texto):
    """'2026-08-05 11:00' -> ('5 ago 2026, 11:00', dias_restantes ou None)"""
    if not texto or texto == "?":
        return "?", None
    try:
        quando = datetime.strptime(texto[:16], "%Y-%m-%d %H:%M")
    except ValueError:
        try:
            quando = datetime.strptime(texto[:10], "%Y-%m-%d")
        except ValueError:
            return texto, None
    legivel = "%d %s %d, %02d:%02d" % (
        quando.day,
        MESES[quando.month - 1],
        quando.year,
        quando.hour,
        quando.minute,
    )
    dias = (quando.date() - datetime.now().date()).days
    return legivel, dias


def prazo(dias):
    if dias is None:
        return ""
    if dias < 0:
        return "terminado"
    if dias == 0:
        return "termina hoje"
    if dias == 1:
        return "falta 1 dia"
    return "faltam %d dias" % dias


def cartao(registo):
    item = registo.get("item") or {}
    escapar = lambda t: html.escape(str(t or ""))

    legivel, dias = data_pt(item.get("data_fim"))
    urgente = dias is not None and 0 <= dias <= 7

    extras = "".join(
        '<div class="linha"><span>%s</span><b>%s</b></div>'
        % (escapar(rotulo), escapar(valor))
        for rotulo, valor in item.get("extra", [])
    )

    mapa = ""
    if item.get("coordenadas"):
        mapa = (
            '<a class="botao secundario" target="_blank" rel="noopener" '
            'href="https://www.google.com/maps?q=%s">Ver no mapa</a>'
            % escapar(item["coordenadas"])
        )

    descricao = ""
    if item.get("descricao"):
        descricao = (
            "<details><summary>Descrição completa</summary><p>%s</p></details>"
            % escapar(item["descricao"])
        )

    return """
    <article class="cartao{classe_fecho}">
      <div class="etiquetas">
        <span class="etiqueta fonte-{fonte}">{fonte_nome}</span>
        <span class="etiqueta ref">{ref}</span>
        {etiqueta_prazo}
      </div>
      <h3>{titulo}</h3>
      <p class="resumo">{resumo}</p>
      <div class="valores">
        <div class="linha destaque"><span>Valor base</span><b>{valor}</b></div>
        {extras}
        <div class="linha"><span>{rotulo_data}</span><b>{data}</b></div>
        <div class="linha"><span>Local</span><b>{local}</b></div>
      </div>
      {descricao}
      <div class="acoes">
        <a class="botao" target="_blank" rel="noopener" href="{url}">Ver anúncio</a>
        {mapa}
      </div>
    </article>""".format(
        classe_fecho="" if registo.get("ativo") else " arquivado",
        fonte=escapar(item.get("fonte")),
        fonte_nome=escapar(ETIQUETAS.get(item.get("fonte"), item.get("fonte"))),
        ref=escapar(item.get("id")),
        etiqueta_prazo='<span class="etiqueta prazo">%s</span>' % prazo(dias)
        if urgente
        else "",
        titulo=escapar(item.get("titulo")),
        resumo=escapar(item.get("resumo")),
        valor=escapar(item.get("valor")),
        extras=extras,
        rotulo_data=escapar(item.get("rotulo_data", "Data")),
        data=escapar(legivel) + (" · %s" % prazo(dias) if dias is not None else ""),
        local=escapar(item.get("local")),
        descricao=descricao,
        url=escapar(item.get("url")),
        mapa=mapa,
    )


ESTILO = """
:root{color-scheme:light dark;--fundo:#f6f7f9;--cartao:#fff;--texto:#1a1c1f;
--suave:#666;--linha:#e3e6ea;--acento:#0b5cad;--urgente:#b3261e}
@media(prefers-color-scheme:dark){:root{--fundo:#14161a;--cartao:#1d2025;
--texto:#e8eaed;--suave:#9aa0a6;--linha:#2c3037;--acento:#7cb0ea;--urgente:#f2b8b5}}
*{box-sizing:border-box}
body{margin:0;padding:24px 16px 64px;background:var(--fundo);color:var(--texto);
font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}
.envolve{max-width:760px;margin:0 auto}
h1{font-size:26px;margin:0 0 4px}
.subtitulo{color:var(--suave);margin:0 0 28px;font-size:14px}
h2{font-size:15px;text-transform:uppercase;letter-spacing:.06em;color:var(--suave);
margin:36px 0 14px;font-weight:600}
.cartao{background:var(--cartao);border:1px solid var(--linha);border-radius:12px;
padding:18px;margin-bottom:16px}
.cartao.arquivado{opacity:.62}
.cartao h3{margin:8px 0 2px;font-size:19px;line-height:1.3}
.resumo{margin:0 0 14px;color:var(--suave);font-size:14px}
.etiquetas{display:flex;gap:6px;flex-wrap:wrap}
.etiqueta{font-size:11px;font-weight:600;padding:3px 8px;border-radius:20px;
background:var(--linha);color:var(--suave);text-transform:uppercase;letter-spacing:.04em}
.etiqueta.fonte-eleiloes{background:var(--acento);color:#fff}
.etiqueta.fonte-financas{background:#5b6470;color:#fff}
.etiqueta.fonte-leilosoc{background:#0f7a5a;color:#fff}
.etiqueta.fonte-citius{background:#7a3e9d;color:#fff}
.etiqueta.prazo{background:var(--urgente);color:#fff}
.valores{border-top:1px solid var(--linha);padding-top:10px}
.linha{display:flex;justify-content:space-between;gap:16px;padding:4px 0;font-size:14px}
.linha span{color:var(--suave);flex-shrink:0}
.linha b{text-align:right;font-weight:600}
.linha.destaque b{font-size:18px;color:var(--acento)}
details{margin-top:12px;font-size:14px}
summary{cursor:pointer;color:var(--acento);font-weight:600}
details p{color:var(--suave);margin:8px 0 0}
.acoes{display:flex;gap:8px;flex-wrap:wrap;margin-top:16px}
.botao{display:inline-block;padding:9px 16px;border-radius:8px;background:var(--acento);
color:#fff;text-decoration:none;font-size:14px;font-weight:600}
.botao.secundario{background:transparent;color:var(--acento);
border:1px solid var(--acento)}
.vazio{background:var(--cartao);border:1px dashed var(--linha);border-radius:12px;
padding:32px;text-align:center;color:var(--suave)}
footer{margin-top:44px;color:var(--suave);font-size:13px;text-align:center}
footer a{color:var(--acento)}
"""


def gerar():
    with open(SEEN_FILE, encoding="utf-8") as ficheiro:
        estado = json.load(ficheiro)

    registos = []
    for fonte in estado.get("fontes", {}).values():
        for registo in fonte.get("itens", {}).values():
            if registo.get("item"):
                registos.append(registo)

    def ordenar(registo):
        return registo["item"].get("data_fim") or ""

    ativos = sorted(
        [r for r in registos if r.get("ativo")], key=ordenar
    )
    arquivo = sorted(
        [r for r in registos if not r.get("ativo")], key=ordenar, reverse=True
    )

    if ativos:
        corpo = "".join(cartao(r) for r in ativos)
    else:
        corpo = (
            '<div class="vazio"><p><b>Nada em leilão neste momento.</b></p>'
            "<p>O robô verifica as quatro fontes todos os dias. Assim que aparecer "
            "alguma coisa em %s, aparece aqui e recebes email.</p></div>" % CONCELHO
        )

    if arquivo:
        corpo += "<h2>Arquivo</h2>" + "".join(cartao(r) for r in arquivo)

    estados_fonte = []
    for nome, etiqueta in ETIQUETAS.items():
        quando = (estado.get("fontes", {}).get(nome) or {}).get("verificado_em")
        if quando:
            legivel_fonte, dias = data_pt(quando.replace("T", " ")[:16])
            if dias is not None and dias <= -2:
                quando_txt = "%s (há %d dias)" % (legivel_fonte, -dias)
            else:
                quando_txt = legivel_fonte
        else:
            quando_txt = "ainda não verificada"
        estados_fonte.append("%s: %s" % (etiqueta, quando_txt))

    verificado = estado.get("atualizado_em", "")
    legivel, _ = data_pt(verificado.replace("T", " ")[:16])

    pagina = """<!doctype html>
<html lang="pt-PT">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex">
<title>Leilões e penhoras — {concelho}</title>
<style>{estilo}</style>
</head>
<body>
<div class="envolve">
  <h1>Leilões e penhoras em {concelho}</h1>
  <p class="subtitulo">{n_ativos} · última verificação: {verificado}</p>
  {corpo}
  <footer>
    <p style="margin:0 0 8px">{estados_fonte}</p>
    Fontes: <a href="https://www.pesquisabenspenhorados.com/leiloes-vendas-financas/">Portal das Finanças</a>,
    <a href="https://www.e-leiloes.pt/">e-leiloes.pt</a> e
    <a href="https://leilosoc.com/pt/category/5-imovel/">Leilosoc</a> e
    <a href="https://www.citius.mj.pt/portal/consultas/consultasvenda.aspx">Citius</a>.<br>
    Página gerada automaticamente. Confirma sempre os dados no anúncio original.
  </footer>
</div>
</body>
</html>
""".format(
        concelho=html.escape(CONCELHO),
        estilo=ESTILO,
        n_ativos="nada ativo"
        if not ativos
        else ("1 ativo" if len(ativos) == 1 else "%d ativos" % len(ativos)),
        verificado=html.escape(legivel or "?"),
        estados_fonte=html.escape(" · ".join(estados_fonte)),
        corpo=corpo,
    )

    os.makedirs(os.path.dirname(SAIDA), exist_ok=True)
    with open(SAIDA, "w", encoding="utf-8") as ficheiro:
        ficheiro.write(pagina)

    print(
        "Página gerada: %s (%d ativos, %d em arquivo)"
        % (SAIDA, len(ativos), len(arquivo))
    )


if __name__ == "__main__":
    gerar()

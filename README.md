# Monitor de leilões e penhoras — Paredes de Coura

Avisa por email quando aparece um novo leilão, venda ou negócio particular de
bens penhorados no concelho de **Paredes de Coura**. Objetivo: apanhar casas e
terrenos antes que passem despercebidos.

Duas fontes, um só email:

| Fonte                                                                                  | O que cobre                                       | Ficheiro             |
| -------------------------------------------------------------------------------------- | ------------------------------------------------- | -------------------- |
| [pesquisabenspenhorados.com](https://www.pesquisabenspenhorados.com/leiloes-vendas-financas/) | vendas das Finanças (agrega o Portal das Finanças) | `fonte_financas.py`  |
| [e-leiloes.pt](https://www.e-leiloes.pt/)                                                | execuções judiciais (OSAE) — é onde estão os imóveis | `fonte_eleiloes.py`  |

Cada fonte tem o seu espaço no `seen.json`, para os IDs não colidirem.

## A página

Além do email, o bot gera uma página com tudo o que já apareceu — um cartão por
leilão, com resumo, valores, prazo, link para o anúncio e para o mapa. Os que
fecham passam para o arquivo, no fundo.

**https://ori-coura.github.io/leiloes-coura-bot/**

O `gerar_pagina.py` não vai à internet: lê só o `seen.json` que o `monitor.py`
gravou. Por isso o estado guarda o item completo e não apenas o ID — os valores
(sobretudo o lance atual) mudam de dia para dia.

## Fonte 1 — Finanças

A [página do distrito de Viana do Castelo](https://www.pesquisabenspenhorados.com/leiloes-vendas-financas/DirectorySearch.aspx?viewType=1&districtId=174)
lista os 10 concelhos:

- concelho **sem** registos → texto simples: `<li>Paredes De Coura</li>`
- concelho **com** registos → link: `<li><a href="...viewType=3&municipalityId=XXXX">…</a></li>`

O script procura "Paredes De Coura" nessa lista (sem acentos, sem maiúsculas). Se
for texto simples, não há nada. Se for link, segue-o.

**O `municipalityId` nunca é fixo nem adivinhado** — é sempre lido do link. O site
ignora IDs inválidos e devolve outro concelho, por isso confirma-se ainda que o
`<h1>` da página de destino diz mesmo "Paredes De Coura".

Cada item é identificado por `sf.ano.idVenda` (do link `detalheVenda.action`), que
corresponde ao "N.º Leilão Finanças" mostrado no site. A paginação é `&page=N`, 10
por página, e devolve **404** para páginas além da última.

## Fonte 2 — e-leiloes.pt

SPA em Vue com uma API JSON pública, sem autenticação:

```
GET /api/EventosMapa/?tableParams={"first":0,"rows":12,"filters":{}}
GET /api/Eventos/<referencia>/
```

O primeiro devolve **todos os eventos do país numa só resposta** (3175 em julho de
2026) e filtra-se `moradaConcelho` localmente. O `/api/Eventos/?tableParams=…`
existe mas pagina a 12 e ignora os filtros no formato óbvio, por isso não se usa.

Atenção: aqui o concelho escreve-se "Paredes **de** Coura" (minúsculo), ao
contrário do agregador das Finanças. A comparação é feita sem acentos nem
maiúsculas, por isso tanto faz.

Por omissão avisa de **tudo** o que houver no concelho — não só imóveis. O volume
é baixíssimo (2 eventos em julho de 2026) e mais vale ver a mais do que perder uma
casa por estar mal classificada. Para restringir a imóveis, põe
`SO_IMOVEIS = True` em `fonte_eleiloes.py`.

Estado verificado em 26/07/2026: nas Finanças, Paredes de Coura sem registos; no
e-leiloes.pt, uma garagem (`LO1493402026`) e uma quota de sociedade
(`NP1227312026`). Nenhuma casa nem terreno.

## Configuração

### 1. Password de aplicação do Gmail

Com verificação em dois passos ativa na conta Google, cria uma password de
aplicação em <https://myaccount.google.com/apppasswords>. São 16 caracteres.
Não é a password normal do Gmail.

### 2. Secrets no GitHub

Em **Settings → Secrets and variables → Actions → New repository secret**:

| Secret       | Valor                                    |
| ------------ | ---------------------------------------- |
| `EMAIL_USER` | o teu endereço Gmail (remetente)         |
| `EMAIL_PASS` | a password de aplicação de 16 caracteres |
| `EMAIL_TO`   | o endereço que recebe os avisos          |

### 3. Correr

O workflow corre sozinho uma vez por dia (07:00 UTC). Para testar à mão:
**Actions → Monitor leilões Paredes de Coura → Run workflow**.

## Correr localmente

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python monitor.py --dry-run
```

Opções:

| Opção              | O que faz                                                            |
| ------------------ | -------------------------------------------------------------------- |
| `--dry-run`        | mostra o email que enviaria, sem enviar nem gravar `seen.json`        |
| `--init`           | marca tudo o que existe agora como visto, sem enviar email            |
| `--fonte <nome>`   | corre só `financas` ou só `eleiloes`                                  |
| `--url <URL>`      | testa o parser das Finanças contra a listagem de outro concelho       |

Para reconstruir a página a partir do estado já guardado:

```bash
.venv/bin/python gerar_pagina.py
```

Para enviar mesmo a partir do computador:

```bash
EMAIL_USER=... EMAIL_PASS=... EMAIL_TO=... .venv/bin/python monitor.py
```

## Se alguma fonte mudar

O script sai com código 2 e a mensagem `ERRO DE SCRAPING: …` quando a estrutura
deixa de bater certo: bloco de concelhos não encontrado, concelho ausente da lista,
o site anuncia N registos mas não se extrai nenhum, o link leva a outro concelho,
ou o `EventosMapa` passa a paginar (detetado por vir menos de 20 concelhos
distintos). Nesse caso o workflow falha e o GitHub avisa por email — é sinal de
rever o código, não de que não há leilões.

## Alternativa sem código

O e-leiloes.pt tem alertas nativos por email para utilizadores registados. Não
dispensa este bot (não cobre as Finanças), mas serve de rede de segurança.

## Fora do âmbito

- penhoras registadas na Conservatória do Registo Predial

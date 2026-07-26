# Monitor de leilões de bens penhorados — Paredes de Coura

Avisa por email quando aparece um novo leilão/venda de bens penhorados das Finanças
no concelho de **Paredes de Coura**.

Fonte: [pesquisabenspenhorados.com](https://www.pesquisabenspenhorados.com/leiloes-vendas-financas/),
que agrega o Portal das Finanças.

## Como funciona a deteção

A [página do distrito de Viana do Castelo](https://www.pesquisabenspenhorados.com/leiloes-vendas-financas/DirectorySearch.aspx?viewType=1&districtId=174)
lista os 10 concelhos:

- concelho **sem** registos → texto simples: `<li>Paredes De Coura</li>`
- concelho **com** registos → link: `<li><a href="...viewType=3&municipalityId=XXXX">…</a></li>`

O script procura "Paredes De Coura" nessa lista (comparação sem acentos e sem
maiúsculas). Se for texto simples, termina sem fazer nada. Se for link, segue-o.

**O `municipalityId` nunca é fixo nem adivinhado** — é sempre lido do link. O site
ignora IDs inválidos e devolve outro concelho, por isso o script ainda confirma que
o `<h1>` da página de destino diz mesmo "Paredes De Coura" antes de avisar seja do
que for.

Cada item é identificado por `sf.ano.idVenda` (extraído do link
`detalheVenda.action?idVenda=1&sf=2321&ano=2023`), que corresponde ao "N.º Leilão
Finanças" mostrado no site. Os IDs já avisados ficam em `seen.json`, para não
receberes o mesmo leilão duas vezes.

Estado verificado em 26/07/2026: Paredes de Coura aparece como texto simples
(sem registos). Ponte de Lima e Viana do Castelo estão como link.

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

| Opção         | O que faz                                                            |
| ------------- | -------------------------------------------------------------------- |
| `--dry-run`   | mostra o email que enviaria, sem enviar nem gravar `seen.json`        |
| `--init`      | marca tudo o que existe agora como visto, sem enviar email            |
| `--url <URL>` | testa o parser contra a listagem de outro concelho (salta a deteção)  |

Para enviar mesmo a partir do computador:

```bash
EMAIL_USER=... EMAIL_PASS=... EMAIL_TO=... .venv/bin/python monitor.py
```

## Se o site mudar

O script sai com código 2 e a mensagem `ERRO DE SCRAPING: …` quando a estrutura
deixa de bater certo (bloco de concelhos não encontrado, concelho ausente da lista,
o site anuncia N registos mas não se extrai nenhum, ou o link leva a outro concelho).
Nesse caso o workflow falha e o GitHub avisa por email — é sinal de rever os
seletores em `monitor.py`, não de que não há leilões.

## Fora do âmbito (por opção)

- e-leiloes.pt (leilões eletrónicos de execuções judiciais)
- penhoras registadas na Conservatória

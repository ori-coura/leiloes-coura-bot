#!/bin/bash
# Executa o monitor completo (as três fontes, incluindo o e-leiloes.pt, que só
# é alcançável a partir de um IP português) e publica o resultado.
#
# Chamado pelo agendamento em ~/Library/LaunchAgents/pt.coura.leiloes.plist,
# mas também se pode correr à mão:  ./correr.sh
set -uo pipefail

RAIZ="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$RAIZ" || exit 1

REGISTO="$RAIZ/correr.log"
exec >> "$REGISTO" 2>&1
echo "===== $(date '+%Y-%m-%d %H:%M:%S') ====="

# Os segredos do email vivem em .env e são lidos pelo próprio monitor.py
# (o shell não os consegue ler: a password do Google tem espaços).

# Partir sempre do que está publicado: o GitHub Actions também escreve o
# seen.json e a página, e trabalhar sobre uma cópia velha dá conflitos.
git rebase --abort 2>/dev/null
if git fetch --quiet origin main; then
  # Só se pode descartar o local quando o que está por commitar são os
  # ficheiros gerados. Havendo código por commitar, não se toca em nada.
  SUJOS="$(git status --porcelain | awk '{print $2}' | grep -v -E '^(seen\.json|docs/)' || true)"
  if [[ -z "$SUJOS" ]]; then
    git reset --hard --quiet origin/main
  else
    echo "AVISO: há ficheiros por commitar ($SUJOS); não sincronizo à força"
  fi
else
  echo "AVISO: não consegui contactar o remoto, sigo com o que tenho"
fi

"$RAIZ/.venv/bin/python" monitor.py
CODIGO=$?

"$RAIZ/.venv/bin/python" gerar_pagina.py

if [[ -n "$(git status --porcelain seen.json docs)" ]]; then
  # Commit primeiro: só depois se integra o que o GitHub Actions publicou.
  # O --autostash evita que outros ficheiros por commitar travem o rebase.
  git add seen.json docs
  git commit --quiet -m "Atualizar leilões e página (Mac) [skip ci]"

  if git push --quiet origin main 2>/dev/null; then
    echo "publicado"
  else
    # Corrida com o GitHub Actions: em ficheiros gerados fica a nossa versão,
    # que é a mais completa (é a única que traz o e-leiloes).
    echo "push rejeitado, a reconciliar..."
    if git pull --rebase -X ours --autostash --quiet origin main \
       && git push --quiet origin main; then
      echo "publicado à segunda"
    else
      git rebase --abort 2>/dev/null
      echo "ERRO: não consegui publicar; fica para a próxima execução"
    fi
  fi
else
  echo "sem alterações a publicar"
fi

# Manter o registo curto (últimas ~500 linhas).
tail -n 500 "$REGISTO" > "$REGISTO.tmp" && mv "$REGISTO.tmp" "$REGISTO"

exit $CODIGO

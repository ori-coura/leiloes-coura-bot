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

# Segredos do email, fora do repositório e fora do git.
if [[ -f "$RAIZ/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$RAIZ/.env"
  set +a
fi

"$RAIZ/.venv/bin/python" monitor.py
CODIGO=$?

"$RAIZ/.venv/bin/python" gerar_pagina.py

if [[ -n "$(git status --porcelain seen.json docs)" ]]; then
  # Commit primeiro: só depois se integra o que o GitHub Actions publicou.
  # O --autostash evita que outros ficheiros por commitar travem o rebase.
  git add seen.json docs
  git commit --quiet -m "Atualizar leilões e página (Mac) [skip ci]"
  git pull --rebase --autostash --quiet origin main \
    || echo "AVISO: git pull falhou, tento o push na mesma"
  git push --quiet origin main && echo "publicado" || echo "ERRO: push falhou"
else
  echo "sem alterações a publicar"
fi

# Manter o registo curto (últimas ~500 linhas).
tail -n 500 "$REGISTO" > "$REGISTO.tmp" && mv "$REGISTO.tmp" "$REGISTO"

exit $CODIGO

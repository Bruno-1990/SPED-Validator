#!/bin/bash
# Hook: commit n push com mensagem dinamica
PROMPT=$(jq -r '.prompt' 2>/dev/null)
if echo "$PROMPT" | grep -qi '^commit n push$'; then
    cd /mnt/c/Users/bmb19/OneDrive/Documentos/work/SPED
    git add -A
    STAT=$(git diff --cached --stat | tail -1 | sed 's/^ *//')
    FILES=$(git diff --cached --name-only | head -5 | xargs -I{} basename {} | paste -sd ', ')
    MSG="${STAT}: ${FILES}"
    if [ -z "$STAT" ]; then
        echo '{"systemMessage": "Nada para commitar."}'
        exit 0
    fi
    git commit -m "$MSG" && git push
    echo "{\"systemMessage\": \"Push: $MSG\"}"
fi

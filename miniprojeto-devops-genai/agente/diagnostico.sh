#!/usr/bin/env bash
# Diagnóstico por IA da falha da suíte do stub (miniprojeto DevOps + GenAI).
#
# Uso: diagnostico.sh <caminho-do-maven-test.log>
#
# Saídas em $DIAG_DIR (default ./diagnostico):
#   prompt-diagnostico.md   contexto coletado e sanitizado (sempre)
#   parecer-diagnostico.md  resposta do Claude (quando o claude CLI existe)
#
# O job NÃO falha quando o claude CLI não está disponível: o prompt fica
# como artefato e o parecer pode ser gerado localmente (ver README do
# miniprojeto). O resultado vai para o GITHUB_STEP_SUMMARY e, em evento de
# pull_request com token, como comentário no PR via gh api.
set -uo pipefail

LOG="${1:?uso: diagnostico.sh <caminho-do-maven-test.log>}"
AGENTE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIAG_DIR="${DIAG_DIR:-diagnostico}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"

mkdir -p "$DIAG_DIR"
PROMPT="$DIAG_DIR/prompt-diagnostico.md"
PARECER="$DIAG_DIR/parecer-diagnostico.md"
INSTRUCOES="$AGENTE_DIR/instrucoes-parecer.md"

# Não basta existir no PATH: no Windows "python" pode ser o alias da
# Microsoft Store, que só imprime um aviso e sai com erro.
PY=""
for candidato in python3 python py; do
    if command -v "$candidato" >/dev/null 2>&1 \
            && "$candidato" -c "import sys" >/dev/null 2>&1; then
        PY="$candidato"
        break
    fi
done
if [ -z "$PY" ]; then
    echo "erro: nenhum interpretador Python funcional no runner (necessário para coleta_contexto.py)" >&2
    exit 1
fi

# O artefato do job test traz o log e o diretório surefire-reports juntos.
SUREFIRE_DIR="$(find "$(dirname "$LOG")" -type d -name surefire-reports 2>/dev/null | head -n 1)"

if ! "$PY" "$AGENTE_DIR/coleta_contexto.py" --log "$LOG" \
        ${SUREFIRE_DIR:+--surefire-dir "$SUREFIRE_DIR"} \
        --saida "$PROMPT"; then
    echo "erro: coleta de contexto falhou" >&2
    exit 1
fi

GERADO=false
if command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
    if "$CLAUDE_BIN" -p "$(cat "$INSTRUCOES")" < "$PROMPT" > "$PARECER" \
            2> "$DIAG_DIR/claude-stderr.log" && [ -s "$PARECER" ]; then
        GERADO=true
    else
        echo "aviso: o claude CLI falhou (ver $DIAG_DIR/claude-stderr.log); usando o fallback." >&2
        rm -f "$PARECER"
    fi
else
    echo "aviso: claude CLI não disponível no runner; usando o fallback." >&2
fi

resumo() {
    if [ "$GERADO" = true ]; then
        echo "## 🤖 Diagnóstico por IA (job ai-diagnosis)"
        echo
        cat "$PARECER"
    else
        echo "## 🤖 Diagnóstico por IA — pendente (claude CLI indisponível)"
        echo
        echo "O contexto coletado e sanitizado está no artefato"
        echo "\`diagnostico/prompt-diagnostico.md\`. Gere o parecer localmente com:"
        echo
        echo '```bash'
        echo 'claude -p "$(cat miniprojeto-devops-genai/agente/instrucoes-parecer.md)" \'
        echo '    < prompt-diagnostico.md > parecer-diagnostico.md'
        echo '```'
    fi
}

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    resumo >> "$GITHUB_STEP_SUMMARY"
else
    resumo
fi

# Comentário no PR: só quando houve parecer, em evento de PR e com token.
if [ "$GERADO" = true ] && [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ] \
        && [ -n "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ]; then
    PR_NUMBER=""
    if command -v jq >/dev/null 2>&1 && [ -f "${GITHUB_EVENT_PATH:-/nao-existe}" ]; then
        PR_NUMBER="$(jq -r '.pull_request.number // empty' "$GITHUB_EVENT_PATH")"
    fi
    if [ -n "$PR_NUMBER" ] && command -v gh >/dev/null 2>&1; then
        # limite de 65536 chars no corpo de comentário do GitHub
        CORPO="$(printf '### 🤖 Diagnóstico por IA (job ai-diagnosis)\n\n%s' "$(head -c 60000 "$PARECER")")"
        if ! gh api "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" \
                -f body="$CORPO" >/dev/null; then
            echo "aviso: não foi possível comentar no PR (gh api falhou)." >&2
        fi
    else
        echo "aviso: número do PR ou gh CLI indisponível; comentário não publicado." >&2
    fi
fi

exit 0

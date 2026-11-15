#!/usr/bin/env bash
# Diagnóstico por IA da falha da suíte do stub (miniprojeto DevOps + GenAI).
#
# Uso: diagnostico.sh <caminho-do-maven-test.log>
#
# Cadeia de motores:
#   a. GROQ_API_KEY presente  -> API do Groq (endpoint OpenAI-compatible)
#   b. claude CLI disponível  -> uso local
#   c. nenhum dos dois        -> fallback: prompts viram artefato e o summary
#                                explica como gerar o parecer localmente
#
# Gera DOIS pareceres por execução de falha:
#   parecer-sem-contexto.md  prompt padrão
#   parecer-com-contexto.md  prompt + docs/lacunas.md + docs/decisoes.md,
#                            com a seção "## Relação com decisões documentadas"
#
# Saídas em $DIAG_DIR (default ./diagnostico). O resultado vai para o
# GITHUB_STEP_SUMMARY e, em pull_request com token, como UM comentário no PR.
#
# Variáveis de ajuste (defaults pensados para o free tier do Groq, que
# limita tokens por minuto):
#   MODEL_GROQ              modelo (default openai/gpt-oss-120b)
#   ORCAMENTO_PROMPT_BYTES  orçamento do prompt-diagnostico.md (default 16000)
#   MAX_BYTES_ANEXO         limite de cada doc anexado (default 8000)
#   MAX_TOKENS_PARECER      max_tokens da resposta (default 2048)
#   PAUSA_ENTRE_CHAMADAS    segundos entre os dois pareceres (default 60)
#   GROQ_TIMEOUT            --max-time do curl (default 120)
#   GROQ_RETRY_ESPERA       espera antes da única retentativa em 429 (default 70)
#
# Segurança: a chave NUNCA é ecoada (sem set -x, sem dump de headers); o
# conteúdo enviado é o prompt já sanitizado pela coleta_contexto.py.
set -uo pipefail

LOG="${1:?uso: diagnostico.sh <caminho-do-maven-test.log>}"
AGENTE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DIAG_DIR="${DIAG_DIR:-diagnostico}"
CLAUDE_BIN="${CLAUDE_BIN:-claude}"
export MODEL_GROQ="${MODEL_GROQ:-openai/gpt-oss-120b}"
ORCAMENTO_PROMPT_BYTES="${ORCAMENTO_PROMPT_BYTES:-16000}"
MAX_BYTES_ANEXO="${MAX_BYTES_ANEXO:-8000}"
PAUSA_ENTRE_CHAMADAS="${PAUSA_ENTRE_CHAMADAS:-60}"
GROQ_URL="https://api.groq.com/openai/v1/chat/completions"

mkdir -p "$DIAG_DIR"
PROMPT="$DIAG_DIR/prompt-diagnostico.md"
PROMPT_CTX="$DIAG_DIR/prompt-com-contexto.md"
INSTRUCOES="$AGENTE_DIR/instrucoes-parecer.md"
INSTRUCOES_CTX="$DIAG_DIR/instrucoes-com-contexto.md"
PARECER_SEM="$DIAG_DIR/parecer-sem-contexto.md"
PARECER_COM="$DIAG_DIR/parecer-com-contexto.md"

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Em Windows o stdout do Python usa cp1252 e quebra com caracteres como
# "→" nos docs; força UTF-8 em todas as chamadas auxiliares.
export PYTHONIOENCODING=utf-8

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

# ---------------------------------------------------------------- coleta ---

# O artefato do job test traz o log e o diretório surefire-reports juntos.
SUREFIRE_DIR="$(find "$(dirname "$LOG")" -type d -name surefire-reports 2>/dev/null | head -n 1)"

if ! "$PY" "$AGENTE_DIR/coleta_contexto.py" --log "$LOG" \
        ${SUREFIRE_DIR:+--surefire-dir "$SUREFIRE_DIR"} \
        --orcamento-bytes "$ORCAMENTO_PROMPT_BYTES" \
        --saida "$PROMPT"; then
    echo "erro: coleta de contexto falhou" >&2
    exit 1
fi

# Anexo sanitizado e truncado de um doc do repositório (reusa as máscaras
# da coleta — o prompt com contexto também vai para um provedor externo).
anexo_sanitizado() {
    local arquivo="$1"
    if [ -f "$arquivo" ]; then
        "$PY" -c '
import sys
sys.path.insert(0, sys.argv[2])
import coleta_contexto as cc
texto = open(sys.argv[1], encoding="utf-8", errors="replace").read()
sys.stdout.write(cc.sanitizar(cc.truncar(texto, int(sys.argv[3]), sys.argv[1])))
' "$arquivo" "$AGENTE_DIR" "$MAX_BYTES_ANEXO"
    else
        echo "_(arquivo $arquivo não encontrado no checkout)_"
    fi
}

{
    cat "$INSTRUCOES"
    cat <<'FIM'

Seção adicional obrigatória, ao final da resposta:

## Relação com decisões documentadas

Relacione a correção sugerida com as lacunas (docs/lacunas.md) e decisões
(docs/decisoes.md) anexadas ao contexto. Se a correção interagir com LC12
ou LC13, diga explicitamente qual pergunta o time precisa responder antes
de aplicá-la.
FIM
} > "$INSTRUCOES_CTX"

{
    cat "$PROMPT"
    echo
    echo "## 4. Anexo: lacunas documentadas (docs/lacunas.md)"
    echo
    anexo_sanitizado "$REPO_ROOT/docs/lacunas.md"
    echo
    echo "## 5. Anexo: decisões documentadas (docs/decisoes.md)"
    echo
    anexo_sanitizado "$REPO_ROOT/docs/decisoes.md"
} > "$PROMPT_CTX"

# ---------------------------------------------------------------- motores ---

# Chamada ao Groq. Nunca ecoa a chave nem headers: sem set -x, sem --verbose,
# e em erro só imprime o código HTTP e o campo error.message do corpo.
chamar_groq() { # $1 instruções (system)  $2 prompt (user)  $3 saída
    local payload="$DIAG_DIR/.payload.json"
    local resposta="$DIAG_DIR/.resposta.json"
    local codigo

    "$PY" -c '
import json, os, sys
with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
    system = f.read()
with open(sys.argv[2], encoding="utf-8", errors="replace") as f:
    user = f.read()
with open(sys.argv[3], "w", encoding="utf-8") as f:
    json.dump({
        "model": os.environ["MODEL_GROQ"],
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "max_tokens": int(os.environ.get("MAX_TOKENS_PARECER", "2048")),
    }, f)
' "$1" "$2" "$payload" || return 1

    _curl_groq() {
        curl -sS --max-time "${GROQ_TIMEOUT:-120}" \
            -o "$resposta" -w '%{http_code}' \
            -H "Authorization: Bearer ${GROQ_API_KEY}" \
            -H "Content-Type: application/json" \
            -d @"$payload" \
            "$GROQ_URL" 2>/dev/null
    }

    codigo="$(_curl_groq)" || codigo="000"
    if [ "$codigo" = "429" ]; then
        echo "aviso: Groq respondeu 429 (rate limit do free tier); nova tentativa única em ${GROQ_RETRY_ESPERA:-70}s." >&2
        sleep "${GROQ_RETRY_ESPERA:-70}"
        codigo="$(_curl_groq)" || codigo="000"
    fi

    if [ "$codigo" = "200" ]; then
        if "$PY" -c '
import json, sys
with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
    dados = json.load(f)
sys.stdout.write(dados["choices"][0]["message"]["content"])
' "$resposta" > "$3" && [ -s "$3" ]; then
            rm -f "$payload" "$resposta"
            return 0
        fi
        echo "aviso: resposta 200 do Groq sem conteúdo utilizável." >&2
    else
        local mensagem=""
        [ -s "$resposta" ] && mensagem="$("$PY" -c '
import json, sys
try:
    with open(sys.argv[1], encoding="utf-8", errors="replace") as f:
        print(json.load(f).get("error", {}).get("message", ""))
except Exception:
    pass
' "$resposta" 2>/dev/null)"
        echo "aviso: chamada ao Groq falhou (HTTP ${codigo})${mensagem:+ — ${mensagem}}." >&2
    fi
    rm -f "$payload" "$resposta"
    return 1
}

chamar_claude() { # $1 instruções  $2 prompt  $3 saída
    if "$CLAUDE_BIN" -p "$(cat "$1")" < "$2" > "$3" \
            2> "$DIAG_DIR/claude-stderr.log" && [ -s "$3" ]; then
        return 0
    fi
    echo "aviso: o claude CLI falhou (ver $DIAG_DIR/claude-stderr.log)." >&2
    rm -f "$3"
    return 1
}

MOTOR=""
if [ -n "${GROQ_API_KEY:-}" ]; then
    MOTOR="groq"
elif command -v "$CLAUDE_BIN" >/dev/null 2>&1; then
    MOTOR="claude"
else
    echo "aviso: nem GROQ_API_KEY nem claude CLI disponíveis; usando o fallback." >&2
fi

gerar_parecer() { # $1 instruções  $2 prompt  $3 saída
    case "$MOTOR" in
        groq)   chamar_groq "$1" "$2" "$3" ;;
        claude) chamar_claude "$1" "$2" "$3" ;;
        *)      return 1 ;;
    esac
}

GERADOS=0
if [ -n "$MOTOR" ]; then
    echo "gerando parecer-sem-contexto.md via ${MOTOR}..."
    gerar_parecer "$INSTRUCOES" "$PROMPT" "$PARECER_SEM" && GERADOS=$((GERADOS + 1))

    if [ "$MOTOR" = "groq" ]; then
        echo "pausa de ${PAUSA_ENTRE_CHAMADAS}s entre as chamadas (rate limit do free tier)..."
        sleep "$PAUSA_ENTRE_CHAMADAS"
    fi

    echo "gerando parecer-com-contexto.md via ${MOTOR}..."
    gerar_parecer "$INSTRUCOES_CTX" "$PROMPT_CTX" "$PARECER_COM" && GERADOS=$((GERADOS + 1))
fi

# ------------------------------------------------------------- publicação ---

resumo() {
    if [ "$GERADOS" -gt 0 ]; then
        echo "## 🤖 Diagnóstico automático (GenAI) — análise sujeita a revisão humana"
        echo
        if [ -s "$PARECER_SEM" ]; then
            echo "### Parecer 1 — sem contexto de decisões"
            echo
            cat "$PARECER_SEM"
            echo
        else
            echo "_(parecer sem contexto não foi gerado; ver log do job)_"
            echo
        fi
        if [ -s "$PARECER_COM" ]; then
            echo "### Parecer 2 — com contexto de decisões (docs/lacunas.md + docs/decisoes.md)"
            echo
            cat "$PARECER_COM"
        else
            echo "_(parecer com contexto não foi gerado; ver log do job)_"
        fi
    else
        echo "## 🤖 Diagnóstico por IA — pendente (nenhum motor disponível ou chamada falhou)"
        echo
        echo "Os prompts coletados e sanitizados estão no artefato \`diagnostico\`"
        echo "(\`prompt-diagnostico.md\` e \`prompt-com-contexto.md\`, com"
        echo "\`instrucoes-com-contexto.md\`). Gere os pareceres localmente com:"
        echo
        echo '```bash'
        echo 'claude -p "$(cat miniprojeto-devops-genai/agente/instrucoes-parecer.md)" \'
        echo '    < prompt-diagnostico.md > parecer-sem-contexto.md'
        echo 'claude -p "$(cat instrucoes-com-contexto.md)" \'
        echo '    < prompt-com-contexto.md > parecer-com-contexto.md'
        echo '```'
    fi
}

if [ -n "${GITHUB_STEP_SUMMARY:-}" ]; then
    resumo >> "$GITHUB_STEP_SUMMARY"
else
    resumo
fi

# Comentário no PR: um único comentário com os dois pareceres.
if [ "$GERADOS" -gt 0 ] && [ "${GITHUB_EVENT_NAME:-}" = "pull_request" ] \
        && [ -n "${GH_TOKEN:-${GITHUB_TOKEN:-}}" ]; then
    PR_NUMBER=""
    if command -v jq >/dev/null 2>&1 && [ -f "${GITHUB_EVENT_PATH:-/nao-existe}" ]; then
        PR_NUMBER="$(jq -r '.pull_request.number // empty' "$GITHUB_EVENT_PATH")"
    fi
    if [ -n "$PR_NUMBER" ] && command -v gh >/dev/null 2>&1; then
        COMENTARIO="$DIAG_DIR/.comentario.md"
        resumo > "$COMENTARIO"
        # limite de 65536 chars no corpo de comentário do GitHub
        if ! gh api "repos/${GITHUB_REPOSITORY}/issues/${PR_NUMBER}/comments" \
                -f body="$(head -c 60000 "$COMENTARIO")" >/dev/null; then
            echo "aviso: não foi possível comentar no PR (gh api falhou)." >&2
        fi
        rm -f "$COMENTARIO"
    else
        echo "aviso: número do PR ou gh CLI indisponível; comentário não publicado." >&2
    fi
fi

exit 0

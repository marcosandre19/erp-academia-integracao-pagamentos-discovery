# Miniprojeto — DevOps com GenAI

## Objetivo

Integrar um agente de GenAI a um pipeline de CI/CD: quando a suíte de testes
do stub de integração de pagamentos (`forum-testes-integracao/stub/`) falha,
um job de diagnóstico por IA analisa o log do Maven e produz um parecer sobre a causa provável.

## Estrutura

```
.github/workflows/devops-genai.yml   # pipeline GitHub Actions (test + ai-diagnosis)
miniprojeto-devops-genai/
├── README.md                        # este arquivo
├── .gitlab-ci.yml                   # equivalente GitLab CI (demonstrativo — o lab oficial é GitLab)
└── agente/
    ├── coleta_contexto.py           # monta e SANITIZA o prompt-diagnostico.md
    ├── instrucoes-parecer.md        # instruções fixas do agente (formato + regras)
    └── diagnostico.sh               # orquestra: coleta → claude -p → summary/PR
```

## Como funciona

- **Job `test`**: JDK 17 (Temurin) + cache Maven; roda
  `mvn -f forum-testes-integracao/stub/pom.xml test` com `tee` + `set -o pipefail`
  (o exit code do Maven reprova o job) e publica `maven-test.log` e os
  relatórios surefire como artefato **sempre** (`if: always()`).
- **Injeção de falha**: `EVENT_REGISTRY_MODE=deferred` é exportado no job
  `test` quando (a) `workflow_dispatch` com input `inject_bug=true`, ou
  (b) `pull_request` cujo PR tem a label **`inject-bug`** (o gatilho inclui
  `labeled`/`unlabeled`, então colocar/tirar a label já dispara nova
  execução). Caso contrário, `sync` (padrão). Ver seção abaixo.
- **Job `ai-diagnosis`**: só roda em falha (`if: failure()` / `when: on_failure`),
  baixa o artefato do log e chama `agente/diagnostico.sh` (detalhes na seção
  "Agente de diagnóstico" abaixo). O diretório `diagnostico/` (prompt e, se
  gerado, parecer) é publicado como artefato.

## Injeção de falha (`inject_bug` → `EVENT_REGISTRY_MODE=deferred`)

Para exercitar o job `ai-diagnosis` com uma falha realista, o stub lê a
config `EVENT_REGISTRY_MODE` (variável de ambiente, ou system property
`-DEVENT_REGISTRY_MODE=...` — o Surefire repassa ambas ao JVM dos testes):

- **`sync` (padrão, ou valor ausente/qualquer outro)**: comportamento
  normal — o webhook registra o `idEvento` na própria requisição; todos os
  testes verdes.
- **`deferred`**: o registro do evento processado é "adiado" — na prática
  nunca acontece. A deduplicação para de funcionar e uma entrega duplicada
  do mesmo evento é reprocessada, produzindo efeito observável (baixa
  aplicada duas vezes muda a situação do aluno na API pública). Ficam
  vermelhos os testes que verificam idempotência pela API pública:
  - `cot.FalhasIntegracaoCotTest.f2_entregaDuplicadaNaoAlteraSituacaoObservadaPelaApiPublica`
  - `blackbox.FluxoPagamentoBlackboxTest.consultaAntesEDepoisDoWebhookComEntregaDuplicada`

  (Os testes que só verificam o `200` da reentrega — f1 e o blackbox do
  webhook — continuam verdes: a resposta HTTP não muda, só o efeito.)

O nome `INJECT_BUG`/`inject_bug` é voltado a quem dispara o pipeline e
existe **só no CI**, que o traduz para `EVENT_REGISTRY_MODE=deferred`. No
código o que aparece é uma opção de configuração plausível: um diagnóstico
justo precisa perceber que o modo "deferred" quebra a garantia de
idempotência — não achar um grep de "bug".

Uso local:

```bash
EVENT_REGISTRY_MODE=deferred mvn -f forum-testes-integracao/stub/pom.xml test
```

No GitHub Actions a falha vem do input `inject_bug` do `workflow_dispatch`
**ou** da label `inject-bug` aplicada ao PR (o gatilho de `pull_request`
inclui `labeled`/`unlabeled`); no GitLab CI, da variável `INJECT_BUG` de um
pipeline manual. Em todos os casos o job `test` exporta
`EVENT_REGISTRY_MODE` (`deferred` quando a injeção está ligada, senão `sync`).

A flag é lida uma única vez na construção do controller; a documentação do
seu propósito fica **apenas aqui**, de propósito: o diagnóstico por IA deve
encontrar a causa pelo log e pelo código, sem dica em comentário.

## Agente de diagnóstico

Dois scripts em `agente/`, chamados pelo job `ai-diagnosis`:

**`coleta_contexto.py`** monta `diagnostico/prompt-diagnostico.md` com, nesta
ordem:

1. o recorte das falhas do log do Maven (blocos `<<< FAILURE!` com stack
   trace + resumo `[ERROR] Failures:`) e os relatórios surefire das classes
   reprovadas — não o log inteiro;
2. o git diff do PR atual (contra `origin/$GITHUB_BASE_REF`); fora de PR,
   o working tree sujo ou o último commit;
3. o conteúdo dos arquivos-fonte citados nos stack traces **e** dos módulos
   do projeto relacionados a eles — imports e vizinhos de pacote (em Java,
   dependência do mesmo pacote não gera `import`), pois a causa-raiz pode
   não estar no traceback;
4. sanitização obrigatória antes de gravar: tokens e chaves (`sk-`,
   `glpat-`, `ghp_`, `AKIA`, JWT, `Bearer ...`, `Authorization:`,
   `password=` etc.), e-mails e caminhos de usuário (`/home/...`,
   `C:\Users\...`) são mascarados.

**`diagnostico.sh`** gera o parecer com esta cadeia de motores:

1. **Groq (caminho do CI)** — se `GROQ_API_KEY` está presente, chama o
   endpoint OpenAI-compatible `https://api.groq.com/openai/v1/chat/completions`
   via `curl`, com `instrucoes-parecer.md` como mensagem *system* e o
   prompt como *user*. Modelo em `MODEL_GROQ` (default
   **`openai/gpt-oss-120b`**), `max_tokens` 2048, timeout de 120s e, em
   HTTP 429, **uma** retentativa após espera (`GROQ_RETRY_ESPERA`, 70s).
   Em erro HTTP só o código e o `error.message` vão para o log — nunca a
   chave ou headers.
2. **claude CLI** — sem a chave, usa `claude -p` se existir (uso local).
3. **Fallback** — sem nenhum motor (ou se as chamadas falharem), **o job
   não falha**: os prompts sanitizados vão para o artefato `diagnostico` e
   o summary explica como gerar os pareceres localmente:

   ```bash
   # baixe o artefato "diagnostico" da execução reprovada e rode:
   claude -p "$(cat miniprojeto-devops-genai/agente/instrucoes-parecer.md)" \
       < prompt-diagnostico.md > parecer-sem-contexto.md
   claude -p "$(cat instrucoes-com-contexto.md)" \
       < prompt-com-contexto.md > parecer-com-contexto.md
   ```

As instruções fixas (`instrucoes-parecer.md`) exigem resposta nas seções
`## Resumo`, `## Evidências (citando linhas do log)`, `## Causa-raiz`,
`## Correção sugerida (diff mínimo)`, `## Como validar`, `## Riscos e
premissas`, `## Confiança (alta/média/baixa + por quê)`, com as regras:
não alterar/sugerir alterar testes para passarem (hipótese de teste errado
vai em Riscos); se a correção depender de decisão de negócio não tomada,
apontá-la e PARAR; não inventar números, SLAs ou comportamento não
evidenciado.

### Dois pareceres por execução

Cada falha gera **dois** pareceres (com pausa de `PAUSA_ENTRE_CHAMADAS`,
default 60s, entre as chamadas ao Groq, por causa do limite de tokens por
minuto do free tier):

- `parecer-sem-contexto.md` — prompt padrão;
- `parecer-com-contexto.md` — mesmo prompt + `docs/lacunas.md` e
  `docs/decisoes.md` anexados (sanitizados e truncados em
  `MAX_BYTES_ANEXO`, 8KB cada), com a seção adicional obrigatória
  **"## Relação com decisões documentadas"**: se a correção interage com
  LC12 (DLQ × registro de idempotência) ou LC13 (idempotência por evento
  ou por efeito), o parecer deve dizer qual pergunta o time precisa
  responder antes de aplicá-la.

Ambos vão para o artefato, para o `GITHUB_STEP_SUMMARY` e, quando o evento
é `pull_request`, como **um único comentário** no PR via `gh api` com o
`GITHUB_TOKEN`, truncado em 60K e identificado no topo como
"🤖 Diagnóstico automático (GenAI) — análise sujeita a revisão humana".

### Orçamento de tamanho do prompt

O free tier do Groq limita tokens por minuto, então a coleta aplica um
orçamento ao `prompt-diagnostico.md` (`ORCAMENTO_PROMPT_BYTES`, default
**16000 bytes**, ~4k tokens): excedido o limite, as seções são truncadas
com marcação explícita na ordem **fontes → diff → falhas por último** (o
recorte de falhas é o conteúdo mais crítico e cai por último).

### Segurança e LGPD (minimização)

- `GROQ_API_KEY` entra **somente** via secret (`Settings > Secrets` no
  GitHub; variável de CI/CD mascarada/protegida no GitLab) — nunca em
  arquivo versionado; o script não ecoa a chave nem headers no log.
- O envio ao Groq é um envio real a terceiro, então a **sanitização roda
  antes**: o prompt é gravado já mascarado pela `coleta_contexto.py`
  (segredos, e-mails, caminhos de usuário) e os anexos de `docs/` passam
  pelas mesmas máscaras antes de entrar no `prompt-com-contexto.md`.
- Minimização: vai para o provedor apenas o recorte de falhas, o diff e os
  fontes relacionados — nunca o log inteiro ou o repositório; os dados do
  stub são fictícios (sem PII de alunos reais), conforme a regra LGPD do
  projeto.

## Resultados

_(a preencher nas próximas etapas)_


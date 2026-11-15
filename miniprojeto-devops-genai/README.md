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
- **Input `inject_bug` / variável `INJECT_BUG`**: em `workflow_dispatch` vem
  do input `inject_bug` (default `false`); em `pull_request` é sempre `false`.
  O job traduz `true` para `EVENT_REGISTRY_MODE=deferred`, a config que o
  stub lê (ver seção abaixo).
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

No GitHub Actions a falha vem do input `inject_bug` do `workflow_dispatch`;
no GitLab CI, da variável `INJECT_BUG` de um pipeline manual — em ambos o
job `test` exporta `EVENT_REGISTRY_MODE` (`deferred` se `true`, senão `sync`).

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

**`diagnostico.sh`** envia o prompt ao Claude via `claude -p` (modo não
interativo), com as instruções fixas de `instrucoes-parecer.md` — resposta
obrigatoriamente nas seções `## Resumo`, `## Evidências (citando linhas do
log)`, `## Causa-raiz`, `## Correção sugerida (diff mínimo)`, `## Como
validar`, `## Riscos e premissas`, `## Confiança (alta/média/baixa + por
quê)`, e com as regras: não alterar/sugerir alterar testes para passarem
(hipótese de teste errado vai em Riscos); se a correção depender de decisão
de negócio não tomada, apontá-la e PARAR; não inventar números, SLAs ou
comportamento não evidenciado.

O parecer vai para o `GITHUB_STEP_SUMMARY` e, quando o evento é
`pull_request`, como comentário no PR via `gh api` com o `GITHUB_TOKEN`.

### Sem claude CLI no runner (caminho usado neste projeto)

Se o `claude` CLI não está disponível no runner, **o job não falha**: o
`prompt-diagnostico.md` é publicado no artefato `diagnostico` e o step
summary registra o aviso. O parecer é então gerado localmente — este é o
caminho adotado aqui, já que o runner não tem o CLI nem credenciais de API:

```bash
# baixe o artefato "diagnostico" da execução reprovada e rode:
claude -p "$(cat miniprojeto-devops-genai/agente/instrucoes-parecer.md)" \
    < prompt-diagnostico.md > parecer-diagnostico.md
```

## Resultados

_(a preencher nas próximas etapas)_

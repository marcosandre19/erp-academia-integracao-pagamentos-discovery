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
    └── diagnostico.sh               # (próxima etapa) script de diagnóstico por IA
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
  baixa o artefato do log e chama `agente/diagnostico.sh`.

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

## Resultados

_(a preencher nas próximas etapas)_

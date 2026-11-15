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
- **Variável `INJECT_BUG`**: em `workflow_dispatch` vem do input `inject_bug`
  (default `false`); em `pull_request` é sempre `false`.
- **Job `ai-diagnosis`**: só roda em falha (`if: failure()` / `when: on_failure`),
  baixa o artefato do log e chama `agente/diagnostico.sh`.

## Resultados

_(a preencher nas próximas etapas)_

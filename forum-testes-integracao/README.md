# Fórum — Testes de Integração com GenIA

Experimento do fórum: gerar testes de integração para o recorte
gateway → webhook → API pública usando dois prompts diferentes e
comparar os resultados.

## Estrutura

- [`prompts/`](prompts/) — os dois prompts usados:
  - [`prompt1-blackbox.md`](prompts/prompt1-blackbox.md) — caixa-preta
    puro, ancorado no contrato OpenAPI (gerou as suítes em
    `stub/src/test/java/blackbox/`).
  - [`prompt2-cot-falhas.md`](prompts/prompt2-cot-falhas.md) —
    Chain-of-Thought sobre modos de falha (gerou a suíte em
    `stub/src/test/java/cot/`).
- [`stub/`](stub/) — stub Spring Boot dos dois endpoints do contrato,
  com as suítes de teste geradas (ver [`stub/README.md`](stub/README.md)).
- [`metricas.md`](metricas.md) — **métricas de execução das suítes**:
  nº de testes gerados por prompt, executáveis de primeira, iterações
  de correção, taxa de sucesso e os cenários que só o prompt 2 trouxe
  (fora de ordem, assincronia pós-200, PII em erros, pendência I02).

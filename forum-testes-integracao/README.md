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

## Análise crítica — vícios na suíte do prompt 2

Caça dirigida a três classes de defeito em
`stub/src/test/java/cot/FalhasIntegracaoCotTest.java`, confrontando
cada teste com `openapi/erp-pagamentos.yaml` (a única fonte declarada
de comportamento esperado).

### 1. Teste viciado — oráculo vindo da própria API

- **F2 (`f2_entregaDuplicadaNaoAlteraSituacao...`)**: o valor esperado
  (`situacaoAposPrimeira`) é **extraído da própria API sob teste** e
  reusado como oráculo na asserção final. O teste só afirma "duas
  leituras iguais" — passa mesmo que o webhook não produza efeito
  nenhum (e, no stub, nunca produz: a situação é fixa). Ou seja, o
  teste é **verde trivial** e não consegue falhar para a violação de
  I01 que diz proteger. Um oráculo honesto exigiria valor esperado
  vindo do contrato ou de fixture externa, não de uma leitura prévia
  do sistema. (O mesmo padrão existe no prompt 1, em
  `FluxoPagamentoBlackboxTest` — o vício não é exclusivo do CoT.)
- **F4 (`f4_duzentosNoWebhookNaoGaranteSituacao...`)**: o esperado
  `"em_atraso"` vem da **tabela interna do stub** (`alu-00017`), não do
  contrato — o oráculo é o fixture da implementação que o teste
  deveria tratar como caixa-preta.

### 2. Números/valores inventados

- **`ALUNO_EM_ATRASO = "alu-00017"` e a string exata `"em_atraso"`**:
  não existem no contrato. O OpenAPI só traz `alu-00042` e `"em_dia"`
  como *examples*, e define `situacao` como **string livre, sem
  enumeração** (lacuna que o próprio prompt 1 respeitou, afirmando
  apenas presença do campo). Os valores vêm do README/código do stub —
  contradizendo o comentário do `CotTestBase`, que declara o contrato
  como "única fonte de comportamento esperado".
- Menor: `trx-cot-0001..0004` e os ids `evt-cot-*` são dados
  arbitrários aceitáveis (o contrato não restringe formato), mas nada
  os ancora nos *examples* do contrato.

### 3. Comportamento inventado para lacunas

- **F3 (fora de ordem)**: o payload do contrato **não tem timestamp
  nem número de sequência** — "emitidos na ordem 1 → 2" é narrativa
  sem representação observável; o que o teste realmente verifica é
  "dois eventos válidos distintos recebem 200", e o rótulo "fora de
  ordem" é inventado. Agrava: pelo Q3 do contrato,
  `(tipoEvento, idTransacao)` é chave de *fallback* de idempotência —
  os dois eventos da mesma `trx-cot-0003` poderiam ser legitimamente
  **deduplicados como o mesmo pagamento**, cenário que o teste não
  distingue do que afirma testar.
- **F4 (assincronia pós-200)**: o contrato (LC01/LC02) deixa
  **indefinido** quando a situação muda; logo após o 200, tanto
  `"em_atraso"` quanto situação já atualizada seriam conformes. O
  teste fixa um dos desfechos (`equalTo("em_atraso")`) — inventa
  determinismo exatamente sobre a lacuna que seu próprio comentário
  registra como PENDENTE. Contra uma implementação real assíncrona
  seria uma *race condition* (flaky); só é estável porque o stub nunca
  processa.
- **F2 (vínculo evento → aluno)**: o payload não carrega nenhuma
  referência ao aluno (lacuna registrada pelo prompt 1 no
  `FluxoPagamentoBlackboxTest`); observar `alu-00042` para "ver o
  efeito" de `trx-cot-0002` é um vínculo inventado.
- Leve — **F1 (timeout + retry)**: nome e comentário prometem "sem
  efeito duplicado", mas o teste só verifica as duas respostas 200; o
  efeito não é observado em lugar nenhum. O teste afirma menos do que
  anuncia.

**Contraponto**: F5 (PII) e o placeholder `@Disabled` de I02 são o
tratamento correto de lacuna — sentinelas fictícias num caso, pergunta
registrada em vez de comportamento inventado no outro.

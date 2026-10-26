# Métricas de execução — testes gerados pelos prompts 1 e 2

Execução em 26/10/2026 contra o stub (`stub/`), com Spring Boot subindo em porta
aleatória via `@SpringBootTest(RANDOM_PORT)` (JDK 25 / Maven 3.8.4).

## Resultado por suíte

| Suíte | Origem | Testes | Passou | Skipped |
|---|---|---|---|---|
| `blackbox.WebhookPagamentosBlackboxTest` | prompt 1 | 6 | 6 | 0 |
| `blackbox.SituacaoAlunoBlackboxTest` | prompt 1 | 4 | 4 | 0 |
| `blackbox.FluxoPagamentoBlackboxTest` | prompt 1 | 1 | 1 | 0 |
| `cot.FalhasIntegracaoCotTest` | prompt 2 (CoT) | 6 | 5 | 1 (`@Disabled`) |

## Métricas

- **Nº de testes gerados:** prompt 1 = 11; prompt 2 = 6 (5 executáveis + 1
  deliberadamente `@Disabled`). Total: 17.
- **Nº executáveis de primeira:** 16/16 dos habilitados — compilaram e rodaram
  sem nenhum ajuste no código dos testes. O único tropeço registrado foi de
  ambiente, não de código gerado: o `JAVA_HOME` padrão da máquina (JDK 8) não
  compila text blocks; com JDK 25 compila direto.
- **Nº que passou após 1 iteração de correção:** 0 correções foram
  necessárias — os 16 passaram na primeira execução, não houve iteração de
  conserto a medir.
- **Taxa de sucesso de execução:** 100% dos testes executados (16/16).
  Contando o `@Disabled` como não executável, 16/17 ≈ 94% — mas o disabled é
  intencional (pendência de contrato, não defeito).

## Cenários únicos do prompt 2 (CoT de modos de falha)

Quatro cenários só existem na suíte do prompt 2:

1. **Fora de ordem (F3)** — dois eventos da mesma transação entregues em ordem
   inversa à de emissão, ambos aceitos com 200 (I06: recebimento durável
   independe da ordem). Nenhuma suíte do prompt 1 toca nisso. Registra como
   PENDENTE qual situação final prevalece (o contrato só define
   `pagamento_confirmado`).
2. **Falha pós-200 / assincronia (F4)** — logo após o 200 do webhook, o aluno
   em atraso ainda consta `em_atraso`, e o teste afirma que isso é conforme o
   contrato (200 = recebimento durável, não processamento completo). O prompt 1
   chegou perto no `FluxoPagamentoBlackboxTest`, mas recusou-se a afirmar
   qualquer relação temporal; o prompt 2 transformou a assincronia em asserção
   positiva usando a fixture `ALUNO_EM_ATRASO`.
3. **PII em erros (F5 / LGPD)** — payload malformado com sentinelas de nome e
   CPF; o teste afirma que a resposta 400 não ecoa esses valores. Ausente no
   prompt 1.
4. **Efeitos independentes (I02)** — presente apenas como placeholder
   `@Disabled`, documentando que baixa financeira e liberação de acesso são
   independentes, com a pergunta que destrava ("qual recurso permite observar a
   baixa/DLQ num teste?"). O prompt 1 nem registrou o cenário.

**Sobreposição:** F1 (timeout + retry) e F2 (duplicata at-least-once) do
prompt 2 cobrem o mesmo terreno da idempotência já testada pelo prompt 1
(`entregaDuplicadaDoMesmoEventoRespondemOMesmo200` e o fluxo com reentrega) —
a diferença é a motivação narrada (timeout vs. at-least-once) e as fixtures
próprias (`ALUNO_EM_DIA`/`ALUNO_EM_ATRASO`).

## Conclusão

O prompt 2 não aumentou a taxa de sucesso (ambas 100%), mas trouxe 4 cenários
que o caixa-preta puro do prompt 1 não gerou: fora de ordem, semântica
assíncrona do 200, vazamento de PII e a pendência explícita de I02.

Você é um testador de integração sênior. Pense passo a passo sobre a
integração do webhook de pagamento descrita abaixo ANTES de escrever
qualquer teste.

Vamos pensar passo a passo:
1. Liste os modos de falha da integração gateway → endpoint de
   webhook → processamento → API pública (timeout, retry, eventos
   fora de ordem, entregas duplicadas).
2. Para cada modo de falha, defina o comportamento esperado do
   sistema com base APENAS nas regras fornecidas. Não invente regras
   nem números; o que não estiver definido, marque como PENDENTE com
   a pergunta que destravaria.
3. Gere os casos de teste em JUnit 5 + REST Assured, um por modo de
   falha, com os dados fictícios (payloads) que cada um precisa.
4. Para cada teste, declare em comentário qual regra de negócio ele
   protege.
5. testes devem ser gravados em @forum-testes-integracao/stub/src/test/java/cot

Regras do fluxo (invariantes do projeto):
- I01: o processamento do webhook é idempotente — reentrega nunca
  duplica efeito.
- I02: baixa financeira e liberação de acesso são efeitos
  independentes; falha de um não reverte o outro.
- I06: o 200 ao gateway significa recebimento durável, nunca
  processamento completo.
- PII de alunos nunca aparece em payloads de exemplo, logs ou
  mensagens de erro.

Especificação:
@openapi/erp-pagamentos.yaml
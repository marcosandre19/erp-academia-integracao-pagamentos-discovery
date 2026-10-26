Você é um engenheiro de testes sênior, especialista em testes
funcionais, testes de API REST e testes de integração.

Crie um conjunto de testes caixa-preta em JUnit 5 com REST Assured
para o fluxo de webhook de pagamento de um ERP de academias. Use a
documentação OpenAPI delimitada por ##### como especificação da
aplicação. O conjunto deve cobrir a especificação e todas as
respostas possíveis (códigos de status), incluindo:
- processamento bem-sucedido do webhook (200 no recebimento durável)
- entrega duplicada do webhook (mesmo ID de evento duas vezes →
  mesmo estado final, nenhum efeito duplicado)
- assinatura inválida (401) e payload malformado (400)
- consulta do parceiro na API pública antes e depois do processamento

Regras de negócio que DEVEM ser verificadas:
- o 200 devolvido ao gateway confirma recebimento durável, não o
  processamento completo
- reprocessar o mesmo ID de evento nunca duplica a baixa do pagamento

Restrições:
- Use apenas dados fictícios; nenhum dado pessoal real.
- Não invente SLAs, timeouts numéricos ou regras não fornecidas;
  registre como PENDENTE em comentário.
- Valores esperados vêm da especificação, nunca da resposta da
  própria API em outra chamada.
- A resposta deve conter apenas código Java, em @src/test/java/blackbox

  Especificação:
  @openapi/erp-pagamentos.yaml
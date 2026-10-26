# Stub — Integração de Pagamentos

Stub em memória dos dois endpoints de `openapi/erp-pagamentos.yaml`,
com comportamento fixo e determinístico, para testes REST Assured
contra `http://localhost:8080`.

## Subir

```bash
mvn spring-boot:run
```

Requer Java 17 e Maven.

## Valores fixos

| O quê | Valor aceito |
|---|---|
| Header `X-Assinatura` (webhook) | `hmac-sha256=assinatura-valida-stub` |
| Header `X-Api-Key` (API pública) | `chave-parceiro-stub` |
| Aluno existente | `alu-00042` → situação `em_dia` |
| Aluno existente | `alu-00017` → situação `em_atraso` |

O stub NÃO calcula HMAC de verdade: compara o header com o valor fixo
acima (o mecanismo real de assinatura é a lacuna L01 da descrição).

## Comportamento

**POST /webhooks/pagamentos**
- Sem `X-Assinatura` ou valor diferente do fixo → `401 {"erro":"assinatura_invalida"}`
- JSON inválido, ou `idEvento`/`tipoEvento`/`idTransacao` ausentes/vazios → `400 {"erro":"payload_malformado"}`
- Evento válido → `200 {"recebido":true}`
- Duplicata (mesmo `idEvento`): deduplicada em um `Set` em memória e
  responde os mesmos `200 {"recebido":true}` — idempotente, como o
  contrato exige. A assinatura é validada antes do payload.

**GET /alunos/{id}/situacao**
- Sem `X-Api-Key` ou valor diferente do fixo → `401 {"erro":"nao_autenticado"}`
- Aluno fora da tabela acima → `404 {"erro":"aluno_inexistente"}`
- Aluno existente → `200 {"idAluno":"...","situacao":"..."}`

O estado (eventos deduplicados) vive só na memória do processo:
reiniciar o stub zera tudo.

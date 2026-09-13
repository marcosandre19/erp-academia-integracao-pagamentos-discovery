# Descrição do Sistema — Linguagem Natural

## Visão geral

Este repositório documenta um recorte de um ERP de gestão de academias.
O ERP é o sistema central da operação: matrículas, planos, cobrança
recorrente, controle de acesso às unidades e relacionamento com alunos.

O ERP tem papel duplo em integrações:
- **Consumidor**: recebe webhooks de parceiros (ex.: gateway de
  pagamento) e consome APIs de terceiros — REST ou SOAP, dependendo
  da maturidade do parceiro.
- **Provedor**: expõe uma API REST pública e MCPs para que parceiros
  e agentes de IA integrem com o sistema.

**Recorte desta documentação**: a jornada de recebimento e
processamento do webhook de confirmação de pagamento de mensalidade,
até a liberação de acesso do aluno e a disponibilização do evento
para parceiros.

## 1. Escopo

**Dentro do escopo:**
- Recebimento do webhook de confirmação de pagamento do gateway
- Validação e deduplicação do evento (idempotência)
- Atualização da situação financeira do aluno
- Liberação de acesso do aluno na unidade (integração com sistema
  de catraca/acesso)
- Publicação do evento para parceiros consumidores da API pública

**Fora do escopo:**
- Matrícula, cancelamento e estorno
- Geração da cobrança (apenas a confirmação)
- Relatórios e dashboards
- Autenticação de usuários internos do ERP

## 2. Nível da visão

- Diagrama estrutural: C4 nível 2 (Containers)
- Diagrama comportamental: sequência da jornada crítica
- Não misturar níveis; não listar endpoints no estrutural

## 3. Limites e responsabilidades

- **Webhook Receiver**: recebe o POST do gateway, valida assinatura,
  responde rápido e enfileira o evento
- **Processador de Eventos**: consome a fila, aplica idempotência,
  orquestra as atualizações
- **Módulo Financeiro**: atualiza a situação de pagamento do aluno
- **Módulo de Acesso**: comanda a liberação na catraca via API do
  fornecedor (REST ou SOAP, conforme a unidade)
- **API Pública**: expõe a situação do aluno para parceiros; nenhum
  parceiro acessa módulos internos diretamente

## 4. Integrações externas

- Gateway de Pagamento <<external>> — emite o webhook
- Sistema de Catraca/Acesso <<external>> — REST ou SOAP conforme
  fornecedor da unidade
- Parceiros consumidores <<external>> — via API REST pública e MCPs

## 5. Restrições

- Detalhes do gateway (payload, códigos) não vazam para o domínio
- O processamento do webhook DEVE ser idempotente — retry do gateway
  nunca pode duplicar baixa de pagamento nem liberação de acesso
- PII de alunos (CPF, dados financeiros) nunca aparece em logs — LGPD
- A API pública é contrato: mudanças exigem versionamento
- Frontend/app não acessa fila nem processador diretamente

## 6. Lacunas conhecidas (a validar)

- L01: Formato exato do payload e mecanismo de assinatura do webhook
  do gateway (HMAC? token?)
- L02: O gateway garante ordem de eventos? O que fazer se "estorno"
  chegar antes de "confirmação"?
- L03: Política de retry do gateway (quantas tentativas, intervalo?)
- L04: SLA de liberação de acesso após pagamento (segundos? minutos?)
- L05: Estratégia quando a API da catraca está fora (fila de
  reprocessamento? liberação manual?)
- L06: Como parceiros são notificados: polling na API pública,
  webhook de saída, ou ambos?
- L07: Escopos e permissões dos MCPs expostos
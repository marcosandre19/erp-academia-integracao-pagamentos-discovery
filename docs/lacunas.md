# Discovery — Lacunas e Perguntas de Esclarecimento

> Gerado a partir de docs/01-descricao.md, seguindo o fluxo da Unidade III:
> lacunas e perguntas ANTES do diagrama. Nada aqui assume fatos não
> declarados; itens sem resposta permanecem como lacunas explícitas.

## 1) Lacunas identificadas

**LC01 — Modelo de processamento não confirmado.** A descrição sugere
fluxo assíncrono (receiver → fila → processador), mas não declara se a
fila existe de fato ou se o processamento é síncrono dentro do request
do webhook. Isso muda a quantidade de containers e o desenho da
sequência inteira.

**LC02 — Resposta ao gateway vs. conclusão do processamento.** Não está
definido o que o "responder rápido" do Webhook Receiver significa: o
200 confirma apenas o recebimento ou a baixa do pagamento? Isso define
onde o retry do gateway é seguro.

**LC03 — Mecanismo de idempotência não especificado.** A restrição
exige idempotência, mas não diz qual é a chave (ID do evento do
gateway? ID da transação? chave própria?) nem onde a deduplicação
acontece (receiver ou processador).

**LC04 — Ordem de eventos (já registrada como L02, promovida a risco).**
Sem garantia de ordem, "estorno antes de confirmação" produz estado
inconsistente que idempotência sozinha não resolve. Falta a política:
descartar, segurar, reconciliar?

**LC05 — Persistência não descrita.** Nenhum banco aparece na
descrição. Para C4 nível 2, é preciso saber: banco único do ERP?
Storage próprio de eventos processados (para deduplicação)?

**LC06 — Modo de notificação dos parceiros (L06).** "Publicação do
evento para parceiros" pode significar: (a) o dado fica disponível
para polling na API pública, (b) o ERP emite webhooks de saída, ou
(c) ambos. Cada opção é um container/fluxo diferente no diagrama.

**LC07 — MCPs fora ou dentro do recorte?** A visão geral cita MCPs
expostos, mas a jornada descrita só usa a API REST pública. Falta
decidir se o MCP aparece no diagrama de containers (mesmo sem
participar da sequência) ou fica explicitamente fora do escopo.

**LC08 — Variabilidade REST/SOAP da catraca.** Não está claro se a
variação por fornecedor é resolvida por um adaptador único no Módulo
de Acesso ou por integrações separadas. No nível container isso
define se há 1 ou N caixas.

**LC09 — Comportamento em falha da catraca (L05).** Sem definição de
reprocessamento, o caminho de falha da sequência não pode ser
desenhado com verdade — e o caminho de falha é exigência do roteiro
comportamental.

**LC10 — Autenticação dos parceiros na API pública.** A API é
declarada como contrato, mas não há menção ao mecanismo de
autenticação/autorização (API key? OAuth?), o que impacta o container
e as restrições de segurança.

## 2) Perguntas de esclarecimento (ordenadas por impacto no diagrama)

1. O processamento do webhook é assíncrono com fila real, ou síncrono
   dentro do request? Se há fila, qual tecnologia/mecanismo?
2. O que o 200 devolvido ao gateway confirma: recebimento ou
   processamento completo?
3. Qual é a chave de idempotência e onde a deduplicação acontece?
4. Se um evento de estorno chegar antes da confirmação, o que o
   sistema faz hoje (ou deveria fazer)?
5. Parceiros são notificados por polling, webhook de saída, ou ambos?
6. A integração com a catraca é um adaptador único que fala REST ou
   SOAP conforme o fornecedor, ou são integrações separadas?
7. Quando a API da catraca está indisponível, existe reprocessamento
   automático ou intervenção manual?
8. Os MCPs expostos devem aparecer no diagrama de containers deste
   recorte ou ficam registrados como fora de escopo?

## 3) Roteiro revisado (proposto — validar respostas antes de usar)

Diagrama estrutural C4 nível 2 (containers) do subsistema de
integração de pagamentos de um ERP de academias. O Gateway de
Pagamento <<external>> envia webhook ao Webhook Receiver, que valida
assinatura, deduplica ou enfileira [depende de Q1-Q3] e responde ao
gateway [semântica depende de Q2]. O Processador de Eventos aplica
idempotência e orquestra: Módulo Financeiro (baixa do pagamento) e
Módulo de Acesso, que comanda a liberação no Sistema de
Catraca <<external>> via adaptador [forma depende de Q6]. A situação
atualizada fica disponível a Parceiros <<external>> pela API REST
pública [modo de notificação depende de Q5]. Persistência: [LC05 — a
definir]. Restrições: detalhes do gateway não vazam para o domínio;
processamento idempotente; PII fora de logs (LGPD); API pública
versionada; frontend não acessa componentes internos deste fluxo.
Lacunas mantidas explícitas: LC01–LC10.



## Respostas de trabalho (hipóteses baseadas em boas práticas — validar contra o sistema real)

**Q1 — Processamento:** Assíncrono com fila real. O receiver
valida assinatura, publica o evento na fila e responde imediatamente.
Justificativa: webhook handler síncrono acopla o SLA do gateway ao tempo
das integrações internas (catraca SOAP pode ser lenta); fila desacopla e
permite retry interno sem depender do retry do gateway.

**Q2 — Semântica do 200:** O 200 confirma recebimento durável
(evento aceito e enfileirado), não processamento completo. Justificativa:
prática padrão de webhooks — processar dentro do request força o gateway
a re-tentar por lentidão nossa, gerando duplicatas desnecessárias.

**Q3 — Idempotência:** Chave = ID do evento do gateway
(fallback: ID da transação + tipo do evento). Deduplicação no
Processador, onde o efeito colateral acontece, com registro durável de
eventos processados no banco. Justificativa: deduplicar só no receiver
não protege contra reentrega pela fila (at-least-once delivery).

**Q4 — Ordem de eventos:** Máquina de estados do pagamento
com transições válidas explícitas. Evento que chega "fora de ordem"
(estorno antes de confirmação) não é aplicado nem descartado: vai para
uma fila de reconciliação com alerta. Justificativa: descartar perde
dinheiro; aplicar cegamente corrompe estado; segurar e reconciliar é o
único caminho auditável.

**Q5 — Notificação de parceiros:** Nesta fase, apenas
polling na API pública (estado atualizado disponível para consulta).
Webhook de saída para parceiros fica registrado como evolução (L06
permanece parcialmente aberta como decisão de roadmap). Justificativa:
webhook de saída é um subsistema inteiro (registro de endpoints, retry,
assinatura) e não deve entrar no diagrama sem decisão real.

**Q6 — Catraca REST/SOAP:** Um único Módulo de Acesso com
adaptadores por fornecedor (padrão Adapter, coerente com a Unidade II).
No nível container: uma caixa. Justificativa: a variação é detalhe de
integração, não de arquitetura; N caixas poluiria o nível 2.

**Q7 — Catraca indisponível:** Retry com backoff exponencial;
esgotadas as tentativas, evento vai para DLQ (dead letter queue) com
alerta para liberação manual. A baixa financeira NÃO é revertida — os
efeitos são independentes. Justificativa: aluno que pagou não pode ter
o pagamento "desfeito" porque a catraca caiu.

**Q8 — MCPs no diagrama:** Aparecem como container na
fronteira do sistema (são parte do produto-plataforma), consumindo a
mesma API pública internamente — mas marcados como fora da jornada
crítica da sequência. Justificativa: MCP reusar a API garante contrato
único; omitir do diagrama esconderia uma superfície de exposição real
(relevante para a segurança discutida na Unidade III).
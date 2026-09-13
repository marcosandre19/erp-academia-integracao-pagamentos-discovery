# ERP de Academias — Discovery da Integração de Pagamentos

Documentação de arquitetura do recorte: recebimento do webhook de
confirmação de pagamento, baixa financeira, liberação de acesso na
catraca e disponibilização do evento para parceiros.

- [Descrição do sistema](docs/descricao.md)
- [Lacunas e perguntas de esclarecimento](docs/lacunas.md)
- Fonte do diagrama: [`diagramas/containers.mmd`](diagramas/containers.mmd)

## Diagrama estrutural — C4 nível 2 (Containers)

### Suposições adotadas (hipóteses de trabalho — validar contra o sistema real)

Referências: lacunas LC01–LC10 e respostas de trabalho Q1–Q8 em
[docs/lacunas.md](docs/lacunas.md).

- **H01 (LC01/Q1)** — Processamento assíncrono com fila real: o Webhook
  Receiver valida a assinatura, publica na fila e responde imediatamente.
- **H02 (LC02/Q2)** — O 200 devolvido ao gateway confirma recebimento
  durável (evento aceito e enfileirado), não o processamento completo.
- **H03 (LC03/Q3)** — Idempotência por ID do evento do gateway;
  deduplicação no Processador de Eventos, com registro durável dos
  eventos processados.
- **H04 (LC05)** — Banco único do ERP, que persiste a situação do aluno
  e o registro de eventos processados; a API Pública lê a situação nele.
- **H05 (LC06/Q5)** — Parceiros são notificados apenas por polling na
  API Pública; webhook de saída fica como evolução de roadmap e não
  aparece no diagrama.
- **H06 (LC07/Q8)** — O Servidor MCP aparece como container na fronteira
  do sistema e consome a API Pública — nunca o banco; está fora da
  jornada crítica da sequência.
- **H07 (LC08/Q6)** — Módulo de Acesso único, com adaptadores por
  fornecedor (REST/SOAP); a variação é detalhe de integração, uma só caixa.
- **H08 (LC04/Q4 e LC09/Q7)** — Reconciliação de eventos fora de ordem e
  DLQ da catraca existem como mecanismos da infraestrutura de mensageria
  e do processador; não são containers separados neste nível.

```mermaid
C4Container
    title ERP de Academias — Containers do recorte de confirmação de pagamento

    System_Ext(gateway, "Gateway de Pagamento", "Emite o webhook de confirmação de pagamento; faz retries")
    System_Ext(catraca, "Sistema de Catraca/Acesso", "Fornecedor varia por unidade; API REST ou SOAP")
    System_Ext(parceiros, "Parceiros Consumidores", "Integram via API REST pública")
    System_Ext(agentes_ia, "Agentes de IA / Parceiros via MCP", "Integram via protocolo MCP")

    Container_Boundary(erp, "ERP de Academias — subsistema de integração de pagamentos") {
        Container(webhook_receiver, "Webhook Receiver", "Endpoint HTTP", "Recebe o POST do gateway, valida a assinatura, traduz o evento para o formato interno (detalhes do gateway não vazam) e enfileira; responde rápido")
        ContainerQueue(fila_eventos, "Fila de Eventos", "Mensageria, entrega at-least-once", "Desacopla o recebimento do processamento; permite retry interno sem depender do retry do gateway")
        Container(processador, "Processador de Eventos", "Worker", "Consome a fila, aplica idempotência e a máquina de estados do pagamento; orquestra Financeiro e Acesso")
        Container(mod_financeiro, "Módulo Financeiro", "Módulo de domínio", "Efetiva a baixa do pagamento e atualiza a situação financeira do aluno")
        Container(mod_acesso, "Módulo de Acesso", "Módulo de domínio + adaptadores por fornecedor", "Comanda a liberação do aluno na catraca da unidade")
        Container(api_publica, "API Pública", "REST, versionada", "Expõe a situação do aluno a parceiros; único caminho de acesso externo ao domínio")
        Container(mcp_server, "Servidor MCP", "Protocolo MCP", "Expõe capacidades do ERP a agentes de IA reutilizando o contrato da API Pública")
        ContainerDb(banco_erp, "Banco de Dados do ERP", "Banco relacional", "Situação financeira/acesso do aluno e registro de eventos processados (deduplicação)")
    }

    Rel(gateway, webhook_receiver, "Envia webhook de confirmação de pagamento", "HTTPS POST assinado")
    Rel(webhook_receiver, fila_eventos, "Publica evento interno validado")
    Rel(processador, fila_eventos, "Consome eventos")
    Rel(processador, banco_erp, "Consulta/registra eventos processados (idempotência)")
    Rel(processador, mod_financeiro, "Comanda a baixa do pagamento")
    Rel(processador, mod_acesso, "Comanda a liberação de acesso")
    Rel(mod_financeiro, banco_erp, "Atualiza a situação financeira do aluno")
    Rel(mod_acesso, catraca, "Libera o acesso do aluno", "REST ou SOAP, conforme fornecedor")
    Rel(api_publica, banco_erp, "Lê a situação do aluno")
    Rel(parceiros, api_publica, "Consulta a situação do aluno (polling)", "HTTPS/REST")
    Rel(agentes_ia, mcp_server, "Interage via MCP")
    Rel(mcp_server, api_publica, "Consome (nunca acessa o banco diretamente)", "HTTPS/REST")

    UpdateLayoutConfig($c4ShapeInRow="3", $c4BoundaryInRow="1")
```

## Checklist de revisão — limites, dependências e vazamentos

- [ ] O diagrama contém apenas o nível container (nenhum componente
      interno, classe ou endpoint listado)?
- [ ] Gateway de Pagamento, Sistema de Catraca e Parceiros/Agentes de IA
      estão todos marcados como sistemas externos (`System_Ext`)?
- [ ] Nenhum detalhe do gateway (payload, códigos, formato de assinatura)
      aparece além da fronteira do Webhook Receiver — a tradução para o
      formato interno acontece ali?
- [ ] A API Pública é o único caminho de entrada para parceiros — não
      existe nenhuma seta de parceiro para módulo interno, fila ou banco?
- [ ] O Servidor MCP consome exclusivamente a API Pública — não há seta
      MCP → banco nem MCP → módulos internos?
- [ ] Frontend/app não aparece acessando fila ou processador (restrição
      da descrição) — e, se ausente do diagrama, isso está coerente com o
      recorte declarado?
- [ ] O ponto de deduplicação (Processador + registro no banco) está
      visível e coerente com a hipótese H03 — retry do gateway ou
      reentrega da fila não duplicam baixa nem liberação?
- [ ] A direção das dependências está correta: o Processador orquestra
      Financeiro e Acesso, e não o contrário?
- [ ] A baixa financeira e a liberação de acesso estão desenhadas como
      efeitos independentes (falha na catraca não desfaz a baixa — H08)?
- [ ] Cada container do diagrama está sustentado pela descrição ou por
      uma hipótese H01–H08 explícita (nada foi inventado "por boas
      práticas": sem cache, BFF, API gateway etc.)?
- [ ] Toda suposição estrutural do diagrama tem um H numerado que
      referencia a lacuna correspondente (LC01–LC10) do lacunas.md?
- [ ] As lacunas ainda abertas (ex.: LC10 — autenticação de parceiros)
      permanecem registradas como lacunas, sem terem sido "resolvidas"
      silenciosamente no diagrama?

## Diagrama comportamental — sequência da jornada crítica

Jornada: recebimento e processamento do webhook de confirmação de
pagamento, do POST do gateway até a liberação de acesso e o estado
disponível na API Pública. Fonte:
[`diagramas/sequencia-webhook-pagamento.mmd`](diagramas/sequencia-webhook-pagamento.mmd).
Os participantes são exatamente os containers do diagrama estrutural;
o Servidor MCP não aparece por estar fora da jornada crítica (H06).

### Suposições adotadas (H01–H08 herdadas do estrutural; H09–H10 novas)

- **H01–H08** — as mesmas do diagrama de containers (acima), em
  especial: fila real (H01), 200 = recebimento durável (H02),
  deduplicação no Processador com registro durável (H03), polling como
  único modo de notificação (H05), REST/SOAP encapsulado no Módulo de
  Acesso (H07), reconciliação e DLQ como mecanismos de infraestrutura
  (H08).
- **H09 (L03/L04 em aberto)** — Política de retry do gateway, SLA de
  liberação e parâmetros de backoff não são conhecidos: todo limite
  aparece de forma simbólica ("tentativas/timeout configurados"),
  nunca como número.
- **H10 (nova — validar com fornecedor)** — O comando de liberação na
  catraca é declarativo/idempotente (define o estado "liberado");
  reenviá-lo no retry não duplica efeito. Se o fornecedor não garantir
  isso, o retry da catraca precisa de proteção própria.

Lacunas não resolvidas que afetam o desenho: **L03** e **L04**
(representadas simbolicamente via H09), **L06** (só polling aparece —
H05) e **LC10** (autenticação do parceiro no polling não desenhada).

```mermaid
sequenceDiagram
    autonumber
    participant GW as Gateway de Pagamento (externo)
    participant WR as Webhook Receiver
    participant FE as Fila de Eventos
    participant PR as Processador de Eventos
    participant MF as Módulo Financeiro
    participant MA as Módulo de Acesso
    participant CT as Sistema de Catraca/Acesso (externo)
    participant DB as Banco de Dados do ERP
    participant AP as API Pública
    participant PC as Parceiros Consumidores (externo)

    %% ---------- 1. Recebimento durável ----------
    GW->>WR: POST webhook de confirmação de pagamento (assinado)
    activate WR
    WR->>WR: Valida assinatura e traduz para evento interno
    Note right of WR: Fronteira anticorrupção: payload e códigos do gateway não passam daqui (restrição da descrição)
    WR->>FE: Publica evento interno (carrega o ID do evento do gateway)
    WR-->>GW: 200 OK
    deactivate WR
    Note over GW,FE: H02 — o 200 confirma recebimento durável (evento enfileirado), NÃO o processamento completo

    opt Retry do gateway (200 perdido ou política própria — L03 em aberto, H09)
        GW->>WR: POST do MESMO webhook (mesmo ID de evento)
        WR->>FE: Publica novamente — o receiver não deduplica (H03)
        WR-->>GW: 200 OK
        Note over WR,FE: A proteção contra duplicata NÃO está aqui: está na deduplicação durável do processador (passo do alt abaixo)
    end

    %% ---------- 2. Processamento idempotente ----------
    FE->>PR: Entrega evento (at-least-once)
    activate PR
    PR->>DB: Consulta registro durável de eventos processados (chave = ID do evento do gateway — H03)

    alt Evento inédito — caminho de sucesso
        PR->>PR: Valida transição na máquina de estados do pagamento (Q4)
        PR->>MF: Comanda a baixa do pagamento
        activate MF
        MF->>DB: Atualiza a situação financeira do aluno
        MF-->>PR: Baixa confirmada
        deactivate MF
        PR->>MA: Comanda a liberação de acesso
        activate MA
        Note right of MA: Variação REST/SOAP por fornecedor encapsulada nos adaptadores (H07)
        alt Catraca disponível
            MA->>CT: Comando de liberação do aluno
            CT-->>MA: Liberação confirmada
            MA-->>PR: Acesso liberado
        else Catraca indisponível — falha parcial (Q7)
            loop Retry com backoff exponencial — tentativas e timeout "configurados", sem números (H09)
                MA->>CT: Reenvia comando de liberação
                CT--xMA: Falha / sem resposta
            end
            Note right of MA: Reenvio seguro: comando declarativo de estado, idempotente no fornecedor (H10 — validar)
            MA-->>PR: Falha definitiva na liberação
            PR->>FE: Publica o evento na DLQ (mecanismo da infraestrutura — H08)
            Note over PR,FE: Alerta para liberação MANUAL — log/alerta apenas com IDs internos, nunca CPF ou dados financeiros (LGPD)
            Note over MF,MA: A baixa financeira NÃO é revertida — efeitos independentes (Q7): quem pagou não perde a baixa porque a catraca caiu
        end
        deactivate MA
        PR->>DB: Registra o evento como processado (registro durável — H03)
        PR-->>FE: Ack — remove a mensagem da fila
        Note right of PR: Ack só APÓS o registro durável: se o worker cair antes, a fila reentrega e a deduplicação decide
    else Evento já processado — retry do gateway OU reentrega da fila
        Note over PR,DB: AQUI atua a idempotência: o ID do evento já consta no registro durável → nenhum efeito é reexecutado (nem baixa, nem liberação)
        PR-->>FE: Ack — descarta a duplicata sem efeito colateral
    end
    deactivate PR

    %% ---------- 3. Evento fora de ordem ----------
    opt Estorno chega antes da confirmação (Q4 — o estorno em si está fora do escopo)
        FE->>PR: Entrega evento de estorno
        activate PR
        PR->>DB: Consulta estado atual do pagamento
        PR->>PR: Máquina de estados: transição inválida (estorno sem confirmação prévia)
        PR->>FE: Encaminha para reconciliação — não aplica, não descarta (H08)
        deactivate PR
        Note over PR,FE: Alerta para reconciliação/auditoria, sem PII (LGPD)
    end

    %% ---------- 4. Estado disponível na API Pública ----------
    PC->>AP: Consulta a situação do aluno (polling — H05)
    activate AP
    AP->>DB: Lê a situação atualizada (H04)
    AP-->>PC: Situação do aluno (contrato REST versionado)
    deactivate AP
    Note over AP,PC: Autenticação do parceiro: lacuna LC10, não desenhada
```

## Checklist de revisão — sequência do webhook de pagamento

- [ ] Os participantes são exatamente os containers do diagrama
      estrutural (mesmos nomes, mesmos limites), sem participantes
      inventados — e a ausência do Servidor MCP está justificada (H06)?
- [ ] A ordem das interações está correta: validação de assinatura →
      enfileiramento → 200 → consumo → deduplicação → baixa →
      liberação → registro durável → ack?
- [ ] A semântica do 200 (recebimento durável, não processamento
      completo — H02) está visível no desenho, antes de qualquer
      efeito de domínio?
- [ ] **Retry do gateway**: consigo apontar no diagrama o mecanismo que
      impede efeito duplicado (deduplicação no Processador contra o
      registro durável, chave = ID do evento — H03)?
- [ ] **Reentrega da fila (at-least-once)**: consigo apontar o mesmo
      mecanismo cobrindo a queda do worker entre efeito e ack (ack só
      após registro durável)?
- [ ] **Retry da catraca**: consigo apontar por que o reenvio não
      duplica efeito (comando declarativo/idempotente — H10) e essa
      hipótese está marcada como "a validar"?
- [ ] Os efeitos colaterais (baixa financeira e liberação de acesso)
      estão desenhados como independentes — a falha da catraca NÃO
      reverte a baixa (Q7)?
- [ ] O caminho de falha parcial termina em estado observável: DLQ +
      alerta para liberação manual, e não em falha silenciosa?
- [ ] O evento fora de ordem vai para reconciliação com alerta, sem
      ser aplicado nem descartado (Q4), e sem expandir para o fluxo
      completo de estorno (fora do escopo)?
- [ ] Nenhum SLA, timeout ou número de tentativas aparece como número
      inventado — todos os limites são simbólicos ("configurado") com
      a lacuna correspondente registrada (H09, L03/L04)?
- [ ] Todo ponto de log/alerta indicado está livre de PII (CPF, dados
      financeiros) — apenas IDs internos (LGPD)?
- [ ] Detalhes do gateway morrem no Webhook Receiver e a variação
      REST/SOAP morre no Módulo de Acesso — nenhuma nota ou mensagem
      vaza esses detalhes para outros participantes?

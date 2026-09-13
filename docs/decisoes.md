# Decisões e Ajustes sobre o que a IA Gerou

> Registro do ciclo IA gera → humano revisa → decisão registrada.
> Nada aqui foi aceito silenciosamente. Referências: hipóteses H01–H10
> e lacunas LC01–LC10 em [lacunas.md](lacunas.md).

## A. Fase de discovery (descrição e lacunas)

**A01 — Hipóteses separadas de fatos.** As respostas Q1–Q8 do
lacunas.md foram geradas por IA com base em boas práticas e estão
marcadas como hipóteses de trabalho. Nenhuma foi promovida a fato sem
validação contra o sistema real.
`[VALIDAR: registrar aqui quais Q1–Q8 foram confirmadas contra o ERP
real e quais divergiram — cada divergência é um achado.]`

**A02 — O "Processador de Eventos" como container separado foi
inferência da IA** durante o discovery, não fato da descrição
original. Mantido como hipótese estrutural (coerente com H01), a
confirmar.

## B. Diagrama estrutural (containers.mmd)

**B01 — Nada inventado "por boas práticas".** O modelo NÃO adicionou
cache, API gateway ou observabilidade sem sustentação — comportamento
melhor que o viés relatado por colegas em sistemas similares. Todos os
containers rastreiam para a descrição ou para um H numerado.

**B02 — Parceiros divididos em dois atores externos** ("Parceiros
Consumidores" REST e "Agentes de IA via MCP"). Decisão do modelo, não
nossa. Mantida: torna visível que o MCP é uma segunda superfície de
exposição com público próprio — relevante para a segurança (Unidade
III). Registrada aqui porque foi escolha dele, aceita conscientemente.

**B03 — DLQ e reconciliação como mecanismos, não containers (H08).**
Decisão de modelagem do modelo para não poluir o nível 2. Aceita, mas
com consequência: esses mecanismos só aparecem na sequência — quem lê
apenas o estrutural não os vê. Mitigação: nota nas suposições do
README.

**B04 — A VALIDAR: Financeiro e Acesso são containers ou
componentes?** O modelo os desenhou como containers (seguindo a
descrição), mas os descreve como "módulo de domínio". Se no ERP real
eles forem módulos dentro de um mesmo deployável (monólito), o
correto no C4 seria representá-los no nível 3 (componentes) — mantê-los
no nível 2 seria mistura de níveis, violando a regra da unidade.
`[VALIDAR: são processos/deployáveis separados no sistema real?]`

## C. Diagrama de sequência (sequencia-webhook-pagamento.mmd)

**C01 — Idempotência da catraca: o modelo declarou em vez de assumir
em silêncio (H10).** Esperávamos que ele assumisse silenciosamente que
o comando de liberação é idempotente no fornecedor; ele assumiu, mas
marcou como "validar com fornecedor". Ainda assim é a lacuna mais cara
do projeto: com fornecedores SOAP legados, nada garante idempotência.
**Promovida a lacuna formal LC11**: "As APIs de liberação dos
fornecedores de catraca (REST e SOAP) são idempotentes? Se não, o
retry do Módulo de Acesso precisa de proteção própria (chave de
operação ou consulta-antes-de-comandar)."

**C02 — ACHADO DA REVISÃO HUMANA: a DLQ conflita com o registro de
idempotência.** No ramo de falha da catraca, o fluxo publica o evento
na DLQ E registra o evento como processado. Consequência não
desenhada: o reprocessamento da DLQ encontraria o ID no registro
durável e seria descartado como duplicata — o mecanismo de recuperação
é bloqueado pelo mecanismo de proteção. O diagrama é plausível e
coerente, e mesmo assim contém uma decisão inexistente. **Decisão
necessária (registrada como LC12):** o reprocessamento da DLQ usa
chave própria? O registro de idempotência guarda o RESULTADO
(completo/parcial) e não só o ID? A definir com o time.

**C03 — ACHADO DA REVISÃO HUMANA: granularidade da idempotência.** O
registro é por EVENTO, mas os efeitos são dois e independentes (baixa
financeira e liberação de acesso). No ramo de falha, o evento é
marcado "processado" com apenas metade dos efeitos concluída.
**Decisão necessária (LC13):** idempotência por evento ou por efeito?
Idempotência por efeito resolveria também o C02 (o reprocessamento da
DLQ reexecutaria apenas o efeito pendente). A definir com o time.

**C04 — Nenhum número inventado.** Todos os limites (retry, timeout,
SLA) aparecem simbolicamente ("configurado") com H09 e lacunas L03/L04
mantidas abertas. O risco relatado por colegas no fórum (número
plausível indo para o desenho sem marcação) não se materializou aqui —
provavelmente porque o prompt proibiu explicitamente.

**C05 — Inferência correta além do pedido.** O "Ack só APÓS o registro
durável" cobre a janela de queda do worker entre o efeito e o ack —
não estava nas hipóteses nem no prompt; está correto e fecha a
proteção contra reentrega da fila. Aceito e incorporado.

**C06 — Tamanho do diagrama.** Quatro seções em um único desenho:
borderline com a "armadilha comum" da unidade (tudo em um diagrama).
Decisão: mantido único porque os ramos compartilham os mesmos
participantes e a numeração automática ajuda a revisão; se o fluxo de
reconciliação crescer, a seção 3 sai para um diagrama próprio.

## D. Invariantes arquiteturais
(decisões que agentes NÃO podem alterar silenciosamente — cada uma com
justificativa, para resistir a "melhorias" bem-intencionadas)

- **I01 — Processamento de webhook é idempotente.** O gateway
  reentrega e a fila é at-least-once; sem idempotência, cobrança
  duplicada — incidente com cliente, não retrabalho.
- **I02 — Baixa financeira e liberação de acesso são efeitos
  independentes.** Falha na catraca nunca reverte pagamento: aluno que
  pagou, pagou.
- **I03 — Detalhes do gateway morrem no Webhook Receiver.** Troca de
  gateway não pode reescrever o domínio (fronteira anticorrupção).
- **I04 — Parceiros e MCPs só enxergam a API Pública versionada.** A
  API é contrato/produto; acesso direto a banco ou módulos criaria
  acoplamento impossível de depreciar com parceiros em produção.
- **I05 — PII de alunos nunca em logs ou alertas.** LGPD; logs
  carregam apenas IDs internos.
- **I06 — O 200 ao gateway significa recebimento durável, nunca
  processamento completo.** Mudar essa semântica silenciosamente
  quebra o contrato de retry com o gateway.

## E. Lacunas novas abertas pela revisão

| ID   | Lacuna                                                        | Origem |
|------|---------------------------------------------------------------|--------|
| LC11 | Idempotência das APIs de catraca (REST/SOAP) não garantida    | C01/H10 |
| LC12 | Interação DLQ × registro de idempotência indefinida           | C02 |
| LC13 | Granularidade da idempotência: por evento ou por efeito?      | C03 |

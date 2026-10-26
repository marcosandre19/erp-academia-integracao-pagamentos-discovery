package cot;

import io.restassured.http.ContentType;
import org.junit.jupiter.api.Disabled;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.containsString;

/**
 * Modos de falha da integração gateway → webhook → processamento → API
 * pública, um teste por modo (prompt 2, Chain-of-Thought).
 *
 * Passo 1 — modos de falha identificados:
 *   F1. Timeout da resposta ao gateway: o 200 se perde na rede e o
 *       gateway reenvia o MESMO evento (retry).
 *   F2. Entrega duplicada sem timeout: fila/gateway at-least-once
 *       reentrega um evento já processado.
 *   F3. Eventos fora de ordem: dois eventos da mesma transação chegam
 *       em ordem inversa à de emissão.
 *   F4. Falha no processamento assíncrono depois do 200: a baixa
 *       financeira ou a liberação de acesso falham após o recebimento.
 *   F5. (transversal) Erro da integração vazando dados do aluno (PII)
 *       na resposta.
 *
 * Passo 2 — comportamento esperado APENAS pelas regras fornecidas:
 *   F1/F2 → I01 (idempotência): reentrega nunca duplica efeito; e o
 *       contrato só define 200 para evento válido, logo a reentrega
 *       recebe o mesmo 200 de recebimento durável (I06).
 *   F3 → I06: cada evento válido é aceito com 200 (recebimento durável
 *       independe da ordem). Qual situação final prevalece é PENDENTE:
 *       o contrato só define o tipo "pagamento_confirmado" — pergunta
 *       que destrava: "o gateway emite outros tipos (ex.: estorno)?
 *       como o domínio ordena eventos concorrentes da mesma transação
 *       (timestamp? sequência)?"
 *   F4 → I06: o 200 já emitido continua válido (significa recebimento,
 *       não processamento); I02: a falha de um efeito não reverte o
 *       outro. A parte observável via API pública é que o 200 NÃO
 *       garante situação atualizada. O restante é PENDENTE — pergunta
 *       que destrava: "como observar baixa financeira e DLQ num teste
 *       ponta a ponta (endpoint interno? métrica? tabela)?"
 *   F5 → regra LGPD do projeto: PII de alunos nunca aparece em
 *       payloads de exemplo, logs ou mensagens de erro.
 */
class FalhasIntegracaoCotTest extends CotTestBase {

    // ------------------------------------------------------------------
    // F1 — Timeout + retry do gateway
    // Regra protegida: I01 — o processamento do webhook é idempotente;
    // o retry causado por timeout (o gateway nunca viu o 200) recebe a
    // mesma resposta de sucesso e não produz efeito novo. I06 — cada 200
    // significa apenas recebimento durável.
    // ------------------------------------------------------------------
    @Test
    void f1_retryAposTimeoutRecebeOMesmo200SemEfeitoDuplicado() {
        String corpo = eventoJson("evt-cot-timeout", "trx-cot-0001");

        // 1ª entrega: o gateway enviou, mas (simulado) não leu o 200.
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(corpo)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));

        // Retry do gateway com o MESMO idEvento: mesma resposta, sem erro
        // de "duplicado" (o contrato não define tal erro) e sem efeito novo.
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(corpo)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));
    }

    // ------------------------------------------------------------------
    // F2 — Entrega duplicada (at-least-once)
    // Regra protegida: I01 — reentrega nunca duplica efeito. O efeito
    // observável pelo único ponto de leitura do contrato (API pública)
    // não muda entre a 1ª entrega e a duplicata: a situação do aluno é
    // a mesma antes e depois da reentrega.
    // ------------------------------------------------------------------
    @Test
    void f2_entregaDuplicadaNaoAlteraSituacaoObservadaPelaApiPublica() {
        String corpo = eventoJson("evt-cot-duplicado", "trx-cot-0002");

        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(corpo)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200);

        // Situação observada após a 1ª entrega.
        String situacaoAposPrimeira =
                given()
                        .header("X-Api-Key", API_KEY_VALIDA)
                .when()
                        .get("/alunos/{id}/situacao", ALUNO_EM_DIA)
                .then()
                        .statusCode(200)
                        .extract().path("situacao");

        // Duplicata do mesmo evento.
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(corpo)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));

        // A duplicata não produziu efeito novo observável (I01).
        given()
                .header("X-Api-Key", API_KEY_VALIDA)
        .when()
                .get("/alunos/{id}/situacao", ALUNO_EM_DIA)
        .then()
                .statusCode(200)
                .body("situacao", equalTo(situacaoAposPrimeira));
    }

    // ------------------------------------------------------------------
    // F3 — Eventos fora de ordem
    // Regra protegida: I06 — o 200 confirma recebimento durável de cada
    // evento, independentemente da ordem de chegada; o receiver não
    // rejeita um evento "atrasado".
    // PENDENTE: qual situação final prevalece quando eventos da mesma
    // transação chegam fora de ordem não é definido pelas regras (o
    // contrato só tem "pagamento_confirmado"). Pergunta que destrava:
    // o gateway emite outros tipos (ex.: estorno)? como o domínio ordena
    // eventos concorrentes (timestamp? número de sequência)?
    // ------------------------------------------------------------------
    @Test
    void f3_eventosDaMesmaTransacaoForaDeOrdemSaoAmbosRecebidosCom200() {
        // Emitidos na ordem 1 → 2, entregues na ordem 2 → 1.
        String evento1 = eventoJson("evt-cot-ooo-1", "trx-cot-0003");
        String evento2 = eventoJson("evt-cot-ooo-2", "trx-cot-0003");

        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(evento2)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));

        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(evento1)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));
    }

    // ------------------------------------------------------------------
    // F4 — Falha no processamento depois do 200
    // Regra protegida: I06 — o 200 ao gateway significa recebimento
    // durável, nunca processamento completo. Logo, nenhum consumidor
    // pode assumir que o 200 implica situação atualizada na API pública:
    // imediatamente após o webhook, o aluno em atraso ainda pode constar
    // "em_atraso", e isso É conforme o contrato.
    // PENDENTE: I02 (baixa e liberação independentes — falha de um não
    // reverte o outro) não é observável pelos dois endpoints do recorte.
    // Pergunta que destrava: como observar baixa financeira e DLQ num
    // teste ponta a ponta (endpoint interno? métrica? tabela)?
    // ------------------------------------------------------------------
    @Test
    void f4_duzentosNoWebhookNaoGaranteSituacaoAtualizadaNaApiPublica() {
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(eventoJson("evt-cot-pos200", "trx-cot-0004"))
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));

        // O processamento é assíncrono: logo após o 200, a situação
        // anterior ("em_atraso") ainda é uma resposta válida do contrato.
        given()
                .header("X-Api-Key", API_KEY_VALIDA)
        .when()
                .get("/alunos/{id}/situacao", ALUNO_EM_ATRASO)
        .then()
                .statusCode(200)
                .body("idAluno", equalTo(ALUNO_EM_ATRASO))
                .body("situacao", equalTo("em_atraso"));
    }

    // ------------------------------------------------------------------
    // F5 — Erro da integração vazando PII
    // Regra protegida: PII de alunos nunca aparece em payloads de
    // exemplo, logs ou mensagens de erro. Um payload rejeitado contendo
    // sentinelas fictícias (não são PII real) não pode ser ecoado na
    // resposta de erro.
    // ------------------------------------------------------------------
    @Test
    void f5_respostaDeErroNaoEcoaDadosDoPayload() {
        String sentinelaNome = "NOME-FICTICIO-SENTINELA";
        String sentinelaCpf = "000.000.000-00";

        // Payload malformado (sem os campos obrigatórios) carregando
        // campos extras com as sentinelas.
        String corpo = """
                {
                  "nomeAluno": "%s",
                  "cpf": "%s"
                }
                """.formatted(sentinelaNome, sentinelaCpf);

        String respostaErro =
                given()
                        .contentType(ContentType.JSON)
                        .header("X-Assinatura", ASSINATURA_VALIDA)
                        .body(corpo)
                .when()
                        .post("/webhooks/pagamentos")
                .then()
                        .statusCode(400)
                        .body("erro", equalTo("payload_malformado"))
                        .extract().body().asString();

        org.hamcrest.MatcherAssert.assertThat(respostaErro,
                not(containsString(sentinelaNome)));
        org.hamcrest.MatcherAssert.assertThat(respostaErro,
                not(containsString(sentinelaCpf)));
    }

    // ------------------------------------------------------------------
    // PENDENTE — I02 (independência entre baixa financeira e liberação
    // de acesso) não tem ponto de observação no contrato atual: os dois
    // endpoints do recorte não expõem a baixa nem a DLQ. Teste mantido
    // desabilitado até a resposta da pergunta registrada abaixo.
    // Pergunta que destrava: qual recurso permitirá observar, num teste
    // de integração, que a baixa persistiu mesmo com a liberação de
    // acesso em falha (e vice-versa)? (endpoint interno? evento? tabela?)
    // ------------------------------------------------------------------
    @Disabled("PENDENTE: contrato não expõe baixa financeira nem DLQ; " +
            "sem ponto de observação para verificar I02")
    @Test
    void pendente_i02_falhaDaLiberacaoNaoReverteABaixaFinanceira() {
        // Intencionalmente vazio: ver pergunta no comentário acima.
    }
}

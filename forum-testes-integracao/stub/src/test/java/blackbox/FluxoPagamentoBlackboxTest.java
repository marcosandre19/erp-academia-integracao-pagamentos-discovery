package blackbox;

import io.restassured.http.ContentType;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.blankOrNullString;

/**
 * Fluxo entre os dois endpoints: consulta do parceiro antes e depois do
 * recebimento do webhook, incluindo a entrega duplicada.
 */
class FluxoPagamentoBlackboxTest extends BlackboxTestBase {

    // Regras protegidas:
    // (1) o 200 do webhook confirma recebimento durável, não processamento
    //     completo — logo a consulta imediatamente após o 200 NÃO pode ser
    //     usada para afirmar mudança de situação;
    // (2) reprocessar o mesmo ID de evento nunca duplica a baixa — a
    //     situação observável pela API pública é a mesma após a reentrega.
    // PENDENTE (contrato): o payload do webhook (idEvento, tipoEvento,
    // idTransacao) não carrega vínculo com o aluno, então não há como
    // afirmar pelo contrato QUAL situação muda nem quando (LC01: o modelo
    // de processamento assíncrono também não está confirmado). O teste
    // afirma apenas o que o contrato garante: as consultas antes e depois
    // cumprem o schema e a reentrega não altera o estado observável.
    @Test
    void consultaAntesEDepoisDoWebhookComEntregaDuplicada() {
        // Consulta ANTES do webhook: contrato cumprido, situação presente.
        String situacaoAntes =
                given()
                        .header("X-Api-Key", API_KEY_VALIDA)
                .when()
                        .get("/alunos/{id}/situacao", ALUNO_EXISTENTE)
                .then()
                        .statusCode(200)
                        .body("idAluno", equalTo(ALUNO_EXISTENTE))
                        .body("situacao", not(blankOrNullString()))
                .extract().path("situacao");

        // Webhook recebido (recebimento durável).
        String corpo = eventoJson("evt-bb-fluxo");
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(corpo)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));

        // Consulta DEPOIS do primeiro recebimento: contrato cumprido.
        String situacaoDepois =
                given()
                        .header("X-Api-Key", API_KEY_VALIDA)
                .when()
                        .get("/alunos/{id}/situacao", ALUNO_EXISTENTE)
                .then()
                        .statusCode(200)
                        .body("idAluno", equalTo(ALUNO_EXISTENTE))
                        .body("situacao", not(blankOrNullString()))
                .extract().path("situacao");

        // Reentrega do MESMO evento (retry do gateway).
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(corpo)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));

        // A situação observável após a reentrega é a mesma de antes dela:
        // nenhum efeito duplicado visível pela API pública.
        given()
                .header("X-Api-Key", API_KEY_VALIDA)
        .when()
                .get("/alunos/{id}/situacao", ALUNO_EXISTENTE)
        .then()
                .statusCode(200)
                .body("situacao", equalTo(situacaoDepois));

        // PENDENTE (LC01): sem a definição do modelo de processamento e do
        // vínculo evento→aluno, não há asserção de contrato possível entre
        // situacaoAntes e situacaoDepois; registrado aqui para não inventar
        // regra que a especificação não sustenta.
    }
}

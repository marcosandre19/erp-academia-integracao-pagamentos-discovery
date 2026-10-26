package blackbox;

import io.restassured.http.ContentType;
import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;

/**
 * POST /webhooks/pagamentos — todas as respostas do contrato (200, 400, 401).
 */
class WebhookPagamentosBlackboxTest extends BlackboxTestBase {

    // Regra protegida: o 200 confirma recebimento durável (evento aceito e
    // enfileirado), NÃO o processamento completo — por isso o teste afirma
    // apenas "recebido": true, único campo que o contrato define na resposta.
    @Test
    void webhookValidoRespondem200ComRecebimentoDuravel() {
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(eventoJson("evt-bb-sucesso"))
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));
    }

    // Regra protegida: assinatura HMAC inválida nunca é aceita (401).
    @Test
    void assinaturaInvalidaRespondem401() {
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", "hmac-sha256=assinatura-forjada")
                .body(eventoJson("evt-bb-assinatura-invalida"))
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(401)
                .body("erro", equalTo("assinatura_invalida"));
    }

    // Regra protegida: o header de assinatura é obrigatório no contrato;
    // ausência equivale a assinatura não verificável (401).
    @Test
    void assinaturaAusenteRespondem401() {
        given()
                .contentType(ContentType.JSON)
                .body(eventoJson("evt-bb-sem-assinatura"))
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(401)
                .body("erro", equalTo("assinatura_invalida"));
    }

    // Regra protegida: payload que não é JSON válido é rejeitado com 400.
    @Test
    void jsonInvalidoRespondem400() {
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body("{isto-nao-e-json")
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(400)
                .body("erro", equalTo("payload_malformado"));
    }

    // Regra protegida: idEvento, tipoEvento e idTransacao são obrigatórios
    // no contrato; a falta de qualquer um é payload malformado (400).
    @Test
    void campoObrigatorioAusenteRespondem400() {
        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body("""
                        { "tipoEvento": "pagamento_confirmado" }
                        """)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(400)
                .body("erro", equalTo("payload_malformado"));
    }

    // Regra protegida: reprocessar o mesmo ID de evento nunca duplica a
    // baixa do pagamento — a reentrega recebe a MESMA resposta de sucesso
    // (idempotência), sem erro e sem efeito novo.
    // PENDENTE: o contrato não expõe um recurso que permita observar a
    // baixa em si; a ausência de efeito duplicado observável pela API
    // pública é verificada em FluxoPagamentoBlackboxTest.
    @Test
    void entregaDuplicadaDoMesmoEventoRespondemOMesmo200() {
        String corpo = eventoJson("evt-bb-duplicado");

        given()
                .contentType(ContentType.JSON)
                .header("X-Assinatura", ASSINATURA_VALIDA)
                .body(corpo)
        .when()
                .post("/webhooks/pagamentos")
        .then()
                .statusCode(200)
                .body("recebido", equalTo(true));

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
}

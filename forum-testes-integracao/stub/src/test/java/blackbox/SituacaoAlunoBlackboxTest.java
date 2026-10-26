package blackbox;

import org.junit.jupiter.api.Test;

import static io.restassured.RestAssured.given;
import static org.hamcrest.Matchers.equalTo;
import static org.hamcrest.Matchers.not;
import static org.hamcrest.Matchers.blankOrNullString;

/**
 * GET /alunos/{id}/situacao — todas as respostas do contrato (200, 401, 404).
 */
class SituacaoAlunoBlackboxTest extends BlackboxTestBase {

    // Regra protegida: a API pública expõe a situação do aluno a parceiros
    // autenticados, com os dois campos obrigatórios do schema SituacaoAluno
    // (idAluno e situacao).
    // PENDENTE (contrato): "situacao" é string livre no contrato — os
    // valores possíveis não estão enumerados; o teste só afirma presença.
    @Test
    void alunoExistenteComAutenticacaoRespondem200ComSituacao() {
        given()
                .header("X-Api-Key", API_KEY_VALIDA)
        .when()
                .get("/alunos/{id}/situacao", ALUNO_EXISTENTE)
        .then()
                .statusCode(200)
                .body("idAluno", equalTo(ALUNO_EXISTENTE))
                .body("situacao", not(blankOrNullString()));
    }

    // Regra protegida: nenhum parceiro acessa o domínio sem autenticação (401).
    @Test
    void semAutenticacaoRespondem401() {
        given()
        .when()
                .get("/alunos/{id}/situacao", ALUNO_EXISTENTE)
        .then()
                .statusCode(401)
                .body("erro", equalTo("nao_autenticado"));
    }

    // Regra protegida: credencial inválida equivale a ausência de
    // autenticação (401), sem vazar se o aluno existe.
    @Test
    void credencialInvalidaRespondem401() {
        given()
                .header("X-Api-Key", "chave-invalida")
        .when()
                .get("/alunos/{id}/situacao", ALUNO_EXISTENTE)
        .then()
                .statusCode(401)
                .body("erro", equalTo("nao_autenticado"));
    }

    // Regra protegida: aluno inexistente é 404 com o corpo de erro do contrato.
    @Test
    void alunoInexistenteRespondem404() {
        given()
                .header("X-Api-Key", API_KEY_VALIDA)
        .when()
                .get("/alunos/{id}/situacao", "alu-99999")
        .then()
                .statusCode(404)
                .body("erro", equalTo("aluno_inexistente"));
    }
}

package blackbox;

import com.exemplo.erp.stub.StubApplication;
import io.restassured.RestAssured;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;

/**
 * Base dos testes caixa-preta: sobe a aplicação em porta aleatória e
 * interage apenas via HTTP, com o contrato openapi/erp-pagamentos.yaml
 * como única fonte dos valores esperados.
 *
 * PENDENTE (L01): o mecanismo real de assinatura HMAC do gateway não
 * está definido no contrato; o valor abaixo é a credencial fixa
 * documentada do ambiente de teste (stub).
 * PENDENTE (LC10): o mecanismo de autenticação dos parceiros (API key?
 * OAuth?) não está definido; idem.
 */
@SpringBootTest(classes = StubApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
abstract class BlackboxTestBase {

    static final String ASSINATURA_VALIDA = "hmac-sha256=assinatura-valida-stub";
    static final String API_KEY_VALIDA = "chave-parceiro-stub";

    // Aluno do exemplo do contrato (dados fictícios)
    static final String ALUNO_EXISTENTE = "alu-00042";

    @LocalServerPort
    private int porta;

    @BeforeEach
    void configurarRestAssured() {
        RestAssured.port = porta;
    }

    static String eventoJson(String idEvento) {
        return """
                {
                  "idEvento": "%s",
                  "tipoEvento": "pagamento_confirmado",
                  "idTransacao": "trx-123456"
                }
                """.formatted(idEvento);
    }
}

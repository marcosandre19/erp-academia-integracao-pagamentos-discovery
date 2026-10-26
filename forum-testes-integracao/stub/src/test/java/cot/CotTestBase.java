package cot;

import com.exemplo.erp.stub.StubApplication;
import io.restassured.RestAssured;
import org.junit.jupiter.api.BeforeEach;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;

/**
 * Base dos testes gerados pelo prompt 2 (Chain-of-Thought sobre modos de
 * falha). Sobe a aplicação em porta aleatória e interage apenas via HTTP;
 * o contrato openapi/erp-pagamentos.yaml e as regras I01/I02/I06 + LGPD
 * do prompt são as únicas fontes de comportamento esperado.
 *
 * PENDENTE (L01): o mecanismo real de assinatura HMAC não está definido
 * no contrato; o valor abaixo é a credencial fixa do stub de teste.
 * PENDENTE (LC10): o mecanismo de autenticação dos parceiros não está
 * definido; idem.
 */
@SpringBootTest(classes = StubApplication.class,
        webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
abstract class CotTestBase {

    static final String ASSINATURA_VALIDA = "hmac-sha256=assinatura-valida-stub";
    static final String API_KEY_VALIDA = "chave-parceiro-stub";

    // Alunos fictícios pré-cadastrados no stub (sem PII)
    static final String ALUNO_EM_DIA = "alu-00042";
    static final String ALUNO_EM_ATRASO = "alu-00017";

    @LocalServerPort
    private int porta;

    @BeforeEach
    void configurarRestAssured() {
        RestAssured.port = porta;
    }

    static String eventoJson(String idEvento, String idTransacao) {
        return """
                {
                  "idEvento": "%s",
                  "tipoEvento": "pagamento_confirmado",
                  "idTransacao": "%s"
                }
                """.formatted(idEvento, idTransacao);
    }
}

package com.exemplo.erp.stub;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Stub determinístico dos dois endpoints de openapi/erp-pagamentos.yaml.
 * Valores fixos aceitos (ver README.md): assinatura do gateway, API key
 * do parceiro e os alunos pré-cadastrados.
 */
@RestController
public class StubController {

    static final String ASSINATURA_VALIDA = "hmac-sha256=assinatura-valida-stub";
    static final String API_KEY_VALIDA = "chave-parceiro-stub";

    static final Map<String, String> SITUACAO_POR_ALUNO = Map.of(
            "alu-00042", "em_dia",
            "alu-00017", "em_atraso"
    );

    private final Set<String> eventosProcessados = ConcurrentHashMap.newKeySet();
    private final ObjectMapper objectMapper = new ObjectMapper();

    @PostMapping("/webhooks/pagamentos")
    public ResponseEntity<Map<String, Object>> receberWebhookPagamento(
            @RequestHeader(value = "X-Assinatura", required = false) String assinatura,
            @RequestBody(required = false) String corpo) {

        if (!ASSINATURA_VALIDA.equals(assinatura)) {
            return erro(HttpStatus.UNAUTHORIZED, "assinatura_invalida",
                    "A assinatura do webhook não pôde ser verificada.");
        }

        JsonNode evento;
        try {
            evento = objectMapper.readTree(corpo == null ? "" : corpo);
        } catch (Exception e) {
            evento = null;
        }
        if (evento == null || !evento.isObject()
                || campoAusente(evento, "idEvento")
                || campoAusente(evento, "tipoEvento")
                || campoAusente(evento, "idTransacao")) {
            return erro(HttpStatus.BAD_REQUEST, "payload_malformado",
                    "Corpo da requisição não é um evento válido.");
        }

        // Idempotência: duplicata não reprocessa, mas a resposta é a mesma.
        eventosProcessados.add(evento.get("idEvento").asText());

        return ResponseEntity.ok(Map.of("recebido", true));
    }

    @GetMapping("/alunos/{id}/situacao")
    public ResponseEntity<Map<String, Object>> consultarSituacaoAluno(
            @RequestHeader(value = "X-Api-Key", required = false) String apiKey,
            @PathVariable String id) {

        if (!API_KEY_VALIDA.equals(apiKey)) {
            return erro(HttpStatus.UNAUTHORIZED, "nao_autenticado",
                    "Credenciais ausentes ou inválidas.");
        }

        String situacao = SITUACAO_POR_ALUNO.get(id);
        if (situacao == null) {
            return erro(HttpStatus.NOT_FOUND, "aluno_inexistente",
                    "Nenhum aluno encontrado para o id informado.");
        }

        return ResponseEntity.ok(Map.of("idAluno", id, "situacao", situacao));
    }

    private static boolean campoAusente(JsonNode no, String campo) {
        JsonNode valor = no.get(campo);
        return valor == null || !valor.isTextual() || valor.asText().isBlank();
    }

    private static ResponseEntity<Map<String, Object>> erro(
            HttpStatus status, String codigo, String mensagem) {
        return ResponseEntity.status(status)
                .body(Map.of("erro", codigo, "mensagem", mensagem));
    }
}

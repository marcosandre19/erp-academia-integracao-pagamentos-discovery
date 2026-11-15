#!/usr/bin/env python3
"""Monta o prompt-diagnostico.md com o contexto minimo para o diagnostico por IA.

Conteudo, nesta ordem:
  1. recorte das falhas do log do Maven + relatorios surefire das classes
     reprovadas (nao o log inteiro);
  2. git diff do PR atual (ou do ultimo commit / working tree);
  3. fontes citados nos stack traces E os modulos do projeto relacionados a
     eles (imports e vizinhos de pacote) — a causa-raiz pode nao estar no
     traceback;
  4. sanitizacao obrigatoria antes de gravar: tokens/chaves/segredos,
     e-mails e caminhos de usuario sao mascarados.

Uso:
  coleta_contexto.py --log maven-test.log [--surefire-dir DIR]
                     [--repo-root DIR] [--saida prompt-diagnostico.md]
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_ARQUIVOS_FONTE = 40
MAX_BYTES_POR_FONTE = 60_000
MAX_BYTES_FONTES_TOTAL = 400_000
MAX_BYTES_LOG = 150_000
MAX_BYTES_SUREFIRE = 40_000
MAX_BYTES_DIFF = 200_000
# Com orcamento ativo, espaco minimo garantido para a secao de fontes: um
# diff grande (ex.: working tree sujo) nao pode expulsar o codigo de
# producao do prompt — e la que a causa-raiz costuma estar.
RESERVA_MIN_FONTES = 6_000

DIRS_IGNORADOS = {".git", "target", "node_modules", "build", ".idea", ".m2"}

# Sanitizacao: segredos primeiro, depois e-mails e caminhos de usuario.
MASCARAS = [
    (re.compile(r"\b(?:sk|rk)-[A-Za-z0-9_\-]{8,}"), "***SEGREDO***"),
    (re.compile(r"\bglpat-[A-Za-z0-9_\-]{10,}"), "***SEGREDO***"),
    (re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}"), "***SEGREDO***"),
    (re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"), "***SEGREDO***"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "***SEGREDO***"),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{8,}"), "***SEGREDO***"),
    # JWT (tres blocos base64url separados por ponto)
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}"),
     "***SEGREDO***"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._\-+/=]{8,}"), r"\1***SEGREDO***"),
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)\S+"), r"\1***SEGREDO***"),
    (re.compile(
        r"(?i)\b((?:api[_-]?key|apikey|access[_-]?key|client[_-]?secret|secret|"
        r"token|senha|password|passwd)\s*[=:]\s*)[^\s\"',;]+"),
     r"\1***SEGREDO***"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "***EMAIL***"),
    (re.compile(r"(?i)[a-z]:\\+Users\\+[^\\/\s\"']+"), r"C:\\Users\\***"),
    (re.compile(r"/home/[^/\s\"']+"), "/home/***"),
    (re.compile(r"/Users/[^/\s\"']+"), "/Users/***"),
]


def sanitizar(texto):
    for padrao, substituto in MASCARAS:
        texto = padrao.sub(substituto, texto)
    return texto


def truncar(texto, limite, rotulo):
    dados = texto.encode("utf-8", errors="replace")
    if len(dados) <= limite:
        return texto
    recorte = dados[:limite].decode("utf-8", errors="replace")
    return recorte + f"\n[... {rotulo} truncado em {limite} bytes ...]"


def ler(caminho):
    return Path(caminho).read_text(encoding="utf-8", errors="replace")


def recortar_falhas(texto_log):
    """Blocos do log: cada '<<< FAILURE!/ERROR!' com seu stack trace, mais o
    resumo final '[ERROR] Failures:/Errors:'."""
    linhas = texto_log.splitlines()
    blocos = []
    i, n = 0, len(linhas)
    while i < n:
        linha = linhas[i]
        if "<<< FAILURE!" in linha or "<<< ERROR!" in linha:
            bloco = [linha]
            i += 1
            while (i < n and not linhas[i].startswith("[INFO]")
                   and "<<< FAILURE!" not in linhas[i]
                   and "<<< ERROR!" not in linhas[i]):
                bloco.append(linhas[i])
                i += 1
            blocos.append("\n".join(bloco).rstrip())
            continue
        if re.match(r"\[ERROR\]\s+(Failures:|Errors:)\s*$", linha):
            bloco = [linha]
            i += 1
            while i < n and linhas[i].startswith("[ERROR]"):
                bloco.append(linhas[i])
                i += 1
            blocos.append("\n".join(bloco).rstrip())
            continue
        i += 1
    if not blocos:  # log sem marcadores conhecidos: ultimas linhas como fallback
        blocos.append("\n".join(linhas[-80:]))
    return blocos


PADRAO_LINHA_FRAME = re.compile(r"^\s*at\s+\S")
PADRAO_FRAME_PROJETO = re.compile(r"^\s*at\s+(?:blackbox|cot|com\.exemplo\.erp)\.")
PADRAO_TESTE_REPROVADO = re.compile(
    r"([\w$]+(?:\.[\w$]+)+)\s+--\s+Time elapsed:.*<<<\s+(?:FAILURE|ERROR)!")


def podar_stack(texto):
    """Poda frames de stack trace: mantem a mensagem de erro completa (linhas
    que nao sao frame passam direto), as 3 primeiras frames de cada trecho
    contiguo e TODAS as frames de classes do projeto; o resto vira uma unica
    marca com a contagem do que foi omitido."""
    linhas = texto.splitlines()
    saida = []
    i, n = 0, len(linhas)
    while i < n:
        if not PADRAO_LINHA_FRAME.match(linhas[i]):
            saida.append(linhas[i])
            i += 1
            continue
        trecho = []
        while i < n and PADRAO_LINHA_FRAME.match(linhas[i]):
            trecho.append(linhas[i])
            i += 1
        omitidas = 0
        for posicao, frame in enumerate(trecho):
            if posicao < 3 or PADRAO_FRAME_PROJETO.match(frame):
                if omitidas:
                    saida.append(f"\t[... {omitidas} frames de infraestrutura omitidas ...]")
                    omitidas = 0
                saida.append(frame)
            else:
                omitidas += 1
        if omitidas:
            saida.append(f"\t[... {omitidas} frames de infraestrutura omitidas ...]")
    return "\n".join(saida)


def testes_reprovados(texto):
    """Nomes qualificados dos testes reprovados (linhas-cabecalho de falha),
    usados para detectar relatorio surefire que so repete o recorte do log."""
    return {m.group(1) for m in PADRAO_TESTE_REPROVADO.finditer(texto)}


def relatorios_surefire(diretorio):
    """Conteudo dos .txt do surefire das classes com falha (tem o stack trace
    completo, que o log resumido do Maven pode nao ter)."""
    resultados = []
    if not diretorio:
        return resultados
    pasta = Path(diretorio)
    if not pasta.is_dir():
        return resultados
    for arquivo in sorted(pasta.glob("*.txt")):
        texto = ler(arquivo)
        if "<<< FAILURE!" in texto or "<<< ERROR!" in texto:
            resultados.append((arquivo.name, texto))
    return resultados


def classes_citadas(texto):
    """Nomes de classe citados em frames de stack trace e no resumo do Maven."""
    nomes = set()
    for m in re.finditer(r"\(([A-Z][\w$]*)\.java:\d+\)", texto):
        nomes.add(m.group(1))
    # forma do resumo: pacote.Classe.metodo:linha
    for m in re.finditer(r"\b(?:[a-z_][\w]*\.)+([A-Z][\w$]*)\.[\w$]+:\d+", texto):
        nomes.add(m.group(1))
    # forma do surefire: "-- in pacote.Classe"
    for m in re.finditer(r"-- in (?:[\w.]*\.)?([A-Z][\w$]*)\b", texto):
        nomes.add(m.group(1))
    return nomes


def indexar_fontes(repo_root):
    indice = {}
    for caminho in repo_root.rglob("*.java"):
        if any(parte in DIRS_IGNORADOS for parte in caminho.parts):
            continue
        indice.setdefault(caminho.stem, []).append(caminho)
    return indice


def expandir_relacionados(iniciais, indice, profundidade_max=3):
    """BFS a partir dos fontes citados: imports do projeto + vizinhos de
    pacote (dependencias do mesmo pacote nao aparecem em import). A
    profundidade 3 cobre o caso teste -> classe-base -> aplicacao ->
    vizinhos da aplicacao; os limites de quantidade/bytes seguram o total."""
    ordem = list(iniciais)
    nivel = {arquivo: 0 for arquivo in iniciais}
    fila = list(iniciais)
    while fila and len(ordem) < MAX_ARQUIVOS_FONTE:
        atual = fila.pop(0)
        if nivel[atual] >= profundidade_max:
            continue
        try:
            texto = ler(atual)
        except OSError:
            continue
        vizinhos = []
        for m in re.finditer(r"^import\s+(?:static\s+)?([\w.]+)\s*;", texto, re.M):
            partes = [p for p in m.group(1).split(".") if p and p[0].isupper()]
            if partes:
                vizinhos.extend(indice.get(partes[0], []))
        vizinhos.extend(sorted(atual.parent.glob("*.java")))
        for vizinho in vizinhos:
            if vizinho in nivel:
                continue
            if any(parte in DIRS_IGNORADOS for parte in vizinho.parts):
                continue
            nivel[vizinho] = nivel[atual] + 1
            ordem.append(vizinho)
            fila.append(vizinho)
            if len(ordem) >= MAX_ARQUIVOS_FONTE:
                break
    return ordem


def aplicar_orcamento(cabecalho, secoes, orcamento):
    """Reduz o documento ao orcamento de bytes truncando as secoes menos
    criticas primeiro (indices em ORDEM_DE_CORTE), com marcacao explicita.
    secoes: lista de (texto, rotulo) na ordem do documento."""
    ORDEM_DE_CORTE = [2, 1, 0]  # fontes primeiro, diff depois, falhas por ultimo
    textos = [texto for texto, _ in secoes]

    def total():
        return len("\n".join([cabecalho] + textos).encode("utf-8", errors="replace"))

    for indice in ORDEM_DE_CORTE:
        if total() <= orcamento:
            break
        if indice >= len(textos):
            continue
        excesso = total() - orcamento
        tamanho = len(textos[indice].encode("utf-8", errors="replace"))
        # 400 bytes de folga para a marca de truncamento
        novo_tamanho = max(tamanho - excesso - 400, 0)
        if novo_tamanho < tamanho:
            textos[indice] = truncar(
                textos[indice], novo_tamanho,
                f"secao '{secoes[indice][1]}' (orcamento de tamanho do prompt)")
    return "\n".join([cabecalho] + textos)


def rodar_git(args, repo_root):
    try:
        return subprocess.run(["git"] + args, cwd=str(repo_root),
                              capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
    except OSError as erro:
        falha = subprocess.CompletedProcess(args, 1, "", str(erro))
        return falha


def obter_diff(repo_root):
    """PR atual quando ha branch base (CI); senao working tree sujo; senao
    ultimo commit."""
    base = (os.environ.get("GITHUB_BASE_REF")
            or os.environ.get("CI_MERGE_REQUEST_TARGET_BRANCH_NAME"))
    tentativas = []
    if base:
        rodar_git(["fetch", "--quiet", "origin", base], repo_root)
        tentativas.append(([f"diff", f"origin/{base}...HEAD"],
                           f"mudancas do PR contra origin/{base}"))
    status = rodar_git(["status", "--porcelain"], repo_root)
    if status.returncode == 0 and status.stdout.strip():
        tentativas.append((["diff", "HEAD"],
                           "mudancas nao commitadas (working tree vs HEAD)"))
    tentativas.append((["diff", "HEAD~1..HEAD"], "ultimo commit (HEAD~1..HEAD)"))
    tentativas.append((["show", "--format=medium", "HEAD"], "git show HEAD"))
    for args, rotulo in tentativas:
        resultado = rodar_git(args, repo_root)
        if resultado.returncode == 0 and resultado.stdout.strip():
            return rotulo, resultado.stdout
    return "indisponivel", "(diff indisponivel neste ambiente)"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, help="log do mvn test")
    parser.add_argument("--surefire-dir", help="target/surefire-reports baixado")
    parser.add_argument("--repo-root", help="raiz do repositorio (default: git)")
    parser.add_argument("--saida", default="prompt-diagnostico.md")
    parser.add_argument("--orcamento-bytes", type=int, default=0,
                        help="limite total do documento em bytes (0 = sem "
                             "limite); corta fontes primeiro, depois diff, "
                             "falhas por ultimo, com marcacao explicita")
    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.is_file():
        sys.exit(f"erro: log nao encontrado: {log_path}")
    texto_log = ler(log_path)

    if args.repo_root:
        repo_root = Path(args.repo_root).resolve()
    else:
        toplevel = rodar_git(["rev-parse", "--show-toplevel"], Path.cwd())
        repo_root = (Path(toplevel.stdout.strip())
                     if toplevel.returncode == 0 and toplevel.stdout.strip()
                     else Path.cwd())

    blocos_falha = recortar_falhas(texto_log)
    texto_falhas = podar_stack("\n\n".join(blocos_falha))

    # Dedup: um surefire cujos testes reprovados ja estao todos no recorte
    # do log so repetiria os mesmos stack traces — entra apenas uma vez.
    reprovados_no_log = testes_reprovados(texto_falhas)
    surefire, surefire_omitidos = [], []
    for nome_arquivo, texto in relatorios_surefire(args.surefire_dir):
        if testes_reprovados(texto) - reprovados_no_log:
            surefire.append((nome_arquivo, podar_stack(texto)))
        else:
            surefire_omitidos.append(nome_arquivo)

    texto_para_citacoes = texto_falhas + "\n" + "\n".join(t for _, t in surefire)
    nomes = classes_citadas(texto_para_citacoes)

    indice = indexar_fontes(repo_root)
    iniciais = []
    for nome in sorted(nomes):
        iniciais.extend(indice.get(nome, []))
    iniciais = list(dict.fromkeys(iniciais))
    fontes = expandir_relacionados(iniciais, indice)

    rotulo_diff, diff = obter_diff(repo_root)

    cabecalho = "\n".join([
        "# Contexto de diagnostico — falha na suite do stub\n",
        "Gerado por coleta_contexto.py a partir dos artefatos do job `test`. "
        "Conteudo sanitizado: segredos, e-mails e caminhos de usuario "
        "mascarados.\n",
    ])

    partes_falhas = [
        "## 1. Falhas da suite (recorte do log e stack traces)\n",
        "```text\n" + truncar(texto_falhas, MAX_BYTES_LOG, "recorte do log")
        + "\n```\n",
    ]
    for nome_arquivo, texto in surefire:
        partes_falhas.append(f"### surefire: {nome_arquivo}\n```text\n"
                             + truncar(texto, MAX_BYTES_SUREFIRE, nome_arquivo)
                             + "\n```\n")
    if surefire_omitidos:
        partes_falhas.append(
            "_(relatorios surefire omitidos por repetirem os stack traces "
            "do recorte acima: " + ", ".join(surefire_omitidos) + ")_\n")

    partes_diff = [
        f"## 2. Diff ({rotulo_diff})\n",
        "```diff\n" + truncar(diff, MAX_BYTES_DIFF, "diff") + "\n```\n",
    ]

    # Sanitiza ANTES de qualquer uso do documento (o prompt pode ser enviado
    # a um provedor externo); medidas de orcamento sempre sobre o texto limpo.
    cab_sanit = sanitizar(cabecalho)
    texto_sec1 = sanitizar("\n".join(partes_falhas))
    texto_sec2 = sanitizar("\n".join(partes_diff))

    cabeca_fontes = sanitizar("\n".join([
        "## 3. Fontes citados nos stack traces e modulos relacionados\n",
        "Prioridade: codigo de producao primeiro, depois os arquivos "
        "citados, depois o suporte — a causa-raiz pode nao estar no "
        "traceback. Cada arquivo entra POR INTEIRO; o que nao cabe no "
        "orcamento e apenas listado como omitido.\n",
    ]))

    def tam(texto):
        return len(texto.encode("utf-8", errors="replace"))

    if args.orcamento_bytes > 0:
        # O diff so pode ocupar o que sobra depois da reserva das fontes.
        maximo_diff = (args.orcamento_bytes - tam(cab_sanit)
                       - tam(texto_sec1) - tam(cabeca_fontes)
                       - RESERVA_MIN_FONTES - 400)
        if maximo_diff > 0 and tam(texto_sec2) > maximo_diff:
            texto_sec2 = truncar(texto_sec2, maximo_diff,
                                 "diff (orcamento de tamanho do prompt)") \
                + "\n```\n"
        # 400 bytes de folga para separadores e eventual marca de truncamento
        restante = (args.orcamento_bytes - tam(cab_sanit) - tam(texto_sec1)
                    - tam(texto_sec2) - tam(cabeca_fontes) - 400)
    else:
        restante = MAX_BYTES_FONTES_TOTAL

    citados_arquivos = set(iniciais)

    def prioridade(fonte):
        codigo_de_producao = 0 if "test" not in fonte.parts else 1
        citado = 0 if fonte in citados_arquivos else 1
        return (codigo_de_producao, citado, fontes.index(fonte))

    blocos_fontes, omitidos = [], []
    for fonte in sorted(fontes, key=prioridade):
        try:
            texto = ler(fonte)
        except OSError:
            continue
        try:
            rel = fonte.relative_to(repo_root)
        except ValueError:
            rel = fonte
        rel = str(rel).replace(os.sep, "/")
        bloco = sanitizar(f"### {rel}\n```java\n"
                          + truncar(texto, MAX_BYTES_POR_FONTE, rel)
                          + "\n```\n")
        if tam(bloco) <= restante:
            blocos_fontes.append(bloco)
            restante -= tam(bloco) + 1
        else:
            omitidos.append(f"{rel} ({tam(bloco)} bytes)")
    if omitidos:
        blocos_fontes.append(sanitizar(
            "_(fontes omitidos por nao caberem inteiros no orcamento: "
            + "; ".join(omitidos) + ")_\n"))

    texto_sec3 = "\n".join([cabeca_fontes] + blocos_fontes)

    # Rede de seguranca: se sec1+sec2 sozinhas ja estourarem o orcamento,
    # o corte por secao (fontes -> diff -> falhas) ainda se aplica.
    secoes = [
        (texto_sec1, "falhas da suite"),
        (texto_sec2, "diff"),
        (texto_sec3, "fontes"),
    ]
    documento = aplicar_orcamento(cab_sanit, secoes, args.orcamento_bytes) \
        if args.orcamento_bytes > 0 else \
        "\n".join([cab_sanit] + [texto for texto, _ in secoes])
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": em Windows o write_text converteria \n em \r\n e o
    # arquivo em disco estouraria o orcamento medido em LF.
    saida.write_text(documento, encoding="utf-8", newline="\n")
    print(f"prompt gravado em {saida} "
          f"({len(documento)} caracteres, {len(fontes)} fontes, "
          f"{len(surefire)} relatorios surefire, diff: {rotulo_diff})")


if __name__ == "__main__":
    main()

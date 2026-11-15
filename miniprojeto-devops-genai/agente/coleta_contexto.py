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
    surefire = relatorios_surefire(args.surefire_dir)

    texto_falhas = "\n\n".join(blocos_falha)
    texto_para_citacoes = texto_falhas + "\n" + "\n".join(t for _, t in surefire)
    nomes = classes_citadas(texto_para_citacoes)

    indice = indexar_fontes(repo_root)
    iniciais = []
    for nome in sorted(nomes):
        iniciais.extend(indice.get(nome, []))
    iniciais = list(dict.fromkeys(iniciais))
    fontes = expandir_relacionados(iniciais, indice)

    rotulo_diff, diff = obter_diff(repo_root)

    partes = [
        "# Contexto de diagnostico — falha na suite do stub\n",
        "Gerado por coleta_contexto.py a partir dos artefatos do job `test`. "
        "Conteudo sanitizado: segredos, e-mails e caminhos de usuario "
        "mascarados.\n",
        "## 1. Falhas da suite (recorte do log e stack traces)\n",
        "```text\n" + truncar(texto_falhas, MAX_BYTES_LOG, "recorte do log")
        + "\n```\n",
    ]
    for nome_arquivo, texto in surefire:
        partes.append(f"### surefire: {nome_arquivo}\n```text\n"
                      + truncar(texto, MAX_BYTES_SUREFIRE, nome_arquivo)
                      + "\n```\n")

    partes.append(f"## 2. Diff ({rotulo_diff})\n")
    partes.append("```diff\n" + truncar(diff, MAX_BYTES_DIFF, "diff") + "\n```\n")

    partes.append("## 3. Fontes citados nos stack traces e modulos relacionados\n")
    partes.append("Inclui tambem os modulos importados e os vizinhos de pacote "
                  "dos arquivos citados: a causa-raiz pode nao estar no "
                  "traceback.\n")
    total = 0
    for fonte in fontes:
        try:
            texto = ler(fonte)
        except OSError:
            continue
        try:
            rel = fonte.relative_to(repo_root)
        except ValueError:
            rel = fonte
        corpo = truncar(texto, MAX_BYTES_POR_FONTE, str(rel))
        total += len(corpo.encode("utf-8", errors="replace"))
        if total > MAX_BYTES_FONTES_TOTAL:
            partes.append("_(limite de tamanho das fontes atingido; demais "
                          "arquivos omitidos)_\n")
            break
        partes.append(f"### {str(rel).replace(os.sep, '/')}\n```java\n{corpo}\n```\n")

    documento = sanitizar("\n".join(partes))
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)
    saida.write_text(documento, encoding="utf-8")
    print(f"prompt gravado em {saida} "
          f"({len(documento)} caracteres, {len(fontes)} fontes, "
          f"{len(surefire)} relatorios surefire, diff: {rotulo_diff})")


if __name__ == "__main__":
    main()

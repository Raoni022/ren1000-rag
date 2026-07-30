"""
Bloco 1 do plano: PDF oficial da ANEEL -> texto limpo em data/ren1000_raw.txt

Rodar isoladamente, sem depender do resto do projeto:

    .venv\\Scripts\\python.exe scripts/extract_text.py --input data/ren1000.pdf --report
    .venv\\Scripts\\python.exe scripts/extract_text.py --input data/ren1000.pdf --output data/ren1000_raw.txt

O PDF de referencia e o TEXTO COMPILADO da REN 1.000/2021 impresso da pagina do CEDOC
(www2.aneel.gov.br/cedoc/ren20211000.html): 152 paginas, 679 artigos, com as alteracoes das
REN 1.059/2023, 1.081/2023, 1.095/2024 e 1.098/2024 marcadas inline no texto.


DECISOES DE EXTRACAO (medidas contra o PDF real, nao supostas)

1. extraction_mode="layout" e obrigatorio, nao preferencia.
   No modo "plain" o pypdf devolve cada pagina como UMA linha de ~5.700 caracteres, sem
   quebra nenhuma, e cola palavras vizinhas ("consumidoracom microgeracao"). Resultado
   medido: 30 artigos reconheciveis em inicio de linha. Com "layout": 679 artigos, do Art. 1
   ao Art. 679, sem buraco na sequencia, e sem palavras coladas.

2. Ligaduras tipograficas (NFKC).
   O PDF usa os glifos ﬁ/ﬂ (1.092 ocorrencias). Sem normalizar, "fiscalizacao" nao casa com
   a busca do usuario nem com o tokenizador do modelo de embedding.

3. Reparo de palavra partida pela ligadura -- ver repara_quebra_de_ligadura().
   Efeito colateral do modo layout: um espaco espurio aparece logo depois da ligadura, e
   "identificacao" saiu 49 vezes como "identific acao" (e ZERO vez inteira). Idem
   "verificacao" (51), "classificacao" (43), "notificacao" (44).

4. Cabecalho/rodape repetido: detectado, nao hardcodado (ver detectar_boilerplate).

5. Reflow de paragrafo: o layout quebra linha por largura de pagina, nao por sentido. Juntar
   essas linhas e o passo que mais importa para o Bloco 2, porque o chunking por artigo
   depende de "Art. 15" e o corpo do artigo estarem no mesmo bloco.

6. Marcadores de alteracao ("(Incluido pela REN ANEEL 1.059, de 07.02.2023)") sao PRESERVADOS
   e colados ao dispositivo que alteram. Sao a procedencia de cada trecho: e o que permite,
   no Bloco 2, distinguir texto vigente de texto revogado.


AVISO SOBRE DISPOSITIVOS REVOGADOS

O texto compilado mantem visivel o texto de dispositivos ja revogados, marcando-os com
"(Revogado pela REN ANEEL X)" -- 66 ocorrencias neste PDF. Este script NAO os remove: a
funcao dele e produzir uma transcricao fiel e auditavel do documento oficial. A separacao
entre vigente e revogado e decisao do Bloco 2 (chunking), onde cada chunk ganha metadado
proprio. O --report conta essas ocorrencias justamente para que isso nao passe batido.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:  # pragma: no cover - mensagem mais util que o traceback
    sys.exit("pypdf nao instalado. Rode: .venv\\Scripts\\python.exe -m pip install pypdf")


# --------------------------------------------------------------------------------------
# Padroes estruturais da norma
# --------------------------------------------------------------------------------------

# Inicio de uma unidade estrutural da REN. Usado para decidir onde NAO juntar linhas.
# O sufixo opcional "-A"/"-B" e essencial neste documento: o texto compilado esta cheio de
# dispositivos inseridos por resolucoes posteriores ("Art. 655-B", "XVII-A -", "§ 1o-A").
RE_INICIO_ESTRUTURA = re.compile(
    r"""^(
          Art\.\s*\d+[ºo]?(?:-[A-Z])?          # artigo, incl. "Art. 655-B"
        | §\s*\d+[ºo]?(?:-[A-Z])?              # paragrafo numerado, incl. "§ 1o-A"
        | Par[aá]grafo\s+[uú]nico              # paragrafo unico
        | [IVXLC]{1,7}(?:-[A-Z])?\s*[-–—]\s    # inciso em romano, incl. "XVII-A - "
        | [a-z]\)                              # alinea: "a)"
        | \d+\s*[-–—]\s                        # item numerado
        | (T[IÍ]TULO|CAP[IÍ]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O|ANEXO)\b
        )""",
    re.VERBOSE,
)

# Nota de alteracao do texto compilado. Nunca abre bloco: pertence ao dispositivo anterior.
RE_NOTA_ALTERACAO = re.compile(
    r"^\(\s*(Inclu[ií]d|Reda[çc][ãa]o\s+dada|Revogad|Renumerad|Vide|Vig[êe]nc)",
    re.IGNORECASE,
)

# Nota que revoga um dispositivo -- contada no relatorio como alerta.
RE_REVOGACAO = re.compile(r"\(\s*Revogad[oa]\s+pel", re.IGNORECASE)

# Linha que e apenas paginacao.
RE_SO_PAGINACAO = re.compile(
    r"^(?:p[aá]g(?:ina)?\.?\s*)?\d{1,4}(?:\s*(?:de|/)\s*\d{1,4})?$"
    r"|^fls?\.?\s*\d{1,4}$",
    re.IGNORECASE,
)

# Palavra cortada por hifen no fim da linha: "distribui-" + "cao" -> "distribuicao".
RE_HIFEN_FIM_LINHA = re.compile(r"(\w)[-‐‑]\n(\w)")

# Fim de frase/estrutura: se a linha termina assim, a quebra e provavelmente real.
RE_FIM_DE_BLOCO = re.compile(r"[.;:!?]\s*$")

RE_ARTIGO = re.compile(r"^Art\.\s*(\d+)", re.MULTILINE)

# Espaco espurio inserido pelo modo layout depois de uma ligadura. Ver a funcao abaixo.
#
# Letras em que uma palavra portuguesa praticamente nunca termina. Se o fragmento da esquerda
# termina numa delas, ele nao pode ser palavra inteira -- logo o espaco seguinte e espurio.
# NAO inclui "z": "eficaz", "feliz", "raiz" sao palavras legitimas, e incluir z faria o script
# produzir "eficazno" a partir de "eficaz no" (erro observado ao testar a regra contra o PDF).
# Tambem nao inclui l/m/n/r/s nem vogais, todas terminacoes comuns.
RE_QUEBRA_LIGADURA = re.compile(
    r"\b(\w*(?:fi|fl)\w*[bcdfgjkpqtvwxç]) ([a-zà-ÿ]{2,})\b", re.IGNORECASE
)

# Caso a parte: "-nte" partido em "-n te" ("suficien te", "insuficien te", "flutuan te").
# Terminacao em "n" e raríssima em portugues e nunca antecede o pronome "te" -- o par so
# aparece aqui como quebra.
RE_QUEBRA_NTE = re.compile(r"\b(\w*(?:fi|fl)\w*n) (te)\b", re.IGNORECASE)


# --------------------------------------------------------------------------------------
# Normalizacao de texto
# --------------------------------------------------------------------------------------

def repara_quebra_de_ligadura(texto: str) -> tuple[str, list[str]]:
    """Remonta palavras partidas por um espaco espurio depois da ligadura ﬁ/ﬂ.

    A regra e ortografica, nao uma lista de palavras: junta quando o fragmento da esquerda
    contem "fi"/"fl" (procedencia da ligadura) E termina numa letra em que palavra portuguesa
    nunca termina -- entao a esquerda nao pode ser palavra inteira e o espaco e espurio.

    E o que separa "identific ação" -> "identificação" e "conflit os" -> "conflitos" de pares
    legitimos como "fins de", "perfil de", "classificada na", "beneficia ou": nesses a esquerda
    termina em s/l/a, terminacoes normais.

    Nao tentei a alternativa obvia -- juntar quando a forma unida aparece inteira em outro
    ponto do documento --: medido, ela nao tem sinal nenhum aqui, porque a quebra ocorre em
    TODA ocorrencia da palavra ("identificação" e "suficiente" aparecem zero vez inteiras).

    Devolve (texto reparado, lista das junções feitas no formato "esquerda direita").
    A lista -- e nao so a contagem -- existe para o --report poder exibir exatamente o que foi
    alterado no texto da norma: uma correcao automatica que ninguem consegue conferir e
    indistinguivel de uma corrupcao silenciosa do documento.
    """
    juncoes: list[str] = []

    def _junta(m: re.Match[str]) -> str:
        juncoes.append(f"{m.group(1)} {m.group(2)}")
        return f"{m.group(1)}{m.group(2)}"

    texto = RE_QUEBRA_LIGADURA.sub(_junta, texto)
    texto = RE_QUEBRA_NTE.sub(_junta, texto)
    return texto, juncoes


def fragmentos_orfaos(texto: str, limite: int = 12) -> list[tuple[str, int]]:
    """Letras soltas deixadas por quebras internas que NENHUMA regra local resolve.

    O modo layout as vezes parte a palavra logo depois da primeira letra ("f aturamento",
    "c ompensacao") ou logo antes da ultima ("fie l", "financeir a"). Nao da para corrigir com
    seguranca a partir do texto ja extraido, porque:

      - o orfao pode pertencer a palavra da esquerda ou a da direita. "fie l cumprimento" e
        "garantia de fiel cumprimento", nao "fie lcumprimento";
      - o comprimento do vao nao distingue os casos: "fie    l" (4 espacos) e quebra interna,
        mas "fiel      cumprimento" (6 espacos) e fronteira legitima de palavra;
      - juntar letra maiuscula quebraria a norma, porque ali sao incisos romanos e subgrupos
        tarifarios reais ("V do", "B deve", "X ou").

    Por isso esta funcao so RELATA. A correcao de verdade e trocar o extrator -- ver a secao
    de limitacoes do README.
    """
    orfaos: Counter[str] = Counter()
    for m in re.finditer(r"(?<![\w-])([b-df-hj-np-tv-zç]) ([a-zà-ÿ]{2,})", texto):
        orfaos[f"{m.group(1)} {m.group(2)}"] += 1
    return orfaos.most_common(limite)


def candidatas_residuais(texto: str, limite: int = 15) -> list[tuple[str, int]]:
    """Pares 'palavra fragmento' que sobraram e talvez sejam quebras nao tratadas.

    Nao corrige nada -- serve para o --report mostrar o que ainda merece olho humano, em vez
    de eu assumir que a regra acima cobre 100% do documento.
    """
    suspeitas: Counter[str] = Counter()
    for m in re.finditer(r"\b(\w*(?:fi|fl)\w{0,5}) ([a-zà-ÿ]{2,7})\b", texto, re.IGNORECASE):
        esquerda, direita = m.group(1), m.group(2)
        if esquerda[-1].lower() in "bcdfgjkpqtvwxç":
            continue  # ja tratado por repara_quebra_de_ligadura
        suspeitas[f"{esquerda} {direita}"] += 1
    return suspeitas.most_common(limite)


# --------------------------------------------------------------------------------------
# Etapas
# --------------------------------------------------------------------------------------

# Indicadores ordinais preservados atraves do NFKC. Sem isso "nº 1.031" viraria "no 1.031" e
# "1º de julho" viraria "1o de julho": o NFKC decompoe º->o e ª->a. Como a interface vai exibir
# o trecho original da norma para o usuario conferir, essa fidelidade tipografica importa.
_SENTINELAS_ORDINAIS = {"º": "", "ª": ""}


def normalizar_unicode(texto: str) -> str:
    """Aplica NFKC (resolve as ligaduras ﬁ/ﬂ) sem destruir os indicadores ordinais º/ª."""
    for original, sentinela in _SENTINELAS_ORDINAIS.items():
        texto = texto.replace(original, sentinela)
    texto = unicodedata.normalize("NFKC", texto)
    for original, sentinela in _SENTINELAS_ORDINAIS.items():
        texto = texto.replace(sentinela, original)
    return texto


def extrair_paginas(caminho_pdf: Path, modo: str) -> list[str]:
    """Le o PDF e devolve o texto de cada pagina, ja com a normalizacao unicode aplicada."""
    leitor = PdfReader(str(caminho_pdf))
    paginas: list[str] = []
    for pagina in leitor.pages:
        bruto = pagina.extract_text(extraction_mode=modo) or ""
        paginas.append(normalizar_unicode(bruto))
    return paginas


def _normalizar_para_comparacao(linha: str) -> str:
    """Chave de comparacao entre paginas: minusculo, espacos colapsados, digitos mascarados.

    Mascarar digitos e o que permite reconhecer que "Pagina 3 de 210" e "Pagina 4 de 210"
    sao o mesmo rodape.
    """
    return re.sub(r"\d+", "#", " ".join(linha.lower().split()))


def _pode_ser_boilerplate(linha: str) -> bool:
    """Salvaguarda: uma linha que inicia estrutura da norma NUNCA e cabecalho/rodape.

    Sem isso o mascaramento de digitos de _normalizar_para_comparacao() pode fazer duas
    linhas de conteudo que diferem apenas por numeros colidirem na mesma chave e serem
    descartadas como rodape -- ou seja, o script apagaria artigos da norma em silencio.
    Perder um artigo e muito pior do que deixar passar uma linha de cabecalho.
    """
    return not RE_INICIO_ESTRUTURA.match(linha.strip())


def detectar_boilerplate(
    paginas: list[str], ratio_minimo: float, linhas_por_borda: int
) -> set[str]:
    """Devolve as chaves normalizadas de linhas que se repetem no topo/base das paginas.

    Só olha as primeiras e ultimas `linhas_por_borda` linhas de cada pagina: uma frase que
    por coincidencia se repete no meio do texto da norma nao deve ser tratada como rodape.
    """
    contador: Counter[str] = Counter()
    for pagina in paginas:
        linhas = [linha for linha in pagina.splitlines() if linha.strip()]
        bordas = linhas[:linhas_por_borda] + linhas[-linhas_por_borda:]
        # set() para uma linha repetida na mesma pagina nao contar duas vezes.
        contador.update(
            {
                _normalizar_para_comparacao(linha)
                for linha in bordas
                if _pode_ser_boilerplate(linha)
            }
        )

    limite = max(2, int(len(paginas) * ratio_minimo))
    return {chave for chave, n in contador.items() if n >= limite}


def limpar_pagina(
    pagina: str, boilerplate: set[str], remover_paginacao: bool
) -> tuple[str, int]:
    """Remove boilerplate/paginacao e colapsa o espacamento justificado do modo layout.

    Devolve (texto, linhas_removidas).
    """
    mantidas: list[str] = []
    removidas = 0

    for linha in pagina.splitlines():
        # O modo layout usa multiplos espacos para posicionar o texto na pagina.
        despida = " ".join(linha.split())
        if not despida:
            mantidas.append("")
            continue
        if (
            _pode_ser_boilerplate(despida)
            and _normalizar_para_comparacao(despida) in boilerplate
        ):
            removidas += 1
            continue
        if remover_paginacao and RE_SO_PAGINACAO.match(despida):
            removidas += 1
            continue
        mantidas.append(despida)

    return "\n".join(mantidas), removidas


def reflow(texto: str) -> str:
    """Junta linhas quebradas pela largura da pagina, preservando as quebras estruturais.

    Regra: junta a linha atual com a seguinte, EXCETO quando a seguinte inicia uma estrutura
    da norma (Art., paragrafo, inciso, alinea, titulo) ou quando ha linha em branco entre elas.
    Nota de alteracao ("(Incluido pela REN ...)") sempre cola no dispositivo anterior.
    """
    texto = RE_HIFEN_FIM_LINHA.sub(r"\1\2", texto)

    saida: list[str] = []

    for linha in texto.split("\n"):
        atual = linha.strip()

        if not atual:
            # Linha em branco: fecha o paragrafo corrente.
            if saida and saida[-1] != "":
                saida.append("")
            continue

        tem_anterior = bool(saida) and saida[-1] != ""

        # A nota de alteracao e a procedencia do dispositivo anterior: nunca abre bloco,
        # mesmo que o dispositivo tenha terminado em ponto.
        if RE_NOTA_ALTERACAO.match(atual) and tem_anterior:
            saida[-1] = f"{saida[-1]} {atual}"
            continue

        comeca_estrutura = bool(RE_INICIO_ESTRUTURA.match(atual))
        pode_continuar = tem_anterior and not comeca_estrutura

        if pode_continuar and not RE_FIM_DE_BLOCO.search(saida[-1]):
            saida[-1] = f"{saida[-1]} {atual}"
        elif pode_continuar and not atual[0].isupper():
            # Linha anterior terminou em ponto, mas esta comeca em minuscula: era abreviacao
            # no meio da frase (ex.: "inc. II do art. 5o"), nao fim de paragrafo.
            saida[-1] = f"{saida[-1]} {atual}"
        else:
            if comeca_estrutura and tem_anterior:
                saida.append("")
            saida.append(atual)

    resultado = "\n".join(saida)
    resultado = re.sub(r"[ \t]{2,}", " ", resultado)
    resultado = re.sub(r"\n{3,}", "\n\n", resultado)
    return resultado.strip() + "\n"


def relatorio_artigos(texto: str) -> tuple[list[int], list[int]]:
    """Devolve (numeros de artigo encontrados, buracos na sequencia).

    Buraco = numero ausente entre o menor e o maior artigo detectado. E o sinal mais direto
    de que a extracao ou o reflow perderam conteudo.
    """
    numeros = sorted({int(n) for n in RE_ARTIGO.findall(texto)})
    if not numeros:
        return [], []
    faltando = [n for n in range(numeros[0], numeros[-1] + 1) if n not in set(numeros)]
    return numeros, faltando


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Extrai e limpa o texto da REN ANEEL 1.000/2021 a partir do PDF oficial."
    )
    parser.add_argument("--input", required=True, type=Path, help="PDF de entrada.")
    parser.add_argument(
        "--output", type=Path, default=Path("data/ren1000_raw.txt"), help="TXT de saida."
    )
    parser.add_argument(
        "--report",
        action="store_true",
        help="Só imprime estatisticas da extracao, sem escrever o arquivo de saida.",
    )
    parser.add_argument(
        "--mode",
        choices=("layout", "plain"),
        default="layout",
        help="Modo de extracao do pypdf. 'layout' e o correto para este PDF; 'plain' existe "
        "so para comparar (perde as quebras de linha e cola palavras).",
    )
    parser.add_argument(
        "--boilerplate-ratio",
        type=float,
        default=0.5,
        help="Fracao de paginas em que uma linha de borda precisa aparecer para ser "
        "tratada como cabecalho/rodape (padrao: 0.5). Use 1.1 para desligar.",
    )
    parser.add_argument(
        "--edge-lines",
        type=int,
        default=3,
        help="Quantas linhas do topo e da base de cada pagina considerar (padrao: 3).",
    )
    parser.add_argument(
        "--keep-page-numbers",
        action="store_true",
        help="Nao remover linhas que sao apenas numeracao de pagina.",
    )
    parser.add_argument(
        "--no-reflow",
        action="store_true",
        help="Nao juntar as linhas quebradas pela largura da pagina (util para debug).",
    )
    parser.add_argument(
        "--no-ligature-fix",
        action="store_true",
        help="Nao remontar palavras partidas por ligadura (util para medir o efeito).",
    )
    parser.add_argument(
        "--show-joins",
        action="store_true",
        help="Listar todas as palavras remontadas, com frequencia. Use para auditar o que o "
        "script alterou no texto da norma antes de confiar na saida.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERRO: nao encontrei {args.input}", file=sys.stderr)
        print(
            "Baixe o TEXTO COMPILADO da REN 1.000/2021 no CEDOC da ANEEL e salve nesse "
            "caminho. Atencao: o PDF original de 2021 esta desatualizado -- a REN "
            "1.059/2023 alterou as regras de micro e minigeracao distribuida.",
            file=sys.stderr,
        )
        return 1

    paginas = extrair_paginas(args.input, args.mode)
    if not paginas:
        print("ERRO: PDF sem paginas legiveis.", file=sys.stderr)
        return 1

    chars_brutos = sum(len(p) for p in paginas)
    if chars_brutos < 100 * len(paginas):
        print(
            "AVISO: quase nenhum texto extraido -- o PDF provavelmente e digitalizado "
            "(imagem). Nesse caso precisaria de OCR, e vale procurar outra fonte do "
            "texto compilado antes.",
            file=sys.stderr,
        )

    boilerplate = detectar_boilerplate(paginas, args.boilerplate_ratio, args.edge_lines)

    partes: list[str] = []
    total_removidas = 0
    for pagina in paginas:
        limpa, removidas = limpar_pagina(
            pagina, boilerplate, remover_paginacao=not args.keep_page_numbers
        )
        total_removidas += removidas
        if limpa.strip():
            partes.append(limpa)

    texto = "\n".join(partes)

    juncoes: list[str] = []
    if not args.no_ligature_fix:
        texto, juncoes = repara_quebra_de_ligadura(texto)

    if not args.no_reflow:
        texto = reflow(texto)

    numeros, faltando = relatorio_artigos(texto)
    revogacoes = len(RE_REVOGACAO.findall(texto))

    print(f"Modo de extracao ........... {args.mode}")
    print(f"Paginas lidas .............. {len(paginas)}")
    print(f"Caracteres brutos .......... {chars_brutos:,}")
    print(f"Caracteres apos limpeza .... {len(texto):,}")
    print(f"Linhas de boilerplate ...... {total_removidas} "
          f"({len(boilerplate)} padroes distintos)")
    print(f"Palavras remontadas ........ {len(juncoes)} "
          f"({len(set(juncoes))} distintas, quebra por ligadura)")
    print(f"Blocos de texto ............ {len([b for b in texto.split(chr(10)) if b])}")
    print(f"Artigos detectados ......... {len(numeros)}", end="")
    if numeros:
        print(f" (Art. {numeros[0]} ao Art. {numeros[-1]})")
    else:
        print()
    if faltando:
        amostra = ", ".join(str(n) for n in faltando[:20])
        sufixo = " ..." if len(faltando) > 20 else ""
        print(f"ATENCAO: {len(faltando)} artigo(s) ausente(s) na sequencia: {amostra}{sufixo}")
    elif numeros:
        print("Sequencia de artigos ....... sem buracos")

    if revogacoes:
        print(
            f"\nATENCAO: {revogacoes} dispositivo(s) marcado(s) como revogado permanecem no "
            f"texto.\n  O texto compilado da ANEEL mantem o conteudo revogado visivel. Este "
            f"script preserva\n  isso de proposito (transcricao fiel). Separar vigente de "
            f"revogado e tarefa do Bloco 2:\n  sem isso, o RAG pode citar artigo correto com "
            f"conteudo que nao vale mais."
        )

    if juncoes and args.show_joins:
        print("\nJuncoes aplicadas ao texto da norma (esquerda + direita -> resultado):")
        for termo, n in Counter(juncoes).most_common():
            print(f"  {n:>4}x  {termo!r} -> {termo.replace(' ', '')!r}")

    orfaos = fragmentos_orfaos(texto)
    if orfaos:
        total = sum(n for _, n in orfaos)
        print(
            f"\nLIMITACAO CONHECIDA: {total}+ palavra(s) partida(s) por letra solta, sem "
            f"correcao segura.\n  O modo layout parte a palavra na primeira ou na ultima "
            f"letra e nao ha sinal que\n  distinga isso de fronteira legitima. Afeta termos "
            f"centrais da norma. Ver README."
        )
        for termo, n in orfaos:
            print(f"  {n:>4}x  {termo!r}")

    residuais = candidatas_residuais(texto)
    if residuais:
        print("\nPares suspeitos de quebra NAO tratada (revisar se sao palavras legitimas):")
        for termo, n in residuais:
            print(f"  {n:>4}x  {termo}")

    if boilerplate:
        print("\nPadroes tratados como cabecalho/rodape:")
        for chave in sorted(boilerplate):
            print(f"  - {chave[:100]}")

    if args.report:
        print("\n(--report: nada foi escrito em disco)")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n" explicito: sem isso o Windows grava CRLF e o artefato versionado fica
    # diferente conforme a maquina que rodou o script.
    args.output.write_text(texto, encoding="utf-8", newline="\n")
    print(f"\nEscrito: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

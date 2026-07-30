"""
Bloco 2 do plano: data/ren1000_raw.txt -> index/chunks.json

Rodar isoladamente:

    .venv\\Scripts\\python.exe scripts/chunk_text.py --report
    .venv\\Scripts\\python.exe scripts/chunk_text.py --output index/chunks.json


POR QUE NEM DISPOSITIVO NEM ARTIGO INTEIRO

Medido no texto extraido (717 artigos, contando os inseridos com sufixo -A/-B):

  - por dispositivo isolado: mediana de 146 caracteres. Granular demais. "II - permitir a
    leitura" nao significa nada fora do caput que o rege, e um chunk desses recuperado
    sozinho leva o LLM a responder sem saber do que se trata.
  - por artigo inteiro: mediana de 523, mas 52% passam de 500 caracteres e o Art. 2
    (definicoes) tem 20.122. Um vetor unico para 20 mil caracteres dilui o significado a
    ponto de nao ser recuperavel por pergunta especifica.

A unidade adotada e o DISPOSITIVO COM SEUS SUBORDINADOS: o caput com os incisos que dependem
dele, cada paragrafo com os seus. Unidades do mesmo artigo sao empacotadas juntas ate o
limite de --max-chars, sem nunca partir uma unidade ao meio -- partir um inciso do seu caput
e o mesmo erro de granularidade, so que introduzido por nos.


VIGENTE E REVOGADO NUNCA DIVIDEM O MESMO CHUNK

O texto compilado da ANEEL mantem visivel o conteudo ja revogado, marcado com "(Revogado
pela REN ANEEL X)". Aqui cada dispositivo revogado vira chunk PROPRIO, com vigente=false.

Isso e o ponto do bloco inteiro: se um chunk misturasse texto vigente e revogado, a flag
seria inutil e o RAG responderia com artigo correto e conteudo que nao vale mais -- falha que
nenhum ajuste de prompt corrige, porque esta na camada de dados. O retriever (Bloco 4) filtra
por essa flag.


DOIS CAMPOS DE TEXTO, DE PROPOSITO

  texto        -- o trecho da norma, literal, para exibir ao usuario conferir.
  texto_busca  -- o mesmo trecho precedido da trilha estrutural e do caput do artigo.

O Bloco 3 gera embedding de texto_busca e a interface mostra texto. Um paragrafo como "§ 2º O
prazo e de 30 dias" so e recuperavel por "prazo de analise de pedido de acesso" se o vetor
tambem carregar de que artigo e capitulo ele veio.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

# --------------------------------------------------------------------------------------
# Estrutura da norma
# --------------------------------------------------------------------------------------

# "Art. 15." / "Art. 655-C." -- o sufixo marca dispositivo inserido por resolucao posterior.
RE_ARTIGO = re.compile(r"^Art\.\s*(\d+(?:-[A-Z]{1,2})?)\s*[.º°]?\s")

# Abre unidade nova dentro do artigo.
RE_PARAGRAFO = re.compile(r"^(§\s*\d+[º°]?(?:-[A-Z])?|Par[áa]grafo\s+[úu]nico)")

# Subordinados: dependem da unidade anterior e nunca viram unidade propria.
RE_SUBORDINADO = re.compile(
    r"^([IVXLC]{1,7}(?:-[A-Z])?\s*[-–—]\s|[a-z]\)|\d+\s*[-–—]\s)"
)

RE_CABECALHO = re.compile(
    r"^(T[ÍI]TULO|CAP[ÍI]TULO|SE[ÇC][ÃA]O|SUBSE[ÇC][ÃA]O|Se[çc][ãa]o|Subse[çc][ãa]o|ANEXO)\b"
)

# Divide "CAPÍTULO I DAS DISPOSIÇÕES GERAIS Seção I Do Objeto" nos seus niveis. O reflow do
# Bloco 1 junta niveis consecutivos numa linha so quando eles vem seguidos no PDF.
RE_NIVEL = re.compile(
    r"(T[ÍI]TULO|CAP[ÍI]TULO|SUBSE[ÇC][ÃA]O|Subse[çc][ãa]o|SE[ÇC][ÃA]O|Se[çc][ãa]o|ANEXO)"
    r"\s+([IVXLC]+|[ÚU]NICA?|\d+)\b"
)

_ORDEM_NIVEL = {"titulo": 0, "capitulo": 1, "secao": 2, "subsecao": 3}

RE_REVOGADO = re.compile(r"\(\s*Revogad[oa]\s+pel", re.IGNORECASE)
RE_REDACAO_DADA = re.compile(r"\(\s*Reda[çc][ãa]o\s+dada\s+pel", re.IGNORECASE)

# Rotulo que abre um dispositivo, usado para reconhecer duas versoes do MESMO dispositivo.
RE_ROTULO = re.compile(
    r"^(Art\.\s*\d+(?:-[A-Z]{1,2})?|§\s*\d+[º°]?(?:-[A-Z])?|Par[áa]grafo\s+[úu]nico"
    r"|[IVXLC]{1,7}(?:-[A-Z])?\s*[-–—]|[a-z]\))"
)

SITUACAO_VIGENTE = "vigente"
SITUACAO_REVOGADO = "revogado"
SITUACAO_SUPERADO = "redacao_anterior"


def _rotulo(bloco: str) -> str | None:
    m = RE_ROTULO.match(bloco)
    return " ".join(m.group(1).split()).rstrip(".") if m else None


def _nivel(bloco: str) -> int:
    """Profundidade do dispositivo: artigo 0, paragrafo 1, inciso 2, alinea 3, texto solto 4.

    Serve para delimitar o alcance de um dispositivo: ele termina quando comeca um irmao (mesmo
    nivel) ou algo de nivel superior. Tudo que vier com nivel maior lhe e subordinado.
    """
    if RE_ARTIGO.match(bloco):
        return 0
    if RE_PARAGRAFO.match(bloco):
        return 1
    if re.match(r"^[IVXLC]{1,7}(?:-[A-Z])?\s*[-–—]\s", bloco):
        return 2
    if re.match(r"^[a-z]\)", bloco):
        return 3
    return 4


def marcar_superados(blocos: list[str]) -> list[bool]:
    """Marca as redacoes ANTIGAS que o texto compilado mantem visiveis sem marcador algum.

    Este e o problema mais perigoso do documento, e o mais silencioso. Quando uma resolucao da
    nova redacao a um dispositivo, a pagina do CEDOC mostra as DUAS versoes em sequencia: a
    antiga primeiro, sem marca nenhuma, e a nova logo depois com "(Redação dada pela REN
    ANEEL X)". Exemplo real, Art. 96:

        Art. 96. No caso de conexao de outra distribuidora [...]
        Art. 96. No caso de conexao de outra distribuidora [...] que nao utilize o processo
                 simplificado da CCEE [...] (Redação dada pela REN ANEEL 1.110, de 10.12.2024)

    Indexar a primeira significa responder com numero de artigo correto e texto que nao vale
    mais -- sem nenhum marcador no trecho que denuncie o erro, diferente do caso "(Revogado)".

    A deteccao e POSICIONAL e delimitada por hierarquia, nao por contagem de rotulos ao longo
    do documento -- essa produziria falso positivo, porque alineas "a)" e "b)" se repetem
    legitimamente sob incisos diferentes (so no Art. 2 ha uma duzia de "a)" sem relacao entre
    si).

    As duas versoes nem sempre sao adjacentes: no Art. 144 a redacao antiga vem acompanhada
    dos seus proprios incisos antes de a nova comecar, e esses incisos tambem estao superados.

        [1139] Art. 144. Quando houver recusa injustificada [...]        <- superado
        [1140] I - notificar o consumidor [...]                          <- superado (do antigo)
        [1141] Art. 144. Quando houver recusa [...] (Redação dada [...])  <- vigente
        [1142] I - notificar [...] (Redação dada pela REN ANEEL 1.095)   <- vigente

    Por isso a varredura avanca enquanto encontra subordinados (nivel maior) e para no primeiro
    irmao ou superior. Se esse irmao for o mesmo dispositivo com "Redação dada", tudo que veio
    antes dele desde a versao antiga esta superado.
    """
    superados = [False] * len(blocos)

    for i, bloco in enumerate(blocos):
        rotulo = _rotulo(bloco)
        if not rotulo or RE_REDACAO_DADA.search(bloco):
            continue

        nivel = _nivel(bloco)
        j = i + 1
        while j < len(blocos) and _nivel(blocos[j]) > nivel:
            j += 1  # subordinado da versao antiga

        if j >= len(blocos) or _rotulo(blocos[j]) != rotulo:
            continue  # o proximo irmao e outro dispositivo: nao ha duas versoes
        if not RE_REDACAO_DADA.search(blocos[j]):
            continue

        for k in range(i, j):
            superados[k] = True

    return superados

# "(Incluído pela REN ANEEL 1.059, de 07.02.2023)" -> "REN ANEEL 1.059/2023"
RE_NORMA_ALTERADORA = re.compile(
    r"REN\s+ANEEL\s+([\d.]+),\s*de\s*\d{2}\.\d{2}\.(\d{4})", re.IGNORECASE
)


# Nota de alteracao grudada no nome de um cabecalho estrutural, ex.:
# "CAPÍTULO XI DA MICROGERAÇÃO [...] (Incluído pela REN ANEEL 1.059, de 07.02.2023)".
RE_NOTA_EM_TITULO = re.compile(
    r"\s*\(\s*(?:Inclu[ií]d|Reda[çc][ãa]o\s+dada|Revogad|Renumerad)[^)]*\)\s*$",
    re.IGNORECASE,
)


def _limpar_titulo(nome: str) -> str:
    """Tira a nota de alteracao do nome de um titulo/capitulo/secao.

    A trilha entra no texto_busca de TODO chunk do capitulo, entao a nota seria repetida
    centenas de vezes no indice: gasta janela do modelo de embedding e dilui o vetor com
    tokens que nao tem a ver com o assunto do dispositivo. A informacao nao se perde -- a
    procedencia de cada trecho continua no campo 'alteracoes'.
    """
    anterior = None
    while anterior != nome:
        anterior = nome
        nome = RE_NOTA_EM_TITULO.sub("", nome).strip()
    return nome


def _normalizar_nivel(marcador: str) -> str:
    m = marcador.lower()
    if m.startswith("t"):
        return "titulo"
    if m.startswith("cap"):
        return "capitulo"
    if m.startswith("subse"):
        return "subsecao"
    if m.startswith("se"):
        return "secao"
    return "anexo"


def atualizar_hierarquia(linha: str, hierarquia: dict[str, str]) -> dict[str, str]:
    """Aplica um cabecalho estrutural a trilha corrente e devolve a trilha nova.

    Abrir um nivel invalida os mais profundos: uma Seção nova nao herda a Subseção da Seção
    anterior. Sem isso a trilha de um artigo do Capitulo XI viria com a subsecao errada.
    """
    nova = dict(hierarquia)
    marcas = list(RE_NIVEL.finditer(linha))
    if not marcas:
        return nova

    for i, m in enumerate(marcas):
        nivel = _normalizar_nivel(m.group(1))
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(linha)
        nome = _limpar_titulo(linha[m.end():fim].strip(" .:-"))
        rotulo = f"{m.group(1).title()} {m.group(2)}"
        nova[nivel] = f"{rotulo} - {nome}" if nome else rotulo
        for outro, ordem in _ORDEM_NIVEL.items():
            if ordem > _ORDEM_NIVEL.get(nivel, 99):
                nova.pop(outro, None)
    return nova


def normas_alteradoras(texto: str) -> list[str]:
    """Resolucoes citadas nas notas de alteracao do trecho, sem repetir."""
    vistas: list[str] = []
    for numero, ano in RE_NORMA_ALTERADORA.findall(texto):
        ref = f"REN ANEEL {numero}/{ano}"
        if ref not in vistas:
            vistas.append(ref)
    return vistas


# --------------------------------------------------------------------------------------
# Parsing: texto -> artigos -> unidades
# --------------------------------------------------------------------------------------

class Unidade:
    """Um dispositivo com os subordinados que dependem dele (caput + incisos, § + alineas)."""

    def __init__(self, cabeca: str, tipo: str, superado: bool = False) -> None:
        self.linhas = [cabeca]
        self.tipo = tipo  # "caput" | "paragrafo" | "solto"
        self._superado = superado

    @property
    def texto(self) -> str:
        return "\n".join(self.linhas)

    @property
    def situacao(self) -> str:
        """Situacao determinada pela CABECA da unidade.

        Um inciso revogado dentro de um caput vigente nao torna o caput revogado -- ele vira
        unidade propria no parser, justamente para nao contaminar o restante.
        """
        if RE_REVOGADO.search(self.linhas[0]):
            return SITUACAO_REVOGADO
        if self._superado:
            return SITUACAO_SUPERADO
        return SITUACAO_VIGENTE


class Artigo:
    def __init__(self, rotulo: str, hierarquia: dict[str, str]) -> None:
        self.rotulo = rotulo
        self.hierarquia = hierarquia
        self.unidades: list[Unidade] = []

    @property
    def caput(self) -> str:
        return self.unidades[0].linhas[0] if self.unidades else ""


def parsear(blocos: list[str]) -> tuple[list[Artigo], list[str]]:
    """Devolve (artigos, blocos de preambulo anteriores ao Art. 1)."""
    artigos: list[Artigo] = []
    preambulo: list[str] = []
    hierarquia: dict[str, str] = {}
    atual: Artigo | None = None
    superados = marcar_superados(blocos)

    for i, bloco in enumerate(blocos):
        if RE_CABECALHO.match(bloco):
            hierarquia = atualizar_hierarquia(bloco, hierarquia)
            # Cabecalho encerra o artigo corrente: o que vier depois pertence a nova secao.
            atual = None
            continue

        m = RE_ARTIGO.match(bloco)
        if m:
            atual = Artigo(f"Art. {m.group(1)}", dict(hierarquia))
            atual.unidades.append(Unidade(bloco, "caput", superados[i]))
            artigos.append(atual)
            continue

        if atual is None:
            preambulo.append(bloco)
            continue

        # Dispositivo revogado ou de redacao superada sempre abre unidade propria, mesmo sendo
        # subordinado: e o que impede esse texto de entrar no mesmo chunk que texto vigente.
        if RE_PARAGRAFO.match(bloco):
            atual.unidades.append(Unidade(bloco, "paragrafo", superados[i]))
        elif RE_REVOGADO.search(bloco) or superados[i]:
            atual.unidades.append(Unidade(bloco, "solto", superados[i]))
        else:
            if atual.unidades and atual.unidades[-1].situacao == SITUACAO_VIGENTE:
                atual.unidades[-1].linhas.append(bloco)
            else:
                atual.unidades.append(Unidade(bloco, "solto"))

    return artigos, preambulo


# --------------------------------------------------------------------------------------
# Chunking
# --------------------------------------------------------------------------------------

class Fragmento:
    """Pedaco de uma unidade ja pronto para virar chunk (ou ser empacotado com vizinhos)."""

    def __init__(self, texto: str, situacao: str, tipo: str, n_dispositivos: int) -> None:
        self.texto = texto
        self.situacao = situacao
        self.tipo = tipo
        self.n_dispositivos = n_dispositivos


def fragmentar(unidade: Unidade, max_chars: int, alvo: int | None = None) -> list[Fragmento]:
    """Divide uma unidade grande demais, REPETINDO a cabeca em cada pedaco.

    O Art. 2 e o caso que exige isso: um caput ("sao adotadas as seguintes definicoes:")
    seguido de ~110 incisos, 20 mil caracteres numa unidade so. Um vetor unico para isso nao
    e recuperavel por pergunta especifica.

    Repetir a cabeca -- em vez de emitir os incisos soltos -- e o que mantem a propriedade que
    justifica este bloco: nenhum inciso vai para o indice sem o caput que lhe da sentido. O
    custo e duplicar o caput em alguns chunks, o que e barato e ajuda a busca.
    """
    if len(unidade.texto) <= max_chars or len(unidade.linhas) == 1:
        return [Fragmento(unidade.texto, unidade.situacao, unidade.tipo, 1)]

    # `alvo` permite fatiar mais fino do que o teto de empacotamento. Faz diferenca no Art. 2,
    # onde os subordinados sao definicoes independentes entre si: juntar quatro delas num
    # chunk faz o vetor virar a media de quatro assuntos distintos.
    teto = alvo or max_chars
    cabeca = unidade.linhas[0]
    partes: list[Fragmento] = []
    atual: list[str] = []
    tamanho = len(cabeca)

    for subordinado in unidade.linhas[1:]:
        if atual and tamanho + len(subordinado) > teto:
            partes.append(
                Fragmento("\n".join([cabeca] + atual), unidade.situacao, unidade.tipo, len(atual))
            )
            atual, tamanho = [], len(cabeca)
        atual.append(subordinado)
        tamanho += len(subordinado)

    if atual:
        partes.append(
            Fragmento("\n".join([cabeca] + atual), unidade.situacao, unidade.tipo, len(atual))
        )
    return partes


def agrupar(
    unidades: list[Unidade], max_chars: int, alvo_fragmento: int | None = None
) -> list[list[Fragmento]]:
    """Fragmenta o que e grande demais e empacota o resto ate max_chars.

    Nunca mistura situacoes no mesmo grupo: e o que mantem o metadado util no Bloco 4. Um
    chunk que juntasse texto vigente e revogado nao poderia ser filtrado nem exibido sem
    induzir o usuario a erro.
    """
    fragmentos: list[Fragmento] = []
    for unidade in unidades:
        fragmentos.extend(fragmentar(unidade, max_chars, alvo_fragmento))

    grupos: list[list[Fragmento]] = []
    atual: list[Fragmento] = []
    tamanho = 0

    for fragmento in fragmentos:
        n = len(fragmento.texto)
        mistura_vigencia = bool(atual) and atual[-1].situacao != fragmento.situacao
        if atual and (tamanho + n > max_chars or mistura_vigencia):
            grupos.append(atual)
            atual, tamanho = [], 0
        atual.append(fragmento)
        tamanho += n

    if atual:
        grupos.append(atual)
    return grupos


def montar_chunks(
    artigos: list[Artigo], max_chars: int, alvo_fragmento: int | None = None
) -> list[dict]:
    chunks: list[dict] = []

    for artigo in artigos:
        for grupo in agrupar(artigo.unidades, max_chars, alvo_fragmento):
            texto = "\n".join(f.texto for f in grupo)
            situacao = grupo[0].situacao  # agrupar() garante grupo homogeneo

            trilha = [artigo.hierarquia[k] for k in ("titulo", "capitulo", "secao", "subsecao")
                      if k in artigo.hierarquia]

            # O caput so entra no texto_busca quando o chunk nao o contem: e o contexto minimo
            # para o trecho ser recuperavel por uma pergunta que nao cite o numero do artigo.
            contexto = "" if grupo[0].tipo == "caput" else artigo.caput
            partes_busca = [f"{artigo.rotulo} ({' > '.join(trilha)})" if trilha else artigo.rotulo]
            if contexto:
                partes_busca.append(contexto)
            partes_busca.append(texto)

            chunks.append({
                "id": f"{artigo.rotulo.replace('Art. ', 'art')}#{len(chunks)}",
                "artigo": artigo.rotulo,
                "trilha": trilha,
                "situacao": situacao,
                "vigente": situacao == SITUACAO_VIGENTE,
                "alteracoes": normas_alteradoras(texto),
                "n_dispositivos": sum(f.n_dispositivos for f in grupo),
                "texto": texto,
                "texto_busca": "\n".join(partes_busca),
            })

    return chunks


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Divide o texto da REN 1.000/2021 em chunks por dispositivo."
    )
    parser.add_argument("--input", type=Path, default=Path("data/ren1000_raw.txt"))
    parser.add_argument("--output", type=Path, default=Path("index/chunks.json"))
    parser.add_argument(
        "--max-chars",
        type=int,
        default=1200,
        help="Teto por chunk (padrao: 1200). Precisa caber na janela do modelo de embedding "
        "do Bloco 3: ~450 chars para uma janela de 128 tokens, ~1800 para 512.",
    )
    parser.add_argument(
        "--fragment-chars",
        type=int,
        default=None,
        help="Teto ao fatiar uma unidade grande demais (padrao: o mesmo de --max-chars). "
        "Valor menor separa subordinados independentes entre si, como as definicoes do Art. 2.",
    )
    parser.add_argument("--report", action="store_true", help="Só relata, nao escreve.")
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERRO: nao encontrei {args.input}. Rode antes scripts/extract_text.py",
              file=sys.stderr)
        return 1

    blocos = [b for b in args.input.read_text(encoding="utf-8").split("\n") if b.strip()]
    artigos, preambulo = parsear(blocos)
    chunks = montar_chunks(artigos, args.max_chars, args.fragment_chars)

    tamanhos = sorted(len(c["texto"]) for c in chunks)
    por_situacao = Counter(c["situacao"] for c in chunks)
    acima = [c for c in chunks if len(c["texto"]) > args.max_chars]

    print(f"Blocos de entrada .......... {len(blocos)}")
    print(f"Preambulo (fora de artigo) . {len(preambulo)} blocos")
    print(f"Artigos .................... {len(artigos)}")
    print(f"Chunks ..................... {len(chunks)}")
    print(f"  vigentes ................. {por_situacao[SITUACAO_VIGENTE]}")
    print(f"  revogados ................ {por_situacao[SITUACAO_REVOGADO]}")
    print(f"  redacao anterior ......... {por_situacao[SITUACAO_SUPERADO]} "
          f"(superada por 'Redação dada')")
    print(f"Tamanho do chunk (chars):")
    print(f"  mediana .................. {statistics.median(tamanhos):.0f}")
    print(f"  p90 / p99 ................ {tamanhos[int(len(tamanhos) * .9)]} / "
          f"{tamanhos[int(len(tamanhos) * .99)]}")
    print(f"  maior .................... {max(tamanhos)}")
    print(f"  acima do teto ............ {len(acima)} (dispositivo indivisivel)")

    # Guarda: rotulo de artigo que aparece mais de uma vez sem que uma das versoes seja
    # redacao superada. O padrao esperado neste documento e sempre "antiga + nova"; se algo
    # fugir disso, a deteccao de marcar_superados() nao cobriu o caso e precisa de revisao.
    versoes_por_artigo = Counter(a.rotulo for a in artigos)
    suspeitos = []
    for rotulo, n in versoes_por_artigo.items():
        if n > 1:
            situacoes = {c["situacao"] for c in chunks if c["artigo"] == rotulo}
            if SITUACAO_SUPERADO not in situacoes:
                suspeitos.append(rotulo)
    if suspeitos:
        print(f"\nATENCAO: {len(suspeitos)} artigo(s) com versoes duplicadas sem redacao "
              f"anterior detectada: {suspeitos[:8]}")
        print("  Revisar: pode haver texto superado indexado como vigente.")

    sem_trilha = [c for c in chunks if not c["trilha"]]
    if sem_trilha:
        print(f"\nAVISO: {len(sem_trilha)} chunk(s) sem trilha estrutural: "
              f"{[c['artigo'] for c in sem_trilha[:5]]}")

    if acima:
        print("\nMaiores chunks (dispositivo unico grande demais para o teto):")
        for c in sorted(acima, key=lambda c: -len(c["texto"]))[:5]:
            print(f"  {c['artigo']:<12} {len(c['texto']):>6} chars, "
                  f"{c['n_dispositivos']} dispositivo(s)")

    if args.report:
        print("\n(--report: nada foi escrito em disco)")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(chunks, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    print(f"\nEscrito: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Bloco 4 do plano: pergunta -> top-k trechos da norma.

Uso:

    from src.retriever import Retriever

    r = Retriever()
    for res in r.buscar("prazo para analisar pedido de acesso", k=3):
        print(res.artigo, res.score, res.texto)

Ou pela linha de comando, para inspecionar sem subir o app:

    .venv\\Scripts\\python.exe -m src.retriever "prazo para analisar pedido de acesso"


O FILTRO DE VIGENCIA E O PONTO DESTE MODULO

O indice contem 1.188 chunks, dos quais 108 NAO estao em vigor: 21 revogados e 87 de redacao
anterior (ver o Bloco 2). Por padrao a busca devolve apenas os vigentes.

O filtro fica aqui, no retriever, e nao no prompt do gerador, por um motivo concreto: o que
nao chega ao contexto nao pode ser citado por engano. Deixar o LLM decidir se um trecho esta
em vigor seria pedir a ele um julgamento que o metadado ja resolve de forma deterministica.


POR QUE NAO HA LIMIAR DE SCORE

Medido no indice pronto: o top-1 de uma pergunta legitima marca 0,878; o de "qual o preco de
um painel solar" marca 0,844; o de "receita de bolo de cenoura", 0,824; o de teclado aleatorio
("asdfgh qwerty"), 0,809. Sete centesimos separam os extremos.

Qualquer corte nessa faixa ou deixaria passar pergunta fora de escopo, ou descartaria pergunta
legitima. Entao este modulo NAO tenta decidir se a pergunta tem resposta na norma -- ele
sempre devolve os k mais proximos, com o score, e a decisao de dizer "nao encontrei" fica com
o gerador (Bloco 5), que olha o conteudo dos trechos, nao a nota da busca.

O score vai junto no resultado para o gerador poder usa-lo como sinal secundario, e para
aparecer na interface -- nao como filtro.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import (  # noqa: E402
    CAMINHO_CHUNKS,
    CAMINHO_INDICE,
    MODELO_EMBEDDING,
    PREFIXO_QUERY,
    SITUACAO_VIGENTE,
)
from src.glossario import expandir  # noqa: E402

# Fusão de rankings (RRF). O 60 é o valor da publicação original e não foi ajustado ao
# gabarito: mexer nele seria calibrar o sistema na própria bateria que o avalia.
K_RRF = 60

# Quantos candidatos buscar por resultado pedido, antes de filtrar por vigencia. Como so 9% do
# indice esta fora de vigor, 4x cobre com folga; se ainda faltar, a busca amplia sozinha.
FATOR_FOLGA = 4

# Medido na bateria de aceitacao (scripts/avaliar.py), com o glossario ligado -- recall do
# artigo do gabarito entre os 7 casos que tem gabarito:
#
#     k=3  3/7      k=8  6/7      k=15  7/7
#     k=5  4/7      k=10 6/7      k=20  7/7
#
# 8 e o ponto onde a curva achata: de 5 para 8 ganha dois casos, de 8 para 15 ganha um. O custo
# e desprezivel -- 8 trechos de ~600 caracteres dao ~1.200 tokens de contexto --, e passar de
# 8 comeca a encher a interface de texto que o usuario nao vai ler.
K_PADRAO = 8


def tokenizar(texto: str) -> list[str]:
    """Tokens para a busca léxica: minúsculo, sem acento, sem pontuação.

    Tirar o acento importa: quem digita "minigeracao" precisa casar com "minigeração", e o
    BM25 compara token com token, sem a tolerância que o modelo de embedding tem.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]{2,}", sem_acento)


def fundir_rrf(rankings: list[list[int]], k0: int = K_RRF) -> list[int]:
    """Reciprocal Rank Fusion: cada lista contribui 1/(k0 + posição) para cada item.

    Escolhida em vez de somar os scores ponderados porque as duas escalas não são comparáveis:
    a similaridade densa vive espremida entre 0,80 e 0,92 (medido), enquanto o BM25 é ilimitado
    e depende da raridade dos termos. Normalizar essas escalas exigiria calibração, e calibrar
    contra a bateria de aceitação seria ajustar o sistema ao próprio gabarito. O RRF ignora a
    magnitude e usa só a ordem, que é o que as duas buscas têm de comparável.
    """
    pontos: dict[int, float] = {}
    for ranking in rankings:
        for posicao, item in enumerate(ranking, 1):
            pontos[item] = pontos.get(item, 0.0) + 1.0 / (k0 + posicao)
    return [item for item, _ in sorted(pontos.items(), key=lambda kv: -kv[1])]


@dataclass(frozen=True)
class Resultado:
    """Um trecho recuperado, com o suficiente para citar e para exibir."""

    artigo: str
    texto: str
    trilha: list[str]
    situacao: str
    alteracoes: list[str]
    score: float
    id: str

    @property
    def referencia(self) -> str:
        """Rotulo curto para citar na resposta, ex.: 'Art. 655-L'."""
        return self.artigo


class Retriever:
    """Busca semantica sobre o indice FAISS pre-computado.

    O modelo e o indice sao carregados sob demanda e ficam em cache na instancia: dentro do
    app, uma unica instancia atende todas as perguntas, sem recarregar 470 MB por requisicao.
    """

    def __init__(
        self,
        caminho_chunks: Path = CAMINHO_CHUNKS,
        caminho_indice: Path = CAMINHO_INDICE,
        modelo: str = MODELO_EMBEDDING,
        expandir_consulta: bool = True,
        hibrido: bool = True,
    ) -> None:
        self.caminho_chunks = Path(caminho_chunks)
        self.caminho_indice = Path(caminho_indice)
        self.nome_modelo = modelo
        # Desligaveis para medir o efeito de cada um -- ver scripts/avaliar.py.
        self.expandir_consulta = expandir_consulta
        self.hibrido = hibrido

    # -- carregamento preguicoso -------------------------------------------------------

    @cached_property
    def chunks(self) -> list[dict]:
        if not self.caminho_chunks.exists():
            raise FileNotFoundError(
                f"{self.caminho_chunks} nao existe. Rode scripts/chunk_text.py."
            )
        return json.loads(self.caminho_chunks.read_text(encoding="utf-8"))

    @cached_property
    def indice(self):
        import faiss

        if not self.caminho_indice.exists():
            raise FileNotFoundError(
                f"{self.caminho_indice} nao existe. Rode scripts/build_index.py."
            )
        indice = faiss.read_index(str(self.caminho_indice))
        # A posicao no indice e o unico elo entre vetor e chunk. Se os dois arquivos vierem de
        # execucoes diferentes, a busca devolve o artigo errado para o vetor certo -- sem erro
        # nenhum, so resposta trocada. Por isso a checagem e na carga.
        if indice.ntotal != len(self.chunks):
            raise ValueError(
                f"Indice e chunks fora de sincronia: {indice.ntotal} vetores para "
                f"{len(self.chunks)} chunks. Regere os dois com scripts/build_index.py."
            )
        return indice

    @cached_property
    def modelo(self):
        from sentence_transformers import SentenceTransformer

        return SentenceTransformer(self.nome_modelo)

    @cached_property
    def bm25(self):
        """Índice léxico sobre os mesmos textos que foram vetorizados.

        Construído em memória na primeira busca: 1.188 documentos curtos custam milissegundos e
        não justificam um artefato em disco. Usa `texto_busca` -- e não `texto` -- para que os
        dois lados da fusão enxerguem exatamente o mesmo conteúdo, incluindo a trilha
        estrutural e o caput que o Bloco 2 acrescentou.
        """
        from rank_bm25 import BM25Okapi

        return BM25Okapi([tokenizar(c["texto_busca"]) for c in self.chunks])

    # -- busca -------------------------------------------------------------------------

    def _vetorizar(self, pergunta: str):
        # O prefixo "query: " vem de src/config.py, o mesmo arquivo que o build usou para o
        # "passage: ". Sao assimetricos de proposito e nao podem divergir.
        return self.modelo.encode(
            [PREFIXO_QUERY + pergunta], normalize_embeddings=True
        ).astype("float32")

    def preparar_consulta(self, pergunta: str) -> tuple[str, list[str]]:
        """Aplica o glossario, se ligado. Devolve (consulta, termos acrescentados)."""
        if not self.expandir_consulta:
            return pergunta, []
        return expandir(pergunta)

    def buscar(
        self,
        pergunta: str,
        k: int = K_PADRAO,
        situacoes: tuple[str, ...] = (SITUACAO_VIGENTE,),
    ) -> list[Resultado]:
        """Devolve os k trechos mais proximos cuja situacao esteja em `situacoes`.

        `situacoes=None` desliga o filtro, o que serve para inspecionar o indice inteiro --
        util para responder "o que este artigo dizia antes?", nunca para a resposta padrao.
        """
        pergunta = pergunta.strip()
        if not pergunta:
            return []

        consulta, _ = self.preparar_consulta(pergunta)
        vetor = self._vetorizar(consulta)

        if self.hibrido:
            return self._buscar_hibrido(consulta, vetor, situacoes, k)

        limite = self.indice.ntotal
        buscar_n = min(limite, max(k * FATOR_FOLGA, k))

        while True:
            scores, posicoes = self.indice.search(vetor, buscar_n)
            resultados = self._montar(scores[0], posicoes[0], situacoes, k)
            # Se o filtro consumiu todos os candidatos e ainda ha indice para varrer, amplia.
            if len(resultados) >= k or buscar_n >= limite:
                return resultados
            buscar_n = min(limite, buscar_n * 4)

    def _buscar_hibrido(self, consulta: str, vetor, situacoes, k: int) -> list[Resultado]:
        """Funde o ranking semantico com o lexico.

        As duas buscas falham por motivos opostos e complementares: a densa perde o termo
        tecnico exato quando ele concorre com dezenas de artigos que falam do mesmo tema, e a
        lexica nao encontra o que foi perguntado com outras palavras. Medido na bateria, a
        fusao levou a recuperacao de 6/7 para 7/7, sem piorar nenhuma pergunta.
        """
        import numpy as np

        scores_densos, posicoes = self.indice.search(vetor, self.indice.ntotal)
        score_por_posicao = {int(p): float(s) for p, s in zip(posicoes[0], scores_densos[0])
                             if p >= 0}

        permitido = [
            i for i in range(len(self.chunks))
            if situacoes is None or self.chunks[i]["situacao"] in situacoes
        ]
        permitidos = set(permitido)

        ranking_denso = [int(p) for p in posicoes[0] if int(p) in permitidos]
        pontos_bm25 = self.bm25.get_scores(tokenizar(consulta))
        ranking_lexico = [i for i in np.argsort(pontos_bm25)[::-1] if int(i) in permitidos]

        fundido = fundir_rrf([ranking_denso, [int(i) for i in ranking_lexico]])[:k]

        # O score exibido continua sendo a similaridade semantica: e a unica das duas escalas
        # que significa algo para quem le ("quao proximo do que perguntei"). A posicao na lista
        # e que reflete a fusao.
        return self._montar(
            [score_por_posicao.get(i, 0.0) for i in fundido], fundido, situacoes, k
        )

    def _montar(self, scores, posicoes, situacoes, k: int) -> list[Resultado]:
        saida: list[Resultado] = []
        for score, posicao in zip(scores, posicoes):
            if posicao < 0:  # FAISS preenche com -1 quando pede mais que o disponivel
                continue
            chunk = self.chunks[int(posicao)]
            if situacoes is not None and chunk["situacao"] not in situacoes:
                continue
            saida.append(
                Resultado(
                    artigo=chunk["artigo"],
                    texto=chunk["texto"],
                    trilha=chunk.get("trilha", []),
                    situacao=chunk["situacao"],
                    alteracoes=chunk.get("alteracoes", []),
                    score=float(score),
                    id=chunk["id"],
                )
            )
            if len(saida) == k:
                break
        return saida


def main() -> int:
    parser = argparse.ArgumentParser(description="Busca trechos da REN 1.000/2021.")
    parser.add_argument("pergunta", help="Pergunta em linguagem natural.")
    parser.add_argument("-k", type=int, default=K_PADRAO, help="Quantos trechos devolver.")
    parser.add_argument(
        "--todas-situacoes",
        action="store_true",
        help="Nao filtrar por vigencia: inclui revogados e redacoes anteriores.",
    )
    args = parser.parse_args()

    retriever = Retriever()
    situacoes = None if args.todas_situacoes else (SITUACAO_VIGENTE,)
    resultados = retriever.buscar(args.pergunta, k=args.k, situacoes=situacoes)

    if not resultados:
        print("Nenhum trecho encontrado.")
        return 0

    for posicao, res in enumerate(resultados, 1):
        marca = "" if res.situacao == SITUACAO_VIGENTE else f"  [{res.situacao.upper()}]"
        print(f"\n{posicao}. {res.referencia}  (score {res.score:.3f}){marca}")
        if res.trilha:
            print(f"   {' > '.join(res.trilha)}")
        if res.alteracoes:
            print(f"   alteracoes: {', '.join(res.alteracoes)}")
        print(f"   {res.texto[:400]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

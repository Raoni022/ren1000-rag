"""
Testes do Bloco 4, sem baixar o modelo de embedding.

Constroem um indice FAISS pequeno com vetores conhecidos e substituem apenas a vetorizacao da
pergunta. O que se testa aqui e a logica que erra em silencio: filtro de vigencia, corte em k,
folga de busca e a sincronia entre indice e chunks.

    .venv\\Scripts\\python.exe tests/test_retriever.py
"""

import json
import sys
import tempfile
from pathlib import Path

import faiss
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SITUACAO_REVOGADO, SITUACAO_SUPERADO, SITUACAO_VIGENTE  # noqa: E402
from src.retriever import Retriever, fundir_rrf  # noqa: E402

falhas: list[str] = []


def checar(nome: str, obtido, esperado) -> None:
    if obtido == esperado:
        print(f"  ok   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}\n        esperado: {esperado!r}\n        obtido:   {obtido!r}")


class RetrieverFalso(Retriever):
    """Retriever real, com a vetorizacao da pergunta trocada por um vetor fixo."""

    vetor_pergunta = np.array([[1.0, 0.0]], dtype="float32")

    def _vetorizar(self, pergunta: str):
        return self.vetor_pergunta


def montar(situacoes: list[str]) -> RetrieverFalso:
    """Cria chunks e indice onde a proximidade decresce na ordem da lista."""
    pasta = Path(tempfile.mkdtemp())
    chunks, vetores = [], []
    for i, situacao in enumerate(situacoes):
        chunks.append({
            "id": f"c{i}", "artigo": f"Art. {i}", "trilha": ["Título I - TESTE"],
            "situacao": situacao, "alteracoes": [], "texto": f"texto {i}",
            "texto_busca": f"busca {i}",
        })
        # Angulo crescente => similaridade decrescente com [1, 0].
        angulo = (i / len(situacoes)) * (np.pi / 2)
        vetores.append([np.cos(angulo), np.sin(angulo)])

    matriz = np.array(vetores, dtype="float32")
    faiss.normalize_L2(matriz)
    indice = faiss.IndexFlatIP(2)
    indice.add(matriz)

    (pasta / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    faiss.write_index(indice, str(pasta / "i.faiss"))
    # hibrido=False: estes testes verificam o filtro, o corte em k e a ordenacao a partir de
    # vetores conhecidos. A fusao lexica e testada a parte, em fundir_rrf() e tokenizar().
    return RetrieverFalso(pasta / "chunks.json", pasta / "i.faiss", hibrido=False)


print("filtro de vigencia: o que nao chega ao contexto nao pode ser citado por engano")
r = montar([SITUACAO_REVOGADO, SITUACAO_VIGENTE, SITUACAO_SUPERADO, SITUACAO_VIGENTE])
checar("por padrao devolve so vigentes",
       [x.artigo for x in r.buscar("q", k=5)], ["Art. 1", "Art. 3"])
checar("situacoes=None devolve tudo, na ordem de similaridade",
       [x.artigo for x in r.buscar("q", k=5, situacoes=None)],
       ["Art. 0", "Art. 1", "Art. 2", "Art. 3"])
checar("da para pedir explicitamente a redacao anterior",
       [x.artigo for x in r.buscar("q", k=5, situacoes=(SITUACAO_SUPERADO,))], ["Art. 2"])
checar("o resultado carrega a situacao",
       [x.situacao for x in r.buscar("q", k=5, situacoes=None)],
       [SITUACAO_REVOGADO, SITUACAO_VIGENTE, SITUACAO_SUPERADO, SITUACAO_VIGENTE])

print("\ncorte em k e ordenacao")
checar("respeita k", len(r.buscar("q", k=1)), 1)
checar("o mais proximo vem primeiro", r.buscar("q", k=1)[0].artigo, "Art. 1")
scores = [x.score for x in r.buscar("q", k=5, situacoes=None)]
checar("scores em ordem decrescente", scores == sorted(scores, reverse=True), True)
checar("similaridade do vetor identico e 1", round(scores[0], 3), 1.0)

print("\nfolga de busca: filtro nao pode devolver menos do que existe")
# 20 nao vigentes antes de 2 vigentes: k*4 candidatos nao alcancam os vigentes na primeira
# tentativa, e a busca precisa ampliar sozinha.
muitos = [SITUACAO_REVOGADO] * 20 + [SITUACAO_VIGENTE] * 2
r2 = montar(muitos)
checar("amplia a busca ate achar os vigentes",
       [x.artigo for x in r2.buscar("q", k=2)], ["Art. 20", "Art. 21"])
checar("pedir mais do que existe devolve o que ha", len(r2.buscar("q", k=99)), 2)

print("\nentradas degeneradas")
checar("pergunta vazia devolve lista vazia", r.buscar(""), [])
checar("pergunta so com espacos devolve lista vazia", r.buscar("   "), [])

print("\no parametro 'modelo' chega mesmo ao vetorizador")
# Guarda contra regressao: apos a migracao para ONNX o parametro ficou sendo guardado e nunca
# lido, entao pedir outro modelo era silenciosamente ignorado.
r_mod = montar([SITUACAO_VIGENTE])
r_mod.nome_modelo = "algum/outro-modelo"
checar("Retriever repassa o repo ao Embedder", r_mod.modelo.repo, "algum/outro-modelo")

print("\nfusao RRF: usa a ordem, nunca a magnitude dos scores")
checar("item bem colocado nas duas listas vence",
       fundir_rrf([[7, 1, 2], [7, 3, 4]])[0], 7)
checar("consenso ganha de primeiro lugar isolado",
       fundir_rrf([[1, 9, 9], [2, 9, 9]])[0], 9)
checar("uniao de todos os itens, sem repetir",
       sorted(fundir_rrf([[1, 2], [2, 3]])), [1, 2, 3])
checar("lista unica preserva a ordem original", fundir_rrf([[5, 6, 7]]), [5, 6, 7])
# Se o RRF olhasse magnitude, um score altissimo em uma lista dominaria. Ele olha posicao.
checar("ranking vazio nao quebra a fusao", fundir_rrf([[], [4, 5]]), [4, 5])

print("\nsincronia entre indice e chunks")
# Um vetor a mais que chunks: a posicao no indice deixaria de apontar para o artigo certo.
r3 = montar([SITUACAO_VIGENTE, SITUACAO_VIGENTE])
dados = json.loads(r3.caminho_chunks.read_text(encoding="utf-8"))
r3.caminho_chunks.write_text(json.dumps(dados[:1], ensure_ascii=False), encoding="utf-8")
try:
    r3.buscar("q")
    checar("detecta indice fora de sincronia", "nao levantou", "ValueError")
except ValueError as erro:
    checar("detecta indice fora de sincronia", "fora de sincronia" in str(erro), True)

print("\narquivos ausentes dizem qual script rodar")
r4 = RetrieverFalso(Path("nao/existe/chunks.json"), Path("nao/existe/i.faiss"))
try:
    r4.buscar("q")
    checar("indice ausente", "nao levantou", "FileNotFoundError")
except FileNotFoundError as erro:
    checar("indice ausente aponta build_index.py", "build_index.py" in str(erro), True)

# Indice presente, chunks ausentes: o outro ramo da checagem.
r5 = montar([SITUACAO_VIGENTE])
r5.caminho_chunks.unlink()
try:
    r5.buscar("q")
    checar("chunks ausentes", "nao levantou", "FileNotFoundError")
except FileNotFoundError as erro:
    checar("chunks ausentes apontam chunk_text.py", "chunk_text.py" in str(erro), True)

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    raise SystemExit(1)
print("Todos os testes passaram.")

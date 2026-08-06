"""
Testes do vetorizador ONNX.

Os que não precisam do modelo rodam sempre. Os que precisam baixam ~113 MB na primeira vez e
são pulados se o download não estiver disponível -- o objetivo é que a suíte continue rodando
em máquina sem rede, não esconder falha.

    .venv\\Scripts\\python.exe tests/test_embedder.py
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import ARQUIVO_ONNX, JANELA_TOKENS, PREFIXO_QUERY, REPO_EMBEDDING  # noqa: E402
from src.embedder import Embedder, tokenizar  # noqa: E402

falhas: list[str] = []


def checar(nome: str, obtido, esperado) -> None:
    if obtido == esperado:
        print(f"  ok   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}\n        esperado: {esperado!r}\n        obtido:   {obtido!r}")


print("configuração: o runtime tem que apontar para o ONNX oficial do modelo")
checar("repositório é o do próprio autor do modelo",
       REPO_EMBEDDING, "intfloat/multilingual-e5-small")
checar("usa a variante quantizada", "qint8" in ARQUIVO_ONNX, True)
checar("vem da pasta onnx do repositório", ARQUIVO_ONNX.startswith("onnx/"), True)
checar("janela igual à do modelo", JANELA_TOKENS, 512)

print("\ntokenização léxica: acento não pode separar quem digita sem ele")
checar("tira acento e minusculiza",
       tokenizar("Minigeração Distribuída"), ["minigeracao", "distribuida"])
checar("'minigeracao' e 'minigeração' viram o mesmo token",
       tokenizar("minigeracao") == tokenizar("minigeração"), True)
checar("descarta pontuação e token de uma letra",
       tokenizar("Art. 655-C, § 1º:"), ["art", "655", "1o"])
checar("texto vazio não quebra", tokenizar(""), [])

print("\ncarregamento é preguiçoso: importar não pode baixar 113 MB")
e = Embedder()
checar("nada carregado ao instanciar",
       "_sessao" not in e.__dict__ and "_tokenizador" not in e.__dict__, True)

print("\ninferência (exige o modelo baixado)")
try:
    vetor = Embedder().vetorizar(PREFIXO_QUERY + "validade dos créditos de energia")
except Exception as erro:
    print(f"  PULADO: modelo indisponível ({type(erro).__name__}). "
          f"Rode com rede e HF_TOKEN para exercitar esta parte.")
else:
    checar("formato (1, 384), que é o do índice", vetor.shape, (1, 384))
    checar("dtype float32, como o FAISS espera", str(vetor.dtype), "float32")
    checar("norma 1 -- é o que torna produto interno igual a cosseno",
           round(float(np.linalg.norm(vetor)), 5), 1.0)

    outro = Embedder().vetorizar(PREFIXO_QUERY + "prazo do orçamento de conexão")
    checar("perguntas diferentes geram vetores diferentes",
           float(np.dot(vetor[0], outro[0])) < 0.999, True)

    igual = Embedder().vetorizar(PREFIXO_QUERY + "validade dos créditos de energia")
    checar("mesma pergunta gera o mesmo vetor (determinístico)",
           round(float(np.dot(vetor[0], igual[0])), 6), 1.0)

    # Truncar em 512 não pode estourar: é o caminho de uma pergunta absurdamente longa.
    longo = Embedder().vetorizar(PREFIXO_QUERY + ("energia distribuída " * 2000))
    checar("pergunta acima da janela é truncada, não quebra", longo.shape, (1, 384))

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    raise SystemExit(1)
print("Todos os testes passaram.")

"""
Testes do Bloco 3 que NAO dependem de baixar o modelo de embedding.

Cobrem a validacao da entrada, os prefixos do E5 e a geometria do indice -- que e onde os
erros silenciosos moram. A qualidade da recuperacao em si e verificada no Bloco 7, com a
bateria de perguntas.

    .venv\\Scripts\\python.exe tests/test_build_index.py
"""

import json
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from build_index import (  # noqa: E402
    MODELO_PADRAO,
    PREFIXO_PASSAGE,
    PREFIXO_QUERY,
    carregar_chunks,
    construir_indice,
)

falhas: list[str] = []


def checar(nome: str, obtido, esperado) -> None:
    if obtido == esperado:
        print(f"  ok   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}\n        esperado: {esperado!r}\n        obtido:   {obtido!r}")


def escrever(conteudo) -> Path:
    caminho = Path(tempfile.mkdtemp()) / "chunks.json"
    caminho.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
    return caminho


print("prefixos do E5 (assimetricos: omiti-los degrada a busca sem gerar erro)")
checar("prefixo de documento", PREFIXO_PASSAGE, "passage: ")
checar("prefixo de pergunta", PREFIXO_QUERY, "query: ")
checar("sao diferentes", PREFIXO_PASSAGE != PREFIXO_QUERY, True)
checar("modelo padrao e o e5-small", MODELO_PADRAO, "intfloat/multilingual-e5-small")

print("\nvalidacao da entrada")
ok = carregar_chunks(escrever([{"id": "a", "texto_busca": "texto"}]))
checar("carrega chunk valido", len(ok), 1)

for descricao, conteudo in [("arquivo vazio", []),
                            ("chunk sem texto_busca", [{"id": "a", "texto": "x"}]),
                            ("texto_busca vazio", [{"id": "a", "texto_busca": ""}])]:
    try:
        carregar_chunks(escrever(conteudo))
        checar(f"rejeita {descricao}", "nao levantou", "SystemExit")
    except SystemExit:
        checar(f"rejeita {descricao}", "SystemExit", "SystemExit")

print("\ngeometria do indice")
# Vetores normalizados: o produto interno tem que reproduzir a ordem do cosseno.
base = np.array([[1.0, 0.0], [0.0, 1.0], [0.7071, 0.7071]], dtype="float32")
indice = construir_indice(base)
checar("um vetor por chunk", indice.ntotal, 3)
checar("dimensao preservada", indice.d, 2)

consulta = np.array([[1.0, 0.0]], dtype="float32")
distancias, posicoes = indice.search(consulta, 3)
checar("vetor identico vem em primeiro", int(posicoes[0][0]), 0)
checar("similaridade do identico e 1", round(float(distancias[0][0]), 3), 1.0)
checar("ordem segue o cosseno (45 graus antes de 90)",
       [int(p) for p in posicoes[0]], [0, 2, 1])
checar("ortogonal tem similaridade 0", round(float(distancias[0][2]), 3), 0.0)

# A posicao no indice e o unico elo entre vetor e chunk: se ela nao for a ordem de entrada,
# a interface exibe o artigo errado para a resposta certa.
checar("posicao no indice = ordem de entrada", int(indice.search(
    np.array([[0.0, 1.0]], dtype="float32"), 1)[1][0][0]), 1)

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    raise SystemExit(1)
print("Todos os testes passaram.")

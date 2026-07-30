"""
Bloco 3 do plano: index/chunks.json -> index/ren1000.faiss

Rodar isoladamente:

    .venv\\Scripts\\python.exe scripts/build_index.py --report
    .venv\\Scripts\\python.exe scripts/build_index.py

Roda uma vez, offline. O Space nao recalcula embedding nenhum: carrega o indice pronto.


MODELO: intfloat/multilingual-e5-small

O plano original previa paraphrase-multilingual-MiniLM-L12-v2, que foi descartado por medicao:
a janela dele e de 128 tokens (~450 caracteres em portugues) e os chunks do Bloco 2 vao ate
1.200 caracteres, com p99 em 1.194. O MiniLM truncaria a maior parte do corpus em silencio --
e o pedaco truncado costuma ser justamente onde estao os numeros e prazos que a pergunta busca.

O e5-small tem janela de 512 tokens, 384 dimensoes e ~470 MB, o que cabe no Space gratuito.


OS PREFIXOS "query:" E "passage:" NAO SAO OPCIONAIS

Os modelos E5 sao treinados com prefixo assimetrico: documentos entram como "passage: <texto>"
e perguntas como "query: <texto>". Omitir isso nao gera erro nenhum -- so degrada a busca, de
forma dificil de perceber depois. Por isso os prefixos ficam em constantes aqui e sao
reexportados para o retriever (Bloco 4) usar exatamente os mesmos.


SIMILARIDADE: produto interno sobre vetores normalizados

E5 e treinado para similaridade de cosseno. Com os vetores normalizados em norma L2, o produto
interno (IndexFlatIP) e identico ao cosseno, entao um IndexFlatIP resolve. IndexFlatL2 daria
ordenacao diferente e pior.

Flat -- forca bruta, sem quantizacao -- porque 1.188 vetores de 384 dimensoes cabem em ~1,8 MB
e a busca exata leva menos de um milissegundo. Indices aproximados (IVF, HNSW) so compensam
em corpus ordens de grandeza maiores, e custariam recall.


O QUE VAI PARA O VETOR

O campo texto_busca de cada chunk, que o Bloco 2 montou com a trilha estrutural e o caput do
artigo. O campo texto, literal, nao e vetorizado: ele existe para a interface exibir o trecho
da norma para o usuario conferir.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Modelo e prefixos vem do runtime (src/config.py), nunca o contrario: o indice tem que ser
# construido exatamente com o que o retriever vai usar na busca.
from src.config import (  # noqa: E402
    MODELO_EMBEDDING as MODELO_PADRAO,
    PREFIXO_PASSAGE,
    PREFIXO_QUERY,
)


def carregar_chunks(caminho: Path) -> list[dict]:
    chunks = json.loads(caminho.read_text(encoding="utf-8"))
    if not chunks:
        raise SystemExit(f"ERRO: {caminho} esta vazio. Rode antes scripts/chunk_text.py")
    faltando = [c.get("id") for c in chunks if not c.get("texto_busca")]
    if faltando:
        raise SystemExit(f"ERRO: {len(faltando)} chunk(s) sem texto_busca: {faltando[:5]}")
    return chunks


def gerar_embeddings(
    textos: list[str], modelo_nome: str, batch_size: int, ids: list[str]
) -> np.ndarray:
    """Vetoriza os textos ja prefixados, normalizando em L2 para o produto interno virar cosseno."""
    from sentence_transformers import SentenceTransformer

    modelo = SentenceTransformer(modelo_nome)
    janela = modelo.max_seq_length

    # Medicao exata com o tokenizador do proprio modelo, nao estimativa por caractere: o que
    # passa da janela e truncado em silencio, e o pedaco cortado costuma ser justamente o fim
    # do dispositivo, onde estao prazos e limites numericos.
    tamanhos = [len(modelo.tokenizer.encode(t)) for t in textos]
    ordenados = sorted(tamanhos)
    truncados = [i for i, n in enumerate(tamanhos) if n > janela]
    print(f"Janela do modelo ........... {janela} tokens")
    print(f"Tokens por chunk ........... mediana {ordenados[len(ordenados) // 2]}, "
          f"p99 {ordenados[int(len(ordenados) * .99)]}, maior {ordenados[-1]}")
    if truncados:
        print(f"AVISO: {len(truncados)} chunk(s) excedem a janela e serao truncados: "
              f"{[ids[i] for i in truncados[:5]]}", file=sys.stderr)
    else:
        print("Truncagem .................. nenhuma")

    return modelo.encode(
        textos,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=True,
        convert_to_numpy=True,
    ).astype("float32")


def construir_indice(embeddings: np.ndarray):
    import faiss

    indice = faiss.IndexFlatIP(embeddings.shape[1])
    indice.add(embeddings)
    return indice


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gera embeddings dos chunks e constroi o indice FAISS."
    )
    parser.add_argument("--input", type=Path, default=Path("index/chunks.json"))
    parser.add_argument("--output", type=Path, default=Path("index/ren1000.faiss"))
    parser.add_argument("--model", default=MODELO_PADRAO)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument(
        "--report",
        action="store_true",
        help="Só valida a entrada e mostra o que seria feito, sem baixar modelo nem gravar.",
    )
    args = parser.parse_args()

    if not args.input.exists():
        print(f"ERRO: nao encontrei {args.input}. Rode antes scripts/chunk_text.py",
              file=sys.stderr)
        return 1

    chunks = carregar_chunks(args.input)
    textos = [PREFIXO_PASSAGE + c["texto_busca"] for c in chunks]
    tamanhos = sorted(len(t) for t in textos)

    print(f"Chunks ..................... {len(chunks)}")
    print(f"Modelo ..................... {args.model}")
    print(f"Prefixo de indexacao ....... {PREFIXO_PASSAGE!r}")
    print(f"texto_busca (chars): mediana {tamanhos[len(tamanhos) // 2]}, "
          f"p99 {tamanhos[int(len(tamanhos) * .99)]}, maior {tamanhos[-1]}")

    if args.report:
        print("\n(--report: nada foi baixado nem gravado)")
        return 0

    print()
    inicio = time.time()
    embeddings = gerar_embeddings(
        textos, args.model, args.batch_size, [c["id"] for c in chunks]
    )
    print(f"Embeddings ................. {embeddings.shape} em {time.time() - inicio:.0f}s")

    # Se a normalizacao falhar, o produto interno deixa de ser cosseno e a ordenacao fica
    # errada sem lancar erro -- por isso a checagem e explicita.
    normas = np.linalg.norm(embeddings, axis=1)
    if not np.allclose(normas, 1.0, atol=1e-3):
        print(f"ERRO: vetores nao normalizados (norma min {normas.min():.4f}, "
              f"max {normas.max():.4f}).", file=sys.stderr)
        return 1
    print("Normalizacao L2 ............ ok (produto interno = cosseno)")

    indice = construir_indice(embeddings)
    print(f"Indice ..................... IndexFlatIP, {indice.ntotal} vetores, "
          f"dim {indice.d}")

    if indice.ntotal != len(chunks):
        print(f"ERRO: {indice.ntotal} vetores para {len(chunks)} chunks. A posicao no indice e "
              f"o que liga o vetor ao chunk -- precisam bater.", file=sys.stderr)
        return 1

    import faiss

    args.output.parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(indice, str(args.output))
    tamanho_mb = args.output.stat().st_size / 1024 / 1024
    print(f"\nEscrito: {args.output} ({tamanho_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Vetorização da pergunta em runtime, sem torch.

POR QUE ONNX E NÃO sentence-transformers

O índice é pré-computado: em produção o sistema vetoriza UMA pergunta por vez. Carregar
`torch` inteiro para isso custa caro e não entrega nada em troca. Medido, uma busca completa:

    torch + sentence-transformers ....... 846 MB de RSS
    ONNX fp32 ........................... 789 MB   (pico 884 MB, pior que o torch)
    ONNX int8 ........................... 456 MB   (pico 456 MB)

Em disco a diferença é maior ainda: o caminho antigo arrasta `torch` (494 MB), `transformers`
(97 MB), `scipy`, `sympy` e `networkx` -- cerca de 790 MB de dependências. Este arquivo precisa
de `onnxruntime` (43 MB) e `tokenizers` (7 MB).

Isso é o que faz o app caber em hospedagem gratuita, que foi o motivo da migração.


POR QUE A VARIANTE QUANTIZADA, E POR QUE ISSO NÃO É ARRISCADO AQUI

A fp32 não compensava: economizava 57 MB e tinha pico PIOR que o torch. A int8 corta 46%.

Quantização altera os vetores, e trocar o codificador da pergunta por um que produz vetores
diferentes dos que construíram o índice degradaria a busca de um jeito que não aparece em teste
superficial. Por isso a troca foi medida contra a bateria inteira, e não pelo cosseno isolado:

    torch      7/7   posições {1:5, 2:8, 3:1, 4:1, 6:2, 7:2, 8:2}
    ONNX fp32  7/7   posições {1:5, 2:8, 3:1, 4:1, 6:2, 7:2, 8:2}
    ONNX int8  7/7   posições {1:5, 2:8, 3:1, 4:1, 6:2, 7:2, 8:2}

Ranking idêntico, artigo por artigo, inclusive na pergunta 2, cujo alvo está na fronteira do
top-8 e seria a primeira a cair.

O índice continua sendo construído com `sentence-transformers` em fp32 (ver
`requirements-build.txt`): o custo lá é pago uma vez, offline, e não faz sentido quantizar o
lado dos documentos.


O ONNX É O OFICIAL

Vem do próprio repositório `intfloat/multilingual-e5-small`, não de uma conversão de terceiros.
Com o modelo original ausente, uma conversão de origem desconhecida poderia divergir do que
gerou o índice sem que nada acusasse.
"""

from __future__ import annotations

import re
import unicodedata
from functools import cached_property

import numpy as np

from src.config import (
    ARQUIVO_ONNX,
    JANELA_TOKENS,
    REPO_EMBEDDING,
)


class Embedder:
    """Reproduz o pipeline do sentence-transformers: transformer, mean pooling, normalize L2.

    A ordem e o modo de pooling não são escolha: são a configuração publicada do e5-small
    (`Transformer → Pooling(mean) → Normalize`). Qualquer divergência aqui produz vetores que
    não conversam com o índice, sem levantar erro.
    """

    def __init__(self, repo: str = REPO_EMBEDDING, arquivo: str = ARQUIVO_ONNX) -> None:
        self.repo = repo
        self.arquivo = arquivo

    @cached_property
    def _sessao(self):
        import onnxruntime as ort

        from huggingface_hub import hf_hub_download

        caminho = hf_hub_download(self.repo, self.arquivo)
        # Uma thread: o app atende uma pergunta por vez e o paralelismo do ORT só somaria
        # memória e disputa de CPU num container pequeno.
        opcoes = ort.SessionOptions()
        opcoes.intra_op_num_threads = 1
        return ort.InferenceSession(caminho, opcoes, providers=["CPUExecutionProvider"])

    @cached_property
    def _tokenizador(self):
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        tok = Tokenizer.from_file(hf_hub_download(self.repo, "tokenizer.json"))
        tok.enable_truncation(max_length=JANELA_TOKENS)
        return tok

    @cached_property
    def _entradas(self) -> set[str]:
        return {entrada.name for entrada in self._sessao.get_inputs()}

    def vetorizar(self, texto: str) -> np.ndarray:
        """Devolve o vetor (1, 384) normalizado, pronto para o produto interno do FAISS."""
        codificado = self._tokenizador.encode(texto)
        ids = np.array([codificado.ids], dtype=np.int64)
        mascara = np.array([codificado.attention_mask], dtype=np.int64)

        entrada = {"input_ids": ids, "attention_mask": mascara}
        if "token_type_ids" in self._entradas:
            entrada["token_type_ids"] = np.zeros_like(ids)

        # (1, tokens, 384) -> média ponderada pela máscara -> norma 1
        estados = self._sessao.run(None, entrada)[0]
        peso = mascara[..., None].astype(np.float32)
        media = (estados * peso).sum(axis=1) / np.clip(peso.sum(axis=1), 1e-9, None)
        return (media / np.linalg.norm(media, axis=1, keepdims=True)).astype("float32")


def tokenizar(texto: str) -> list[str]:
    """Tokens para a busca léxica: minúsculo, sem acento, sem pontuação.

    Tirar o acento importa: quem digita "minigeracao" precisa casar com "minigeração", e o
    BM25 compara token com token, sem a tolerância que o modelo de embedding tem.
    """
    sem_acento = unicodedata.normalize("NFKD", texto.lower())
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]{2,}", sem_acento)

"""
Constantes compartilhadas entre a construcao do indice (build-time) e a busca (runtime).

Ficam aqui, e nao no script de build, porque uma divergencia entre os dois lados NAO gera erro:
o indice continua respondendo, so que pior, e o defeito e praticamente invisivel em teste
manual. Um unico lugar de definicao e o que impede isso.

A dependencia aponta de scripts/ para src/, e nao o contrario: o indice tem que ser construido
com o que o runtime espera, nunca o inverso.
"""

from __future__ import annotations

from pathlib import Path

# Raiz do repositorio, para os caminhos padrao funcionarem de qualquer diretorio de trabalho.
RAIZ = Path(__file__).resolve().parents[1]

CAMINHO_CHUNKS = RAIZ / "index" / "chunks.json"
CAMINHO_INDICE = RAIZ / "index" / "ren1000.faiss"

# Janela de 512 tokens, 384 dimensoes, ~470 MB. Ver a justificativa da escolha no README.
MODELO_EMBEDDING = "intfloat/multilingual-e5-small"

# Os modelos E5 sao treinados com prefixo assimetrico. Trocar ou omitir nao levanta excecao --
# so piora a recuperacao. Por isso os dois lados leem daqui.
PREFIXO_PASSAGE = "passage: "
PREFIXO_QUERY = "query: "

# Situacao de vigencia atribuida pelo Bloco 2. O retriever devolve so VIGENTE por padrao.
SITUACAO_VIGENTE = "vigente"
SITUACAO_REVOGADO = "revogado"
SITUACAO_SUPERADO = "redacao_anterior"

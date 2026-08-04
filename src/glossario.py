"""
Ponte entre o vocabulário de quem pergunta e o vocabulário da norma.

POR QUE ISSO EXISTE

A REN 1.000/2021 não usa os termos que o público-alvo usa. Medido no corpus vigente:

    pedido de acesso            0 ocorrências   →  orçamento de conexão        82
    conta de luz                0                  fatura                     582
    corte de energia            0                  suspensão do fornecimento   28
    troca de titularidade       0                  alteração de titularidade   25
    bandeira vermelha           0                  bandeiras tarifárias         9
    placa solar / energia solar 0                  microgeração distribuída    18

O caso do "pedido de acesso" é o mais instrutivo: esse vocabulário vem do arcabouço antigo
(REN 482/2012 e PRODIST), revogado pela REN 1.059/2023. Um instalador que aprendeu a profissão
antes de 2023 vai digitar exatamente assim -- e a resposta existe, no Art. 64, sob outro nome.

Busca vetorial não resolve isso sozinha: os embeddings aproximam palavras de sentido próximo,
mas "pedido de acesso" e "orçamento de conexão" não são sinônimos linguísticos, e sim termos
que a mesma norma trocou por decisão regulatória. Busca léxica (BM25) também não resolve, pelo
motivo oposto: não se acha por casamento de termo aquilo que não está escrito.


COMO FUNCIONA

O termo da norma é ACRESCENTADO à pergunta, não substituído. Substituir descartaria o sinal
original -- alguém que pergunta "conta de luz alta" perderia "alta". Acrescentar mantém os dois
e deixa o modelo de embedding pesar.

A tabela é curta, explícita e auditável de propósito, e cada entrada tem evidência medida. Não
é lista de sinônimos genérica: é conhecimento de domínio codificado, do mesmo tipo que sustenta
o Instalight-flow.
"""

from __future__ import annotations

import re

# (padrão do jeito que se pergunta, termo do jeito que a norma escreve)
#
# Os padrões usam \b para casar palavra inteira. Sem isso "gato" casaria dentro de
# "obrigatório" -- 8 falsos positivos no corpus, medidos.
_ENTRADAS: list[tuple[str, str]] = [
    # Vocabulário do arcabouço revogado (REN 482/2012, PRODIST) ainda em uso corrente.
    (r"\b(pedido|solicita[çc][ãa]o|parecer|protocolo)\s+de\s+acesso\b", "orçamento de conexão"),
    (r"\bacesso\s+[àa]\s+rede\b", "orçamento de conexão"),

    # Linguagem do consumidor final.
    (r"\bconta\s+de\s+(luz|energia)\b", "fatura"),
    (r"\bcorte\s+de\s+(luz|energia)\b", "suspensão do fornecimento"),
    (r"\b(troca|transfer[êe]ncia|mudan[çc]a)\s+de\s+titularidade\b", "alteração de titularidade"),
    (r"\bbandeira\s+(vermelha|amarela|verde)\b", "bandeiras tarifárias"),

    # Linguagem do mercado solar.
    (r"\b(placa|painel|pain[ée]is|plac as)\s+solar(es)?\b", "microgeração distribuída"),
    (r"\benergia\s+solar\b", "microgeração distribuída"),
]

GLOSSARIO: list[tuple[re.Pattern[str], str]] = [
    (re.compile(padrao, re.IGNORECASE), termo) for padrao, termo in _ENTRADAS
]


def expandir(pergunta: str) -> tuple[str, list[str]]:
    """Acrescenta à pergunta os termos da norma correspondentes ao que ela menciona.

    Devolve (pergunta expandida, termos acrescentados). A lista de termos serve para a
    interface poder mostrar ao usuário o que foi acrescentado -- uma expansão invisível
    tornaria a busca inexplicável quando ela trouxesse algo inesperado.
    """
    acrescentados: list[str] = []
    for padrao, termo in GLOSSARIO:
        if padrao.search(pergunta) and termo not in acrescentados:
            acrescentados.append(termo)

    if not acrescentados:
        return pergunta, []
    return f"{pergunta} {' '.join(acrescentados)}", acrescentados

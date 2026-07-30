"""
Testes das funcoes de limpeza do Bloco 1, sem depender do PDF real.

Sem pytest de proposito: roda com o Python do venv e nada mais, porque nesse ponto do
projeto a unica dependencia instalada e o pypdf.

    .venv\\Scripts\\python.exe tests/test_extract_text.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from extract_text import (  # noqa: E402
    RE_SO_PAGINACAO,
    detectar_boilerplate,
    limpar_pagina,
    reflow,
    normalizar_unicode,
    relatorio_artigos,
    repara_quebra_de_ligadura,
)

falhas: list[str] = []


def checar(nome: str, obtido, esperado) -> None:
    if obtido == esperado:
        print(f"  ok   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}\n        esperado: {esperado!r}\n        obtido:   {obtido!r}")


print("reflow: junta linhas quebradas pela largura da pagina")
checar(
    "duas linhas de um mesmo paragrafo viram uma",
    reflow("Art. 1o Esta Resolucao estabelece as regras\nda prestacao do servico.\n"),
    "Art. 1o Esta Resolucao estabelece as regras da prestacao do servico.\n",
)
checar(
    "remonta palavra hifenizada no fim da linha",
    reflow("a distribui-\ncao de energia deve\nseguir a norma.\n"),
    "a distribui cao de energia deve seguir a norma.\n".replace("distribui cao", "distribuicao"),
)

print("\nreflow: preserva as quebras estruturais da norma")
checar(
    "novo artigo comeca em bloco proprio",
    reflow("Art. 1o Primeira regra\ncontinua aqui.\nArt. 2o Segunda regra.\n"),
    "Art. 1o Primeira regra continua aqui.\n\nArt. 2o Segunda regra.\n",
)
checar(
    "inciso em romano nao e colado no caput",
    reflow("Art. 5o Sao deveres:\nI - pagar a fatura\nno vencimento;\nII - permitir a leitura.\n"),
    "Art. 5o Sao deveres:\n\nI - pagar a fatura no vencimento;\n\nII - permitir a leitura.\n",
)
checar(
    "paragrafo e alinea abrem bloco proprio",
    reflow("Art. 7o Caput.\n§ 1o Primeiro paragrafo.\na) primeira alinea.\n"),
    "Art. 7o Caput.\n\n§ 1o Primeiro paragrafo.\n\na) primeira alinea.\n",
)
checar(
    "CAPITULO abre bloco proprio",
    reflow("texto final do artigo anterior.\nCAPITULO II\nDO FATURAMENTO\n"),
    "texto final do artigo anterior.\n\nCAPITULO II DO FATURAMENTO\n",
)
checar(
    "ponto de abreviacao no meio da frase nao quebra paragrafo",
    reflow("conforme o disposto no art.\n5o desta Resolucao.\n"),
    "conforme o disposto no art. 5o desta Resolucao.\n",
)

print("\nreflow: dispositivos inseridos por resolucao posterior (sufixo -A/-B)")
checar(
    "inciso 'XVII-A -' abre bloco proprio",
    reflow("Art. 2o Definicoes:\nXVII-A - excedente de energia: diferenca positiva.\n"),
    "Art. 2o Definicoes:\n\nXVII-A - excedente de energia: diferenca positiva.\n",
)
checar(
    "'Art. 655-B' abre bloco proprio",
    reflow("fim do artigo anterior.\nArt. 655-B Novo dispositivo.\n"),
    "fim do artigo anterior.\n\nArt. 655-B Novo dispositivo.\n",
)
checar(
    "'§ 1o-A' abre bloco proprio",
    reflow("Art. 9o Caput.\n§ 1o-A Paragrafo inserido.\n"),
    "Art. 9o Caput.\n\n§ 1o-A Paragrafo inserido.\n",
)

print("\nreflow: nota de alteracao cola no dispositivo que ela altera")
checar(
    "nota nao vira bloco orfao apos ponto final",
    reflow("Art. 3o Regra nova.\n(Incluido pela REN ANEEL 1.059, de 07.02.2023)\n"),
    "Art. 3o Regra nova. (Incluido pela REN ANEEL 1.059, de 07.02.2023)\n",
)
checar(
    "nota de revogacao tambem cola (procedencia preservada)",
    reflow("I - a partir de 2019: 2.500 kW;\n(Revogado pela REN ANEEL 1.059, de 07.02.2023)\n"),
    "I - a partir de 2019: 2.500 kW; (Revogado pela REN ANEEL 1.059, de 07.02.2023)\n",
)

print("\nnormalizacao unicode: resolve ligadura, preserva ordinal")
checar(
    "ligadura ﬁ expandida",
    normalizar_unicode("ﬁscalização"),
    "fiscalização",
)
checar("ordinal masculino preservado", normalizar_unicode("nº 1.031"), "nº 1.031")
checar("ordinal em data preservado", normalizar_unicode("1º de julho"), "1º de julho")
checar("ordinal feminino preservado", normalizar_unicode("1ª via"), "1ª via")
checar(
    "ligadura e ordinal na mesma linha",
    normalizar_unicode("Art. 1º da veriﬁcação"),
    "Art. 1º da verificação",
)

print("\nreparo de palavra partida por ligadura")
for partida, inteira in [
    ("identific acao", "identificacao"),
    ("verific ar", "verificar"),
    ("classific adas", "classificadas"),
    ("definiç ão", "definição"),          # quebra apos ç, com acento na direita
    ("notific ações", "notificações"),
    ("conflit os", "conflitos"),           # quebra apos t
    ("fix ado", "fixado"),                 # quebra apos x
    ("beneficiad as", "beneficiadas"),     # quebra apos d
    ("suficien te", "suficiente"),         # caso "-n te"
    ("insuficien te", "insuficiente"),
    ("flutuan te", "flutuante"),
]:
    checar(f"{partida!r} remontada", repara_quebra_de_ligadura(partida)[0], inteira)

# Falsos positivos reais, colhidos rodando a regra contra o PDF da norma.
for legitima in ["para fins de", "o perfil de carga", "que se beneficia ou utiliza",
                 "verifique nas condicoes", "classificada na modalidade",
                 "o prazo definido no contrato", "simplificado para o consumidor",
                 "eficaz no prazo", "meio eficaz de comunicacao"]:
    checar(f"{legitima!r} preservada", repara_quebra_de_ligadura(legitima)[0], legitima)

checar(
    "juncoes sao registradas para auditoria, nao so contadas",
    repara_quebra_de_ligadura("identific acao e verific acao para fins de teste")[1],
    ["identific acao", "verific acao"],
)

print("\ndeteccao de cabecalho/rodape")
paginas = [
    f"AGENCIA NACIONAL DE ENERGIA ELETRICA - ANEEL\nArt. {i}o Conteudo unico da pagina {i}.\n"
    f"Pagina {i} de 4"
    for i in range(1, 5)
]
boilerplate = detectar_boilerplate(paginas, ratio_minimo=0.5, linhas_por_borda=3)
checar(
    "cabecalho fixo detectado",
    "agencia nacional de energia eletrica - aneel" in boilerplate,
    True,
)
checar(
    "rodape com numero variavel detectado (digitos mascarados)",
    "pagina # de #" in boilerplate,
    True,
)
checar(
    "linha de conteudo nao entra no boilerplate",
    any(c.startswith("art.") for c in boilerplate),
    False,
)
limpa, removidas = limpar_pagina(paginas[0], boilerplate, remover_paginacao=True)
checar("limpar_pagina remove as 2 linhas de borda", removidas, 2)
checar("limpar_pagina preserva o conteudo", limpa.strip(), "Art. 1o Conteudo unico da pagina 1.")

print("\npaginacao isolada")
for candidata in ["12", "Pagina 7", "3 de 210", "fls. 88", "7/210"]:
    checar(f"{candidata!r} e paginacao", bool(RE_SO_PAGINACAO.match(candidata)), True)
for candidata in ["Art. 12", "75 kW e o limite", "II - do prazo"]:
    checar(f"{candidata!r} NAO e paginacao", bool(RE_SO_PAGINACAO.match(candidata)), False)

print("\nrelatorio de artigos (teste de sanidade da extracao)")
checar(
    "sequencia completa nao acusa buraco",
    relatorio_artigos("Art. 1o a\n\nArt. 2o b\n\nArt. 3o c\n"),
    ([1, 2, 3], []),
)
checar(
    "artigo perdido na extracao e detectado",
    relatorio_artigos("Art. 1o a\n\nArt. 2o b\n\nArt. 5o c\n"),
    ([1, 2, 5], [3, 4]),
)
checar("texto sem artigo nenhum", relatorio_artigos("nada aqui\n"), ([], []))

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    raise SystemExit(1)
print("Todos os testes passaram.")

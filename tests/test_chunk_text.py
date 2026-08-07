"""
Testes do chunking (Bloco 2), sem depender do arquivo de texto extraido.

    .venv\\Scripts\\python.exe tests/test_chunk_text.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from chunk_text import (  # noqa: E402
    SITUACAO_REVOGADO,
    SITUACAO_VIGENTE,
    Unidade,
    agrupar,
    atualizar_hierarquia,
    fragmentar,
    marcar_superados,
    montar_chunks,
    normas_alteradoras,
    parsear,
)

falhas: list[str] = []


def checar(nome: str, obtido, esperado) -> None:
    if obtido == esperado:
        print(f"  ok   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}\n        esperado: {esperado!r}\n        obtido:   {obtido!r}")


print("deteccao de redacao superada (o defeito mais silencioso do texto compilado)")
checar(
    "versoes adjacentes: a antiga e marcada, a nova nao",
    marcar_superados([
        "Art. 96. No caso de conexao, a distribuidora e responsavel.",
        "Art. 96. No caso de conexao que nao utilize o processo, a distribuidora e "
        "responsavel. (Redação dada pela REN ANEEL 1.110, de 10.12.2024)",
    ]),
    [True, False],
)
checar(
    "versoes separadas pelos subordinados da antiga (formato do Art. 144)",
    marcar_superados([
        "Art. 144. Quando houver recusa injustificada, a distribuidora deve:",
        "I - notificar o consumidor pelo menos duas vezes;",
        "Art. 144. Quando houver recusa, a distribuidora deve: (Redação dada pela REN ANEEL "
        "1.095, de 18.06.2024)",
        "I - notificar o consumidor; (Redação dada pela REN ANEEL 1.095, de 18.06.2024)",
    ]),
    [True, True, False, False],
)
checar(
    "inciso com duas versoes dentro do mesmo artigo",
    marcar_superados([
        "Art. 21. Compete ao consumidor:",
        "IV - pagar a participacao financeira por meio de boleto;",
        "IV - pagar, por meio de boleto, PIX ou QR Code, a participacao financeira; "
        "(Redação dada pela REN ANEEL 1.095, de 18.06.2024)",
    ]),
    [False, True, False],
)

# Falso positivo que a regra precisa evitar: alineas "a)" se repetem sob incisos diferentes.
checar(
    "alineas homonimas sob incisos diferentes nao sao versoes",
    marcar_superados([
        "I-A - autoconsumo remoto: modalidade caracterizada por:",
        "a) unidades consumidoras de mesma titularidade;",
        "I-B - autoconsumo local: modalidade caracterizada por:",
        "a) titularidade de uma pessoa fisica ou juridica;",
    ]),
    [False, False, False, False],
)
checar(
    "sem nota de 'Redação dada' nada e marcado",
    marcar_superados(["Art. 5. Texto um.", "Art. 5. Texto dois."]),
    [False, False],
)
checar(
    "dispositivo diferente logo depois nao dispara",
    marcar_superados([
        "Art. 5. Texto.",
        "Art. 6. Outro texto. (Redação dada pela REN ANEEL 1.095, de 18.06.2024)",
    ]),
    [False, False],
)

print("\ntrilha estrutural")
h = atualizar_hierarquia("TÍTULO I PARTE GERAL", {})
h = atualizar_hierarquia("CAPÍTULO II DA CONEXÃO Seção I Das Disposições Gerais", h)
checar("titulo preservado", h["titulo"], "Título I - PARTE GERAL")
checar("capitulo e secao na mesma linha", (h["capitulo"], h["secao"]),
       ("Capítulo II - DA CONEXÃO", "Seção I - Das Disposições Gerais"))
h2 = atualizar_hierarquia("Seção II Da Tensão de Conexão", h)
checar("secao nova mantem o capitulo", h2["capitulo"], "Capítulo II - DA CONEXÃO")
h3 = atualizar_hierarquia("Subseção I Do Prazo", h2)
h4 = atualizar_hierarquia("Seção III Do Ponto de Conexão", h3)
checar("secao nova invalida a subsecao anterior", "subsecao" in h4, False)
checar(
    "nota de alteracao sai do nome do capitulo (ela iria para todo chunk do capitulo)",
    atualizar_hierarquia(
        "CAPÍTULO XI DA MICROGERAÇÃO E MINIGERAÇÃO DISTRIBUÍDA (Incluído pela REN ANEEL "
        "1.059, de 07.02.2023)", {}
    )["capitulo"],
    "Capítulo XI - DA MICROGERAÇÃO E MINIGERAÇÃO DISTRIBUÍDA",
)

print("\nnormas alteradoras")
checar(
    "extrai e nao repete",
    normas_alteradoras("texto (Incluído pela REN ANEEL 1.059, de 07.02.2023) mais texto "
                       "(Redação dada pela REN ANEEL 1.059, de 07.02.2023) e "
                       "(Revogado pela REN ANEEL 1.098, de 23.07.2024)"),
    ["REN ANEEL 1.059/2023", "REN ANEEL 1.098/2024"],
)

print("\nfragmentacao de unidade grande: a cabeca e repetida, nunca omitida")
unidade = Unidade("Art. 2. Sao adotadas as seguintes definicoes:", "caput")
for i in range(6):
    unidade.linhas.append(f"{'I' * (i + 1)} - definicao numero {i} com texto de enchimento;")
partes = fragmentar(unidade, max_chars=120)
checar("gerou mais de um fragmento", len(partes) > 1, True)
checar("todo fragmento comeca pelo caput",
       all(p.texto.startswith("Art. 2. Sao adotadas") for p in partes), True)
checar("nenhum subordinado se perdeu",
       sum(p.n_dispositivos for p in partes), 6)

print("\nagrupamento nunca mistura situacoes")
vigente = Unidade("§ 1º Texto vigente.", "paragrafo")
revogado = Unidade("§ 2º Texto antigo. (Revogado pela REN ANEEL 1.059, de 07.02.2023)",
                   "paragrafo")
grupos = agrupar([vigente, revogado], max_chars=5000)
checar("vigente e revogado ficam em grupos separados", len(grupos), 2)
checar("situacoes corretas", [g[0].situacao for g in grupos],
       [SITUACAO_VIGENTE, SITUACAO_REVOGADO])

print("\npipeline completo em miniatura")
blocos = [
    "TÍTULO II PARTE ESPECIAL",
    "CAPÍTULO XI DA MICROGERAÇÃO E MINIGERAÇÃO DISTRIBUÍDA",
    "Art. 655-C. O consumidor interessado deve apresentar garantia.",
    "§ 1º O valor deve ser calculado pela equacao. (Incluído pela REN ANEEL 1.059, de "
    "07.02.2023)",
    "§ 2º Texto antigo. (Revogado pela REN ANEEL 1.081, de 12.12.2023)",
]
artigos, preambulo = parsear(blocos)
chunks = montar_chunks(artigos, max_chars=1200)
checar("preambulo vazio", preambulo, [])
checar("um artigo", [a.rotulo for a in artigos], ["Art. 655-C"])
checar("revogado nao compartilha chunk com vigente",
       sorted({c["situacao"] for c in chunks}), [SITUACAO_REVOGADO, SITUACAO_VIGENTE])
vig = next(c for c in chunks if c["situacao"] == SITUACAO_VIGENTE)
checar("trilha completa", vig["trilha"],
       ["Título II - PARTE ESPECIAL",
        "Capítulo XI - DA MICROGERAÇÃO E MINIGERAÇÃO DISTRIBUÍDA"])
checar("alteracoes registradas", vig["alteracoes"], ["REN ANEEL 1.059/2023"])
checar("texto_busca leva a trilha", vig["texto_busca"].startswith("Art. 655-C (Título II"), True)
checar("texto exibido nao leva a trilha", vig["texto"].startswith("Art. 655-C. O consumidor"),
       True)
rev = next(c for c in chunks if c["situacao"] == SITUACAO_REVOGADO)
checar("chunk revogado carrega o caput como contexto na busca",
       "Art. 655-C. O consumidor interessado" in rev["texto_busca"], True)
checar("mas o texto exibido e so o dispositivo revogado",
       rev["texto"].startswith("§ 2º"), True)

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    raise SystemExit(1)
print("Todos os testes passaram.")

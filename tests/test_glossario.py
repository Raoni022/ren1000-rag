"""
Testes do glossário (Bloco 7): a ponte entre o vocabulário de quem pergunta e o da norma.

    .venv\\Scripts\\python.exe tests/test_glossario.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.glossario import expandir  # noqa: E402

falhas: list[str] = []


def checar(nome: str, obtido, esperado) -> None:
    if obtido == esperado:
        print(f"  ok   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}\n        esperado: {esperado!r}\n        obtido:   {obtido!r}")


print("vocabulário do arcabouço revogado, ainda em uso corrente")
for pergunta in [
    "Qual o prazo para analisar um pedido de acesso?",
    "Como faço a solicitação de acesso?",
    "Quanto tempo leva o parecer de acesso?",
    "Quais documentos vão no protocolo de acesso?",
    "Preciso de acesso à rede da distribuidora",
]:
    _, termos = expandir(pergunta)
    checar(f"{pergunta[:44]!r}", termos, ["orçamento de conexão"])

print("\nlinguagem do consumidor final")
casos = [
    ("Minha conta de luz veio alta", ["fatura"]),
    ("por que houve corte de energia?", ["suspensão do fornecimento"]),
    ("como faço a troca de titularidade?", ["alteração de titularidade"]),
    ("o que significa bandeira vermelha?", ["bandeiras tarifárias"]),
    ("preciso de projeto para instalar placa solar?", ["microgeração distribuída"]),
    ("regras para energia solar em casa", ["microgeração distribuída"]),
]
for pergunta, esperado in casos:
    _, termos = expandir(pergunta)
    checar(f"{pergunta[:44]!r}", termos, esperado)

print("\no termo é acrescentado, não substituído")
expandida, _ = expandir("Minha conta de luz veio alta")
checar("mantém a pergunta original", "conta de luz veio alta" in expandida, True)
checar("acrescenta o termo da norma", expandida.endswith("fatura"), True)

print("\nnão dispara onde não deve")
for pergunta in [
    "Por quanto tempo valem os créditos de energia?",
    "É obrigatório ter responsável técnico?",
    "Qual a diferença entre microgeração e minigeração?",
]:
    checar(f"{pergunta[:44]!r}", expandir(pergunta), (pergunta, []))

# "gato" dentro de "obrigatório" tem 8 ocorrências no corpus: por isso o casamento usa \b.
checar("não casa termo dentro de outra palavra",
       expandir("é obrigatório ter contador?")[1], [])

print("\numa pergunta pode acionar mais de uma entrada")
_, termos = expandir("a conta de luz subiu depois que instalei placa solar")
checar("acumula sem repetir", sorted(termos), ["fatura", "microgeração distribuída"])

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    raise SystemExit(1)
print("Todos os testes passaram.")

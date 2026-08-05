"""
Testes do Bloco 6: a interface constrói e a formatação está correta.

Não sobe servidor nem chama API. O que se testa é o que quebra o Space em produção -- a
interface montar com a versão instalada do Gradio -- e a formatação que o usuário lê, incluindo
a marcação de dispositivo revogado.

    .venv\\Scripts\\python.exe tests/test_app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SITUACAO_REVOGADO, SITUACAO_SUPERADO, SITUACAO_VIGENTE  # noqa: E402
from src.retriever import Resultado  # noqa: E402

falhas: list[str] = []


def checar(nome: str, obtido, esperado) -> None:
    if obtido == esperado:
        print(f"  ok   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}\n        esperado: {esperado!r}\n        obtido:   {obtido!r}")


def trecho(artigo="Art. 655-L", situacao=SITUACAO_VIGENTE, alteracoes=None) -> Resultado:
    return Resultado(
        artigo=artigo,
        texto="Art. 655-L. Os créditos expiram em 60 meses.\n§ 1º Depois disso, revertem.",
        trilha=["Título II - PARTE ESPECIAL", "Capítulo XI - DA MICROGERAÇÃO"],
        situacao=situacao,
        alteracoes=alteracoes or ["REN ANEEL 1.059/2023"],
        score=0.884,
        id="art655-L#0",
    )


print("a interface constrói com a versão instalada do Gradio")
import gradio as gr  # noqa: E402

import app  # noqa: E402

checar("versão do Gradio satisfaz o requirements", int(gr.__version__.split(".")[0]) >= 5, True)
checar("app expõe o Blocks para o Space", isinstance(app.demo, gr.Blocks), True)
checar("retriever instanciado uma vez", app.retriever is not None, True)
checar("generator instanciado uma vez", app.generator is not None, True)

print("\nformatação das fontes: o usuário precisa conseguir conferir contra a norma")
saida = app.formatar_fontes([trecho()])
checar("numera o trecho", saida.startswith("**1. Art. 655-L**"), True)
checar("rotula o score como semântico, já que a ordem vem da fusão com a busca léxica",
       "similaridade semântica 0.884" in saida, True)
checar("mostra a trilha estrutural", "Título II - PARTE ESPECIAL" in saida, True)
checar("mostra a procedência da alteração", "REN ANEEL 1.059/2023" in saida, True)
checar("texto da norma vai em blockquote, separado do que o sistema escreve",
       "> Art. 655-L. Os créditos expiram em 60 meses." in saida, True)
checar("todas as linhas do texto entram no blockquote",
       "> § 1º Depois disso, revertem." in saida, True)

print("\nvigência fica visível, não só nos metadados")
checar("dispositivo vigente não recebe marca",
       "⚠️" not in app.formatar_fontes([trecho()]), True)
checar("revogado é marcado",
       "REVOGADO" in app.formatar_fontes([trecho(situacao=SITUACAO_REVOGADO)]), True)
checar("redação anterior é marcada",
       "REDAÇÃO ANTERIOR" in app.formatar_fontes([trecho(situacao=SITUACAO_SUPERADO)]), True)
checar("sem trechos não quebra o layout",
       app.formatar_fontes([]), "_Nenhum trecho recuperado._")

print("\navisos do gerador chegam à interface")
checar("sem avisos, nada é exibido", app.formatar_avisos([]), "")
checar("cada aviso vira uma linha",
       app.formatar_avisos(["CITACAO_NAO_RECUPERADA: ...", "RESSALVA Art. 323: ..."]).count("⚠️"),
       2)

print("\npergunta vazia não dispara busca")
resposta, avisos, fontes = app.responder("   ", 5, False)
checar("resposta vazia", resposta, "")
checar("orienta o usuário", "Digite uma pergunta" in fontes, True)

print("\nfalha da API é traduzida para linguagem de usuário")
checar("estouro de cota não vira traceback",
       "cota diária" in app._explicar_falha(RuntimeError(
           "Error code: 429 - rate_limit_exceeded: tokens per day (TPD)")), True)
checar("chave inválida é identificada",
       "Chave de API inválida" in app._explicar_falha(RuntimeError(
           "Error code: 401 - {'code': 'invalid_api_key'}")), True)
checar("falha desconhecida mostra o erro original",
       "coisa estranha" in app._explicar_falha(RuntimeError("coisa estranha")), True)

print("\nfalha do LLM não derruba a interface")
class GeneratorQuebrado:
    def responder(self, *a, **kw):
        raise RuntimeError("cota estourada")

original_gen, original_chave = app.generator, app.tem_chave
app.generator, app.tem_chave = GeneratorQuebrado(), True
try:
    # Retriever real, com o índice do repositório: exercita o caminho completo até o gerador.
    resposta, avisos, fontes = app.responder("prazo de analise do pedido de acesso", 2, False)
    checar("avisa sobre a falha", "cota estourada" in avisos, True)
    checar("explica que a busca continua funcionando", "busca continua" in avisos, True)
    checar("mas ainda entrega os trechos recuperados", "**1. Art." in fontes, True)
finally:
    app.generator, app.tem_chave = original_gen, original_chave

print("\nsem chave, o app vira ferramenta de busca em vez de quebrar")
app.tem_chave = False
try:
    resposta, avisos, fontes = app.responder("validade dos creditos de energia", 2, False)
    checar("não redige resposta", resposta, "")
    checar("explica o motivo", "LLM_API_KEY" in avisos, True)
    checar("entrega os trechos assim mesmo", "**1. Art." in fontes, True)
finally:
    app.tem_chave = original_chave

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    raise SystemExit(1)
print("Todos os testes passaram.")

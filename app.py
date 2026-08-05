"""
Bloco 6 do plano: interface Gradio. Ponto de entrada do Hugging Face Space.

    .venv\\Scripts\\python.exe app.py


DEGRADA PARA BUSCA QUANDO NAO HA CHAVE DE LLM

Sem LLM_API_KEY o app nao quebra: ele continua recuperando e exibindo os trechos da norma,
apenas sem o paragrafo de resposta redigida. Isso e util de verdade -- o projeto se descreve
como ferramenta de busca e apoio a leitura, e a parte de busca nao depende de API paga
nenhuma. Tambem evita que o Space publicado fique inutilizavel se a chave expirar ou estourar
a cota do free tier.


CARREGAMENTO UNICO

Retriever e Generator sao instanciados uma vez, no import, e reaproveitados em toda pergunta.
O modelo de embedding tem ~470 MB: recarregar por requisicao inviabilizaria o Space gratuito.
"""

from __future__ import annotations

import os

import gradio as gr
from dotenv import load_dotenv

from src.config import SITUACAO_VIGENTE
from src.generator import FRASE_SEM_RESPOSTA, Generator
from src.retriever import Retriever

load_dotenv()

TITULO = "Busca na REN ANEEL 1.000/2021"

DISCLAIMER = """\
> **Ferramenta de busca e apoio à leitura — não é aconselhamento jurídico, regulatório ou
> técnico, e não substitui a leitura da norma oficial da ANEEL.** As respostas são geradas a
> partir dos trechos recuperados e podem conter erros de recuperação ou de interpretação.
> Para qualquer decisão com efeito real, confira o texto oficial e consulte um profissional
> habilitado.
"""

PERGUNTAS_EXEMPLO = [
    "Por quanto tempo valem os créditos de energia do sistema de compensação?",
    "Qual o prazo para a distribuidora analisar um pedido de acesso à rede?",
    "Quando é exigida a garantia de fiel cumprimento na minigeração distribuída?",
    "O que acontece se o consumidor recusar assinar o contrato?",
    "Qual o preço de um painel solar?",
]

retriever = Retriever()
generator = Generator()
tem_chave = bool(os.getenv("LLM_API_KEY"))


def _rotulo_situacao(situacao: str) -> str:
    return {
        "revogado": " · ⚠️ REVOGADO",
        "redacao_anterior": " · ⚠️ REDAÇÃO ANTERIOR",
    }.get(situacao, "")


def formatar_fontes(trechos) -> str:
    """Os trechos literais da norma, para o usuário conferir a resposta contra a fonte."""
    if not trechos:
        return "_Nenhum trecho recuperado._"

    partes = []
    for i, t in enumerate(trechos, 1):
        # "semântica" no rótulo não é preciosismo: a ordem da lista vem da fusão com a busca
        # léxica, então o número não decresce monotonicamente e sem o rótulo pareceria erro.
        cabecalho = (f"**{i}. {t.artigo}**{_rotulo_situacao(t.situacao)} · "
                     f"similaridade semântica {t.score:.3f}")
        linhas = [cabecalho]
        if t.trilha:
            linhas.append(f"<sub>{' › '.join(t.trilha)}</sub>")
        if t.alteracoes:
            linhas.append(f"<sub>Alterado por: {', '.join(t.alteracoes)}</sub>")
        # Blockquote para o texto da norma ficar visualmente separado do que o sistema escreve.
        linhas.append("\n".join(f"> {l}" for l in t.texto.split("\n")))
        partes.append("\n\n".join(linhas))

    return "\n\n---\n\n".join(partes)


_AVISO_SO_BUSCA = (
    "A busca continua funcionando: os trechos da norma abaixo são o resultado da recuperação."
)


def _explicar_falha(erro: Exception) -> str:
    """Traduz a falha da API para algo que o usuário do Space consiga entender.

    O estouro de cota é o caso esperado, não o excepcional: o free tier da Groq dá 100 mil
    tokens por dia para o llama-3.3-70b, e cada pergunta consome ~2,5 mil com k=8. Algumas
    dezenas de perguntas zeram a cota diária de um Space público, e mostrar o traceback bruto
    faria parecer que a ferramenta quebrou, quando ela apenas ficou sem orçamento até o dia
    seguinte.
    """
    texto = str(erro)
    if "rate_limit" in texto or "429" in texto:
        return (
            "⏳ A cota diária do modelo de linguagem acabou, então a resposta redigida está "
            "indisponível até a cota renovar."
        )
    if "invalid_api_key" in texto or "401" in texto:
        return "⚠️ Chave de API inválida ou de provedor diferente do configurado."
    return f"⚠️ Falha ao chamar o modelo de linguagem: {erro}"


def formatar_avisos(avisos: list[str]) -> str:
    if not avisos:
        return ""
    return "\n".join(f"⚠️ {aviso}" for aviso in avisos)


def responder(pergunta: str, k: int, incluir_nao_vigentes: bool):
    """Retorna (resposta, avisos, fontes) já formatados para a interface."""
    pergunta = (pergunta or "").strip()
    if not pergunta:
        return "", "", "_Digite uma pergunta sobre a REN 1.000/2021._"

    situacoes = None if incluir_nao_vigentes else (SITUACAO_VIGENTE,)
    trechos = retriever.buscar(pergunta, k=int(k), situacoes=situacoes)
    fontes = formatar_fontes(trechos)

    if not tem_chave:
        aviso = (
            "ℹ️ `LLM_API_KEY` não configurada: o app está funcionando apenas como busca. "
            "Os trechos abaixo são o resultado da recuperação, sem resposta redigida."
        )
        return "", aviso, fontes

    try:
        resposta = generator.responder(pergunta, trechos)
    except Exception as erro:  # a interface nao pode cair por falha de API
        return "", f"{_explicar_falha(erro)}\n\n{_AVISO_SO_BUSCA}", fontes

    texto = resposta.texto or FRASE_SEM_RESPOSTA
    if resposta.artigos_citados:
        texto += f"\n\n<sub>Artigos citados: {', '.join(resposta.artigos_citados)}</sub>"

    return texto, formatar_avisos(resposta.avisos), fontes


with gr.Blocks(title=TITULO) as demo:
    gr.Markdown(f"# {TITULO}")
    gr.Markdown(
        "Pergunte em português sobre a norma que rege a prestação do serviço público de "
        "distribuição de energia elétrica, incluindo micro e minigeração distribuída. "
        "A resposta cita o artigo, e o trecho original aparece ao lado para conferência."
    )
    gr.Markdown(DISCLAIMER)

    with gr.Row():
        with gr.Column(scale=3):
            entrada = gr.Textbox(
                label="Pergunta",
                placeholder="Ex.: por quanto tempo valem os créditos de energia?",
                lines=2,
            )
        with gr.Column(scale=1):
            k = gr.Slider(1, 10, value=5, step=1, label="Trechos recuperados")
            incluir = gr.Checkbox(
                value=False,
                label="Incluir revogados e redações anteriores",
                info="Por padrão a busca devolve apenas dispositivos em vigor.",
            )

    botao = gr.Button("Perguntar", variant="primary")

    saida_resposta = gr.Markdown(label="Resposta")
    saida_avisos = gr.Markdown()
    with gr.Accordion("Trechos da norma (fonte da resposta)", open=True):
        saida_fontes = gr.Markdown()

    gr.Examples(examples=[[p] for p in PERGUNTAS_EXEMPLO], inputs=[entrada])

    gr.Markdown(
        "<sub>Corpus: texto compilado da "
        "[REN 1.000/2021](https://www2.aneel.gov.br/cedoc/ren20211000.html), 679 artigos, com "
        "as alterações até a REN 1.110/2024. Dispositivos revogados e redações anteriores são "
        "identificados e ficam fora da busca por padrão. "
        "[Código no GitHub](https://github.com/Raoni022/ren1000-rag).</sub>"
    )

    entradas = [entrada, k, incluir]
    saidas = [saida_resposta, saida_avisos, saida_fontes]
    # api_name deixa o handler endereçável por HTTP, o que permite testar o servidor sem
    # navegador e usar o Space como API.
    botao.click(responder, inputs=entradas, outputs=saidas, api_name="responder")
    entrada.submit(responder, inputs=entradas, outputs=saidas, api_name=False)


if __name__ == "__main__":
    # No Gradio 6 o tema saiu do construtor do Blocks para o launch().
    demo.launch(theme=gr.themes.Soft())

"""
Bloco 7 do plano: roda a bateria de aceitação e mede o sistema.

    .venv\\Scripts\\python.exe scripts/avaliar.py --so-busca      # sem LLM, sem custo
    .venv\\Scripts\\python.exe scripts/avaliar.py                 # completo, exige LLM_API_KEY
    .venv\\Scripts\\python.exe scripts/avaliar.py --output docs/AVALIACAO.md

Existe para que toda mudança de recuperação seja avaliada em vez de suposta. Já aconteceu
neste projeto de uma hipótese plausível e bem medida em pequeno ("a definição isolada pontua
mais que o chunk empacotado") piorar o resultado quando aplicada de verdade -- o efeito só
apareceu porque havia como medir.

DUAS MÉTRICAS, DE PROPÓSITO SEPARADAS

  recuperação  -- o artigo do gabarito está entre os k trechos devolvidos?
  aceitação    -- a resposta final cita o artigo certo, ou recusa quando deve?

A separação importa porque as duas falham por motivos diferentes e se consertam em lugares
diferentes. Rodar só a métrica de recuperação (--so-busca) não custa nada e não chama API,
então dá para iterar no retriever sem gastar cota.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from src.retriever import K_PADRAO, Retriever  # noqa: E402
from tests.perguntas_aceitacao import CRITERIO_APROVACAO, PERGUNTAS, RECUSA  # noqa: E402


def avaliar_recuperacao(retriever: Retriever, k: int) -> list[dict]:
    linhas = []
    for caso in PERGUNTAS:
        trechos = retriever.buscar(caso["pergunta"], k=k)
        artigos = [t.artigo for t in trechos]
        esperado = caso["esperado"]

        if esperado is RECUSA:
            # Não há artigo a recuperar. A recuperação não pode acertar nem errar aqui: quem
            # decide é o gerador, então o caso não entra na métrica de busca.
            posicao, ok = None, None
        else:
            posicao = next((i for i, a in enumerate(artigos, 1) if a in esperado), None)
            ok = posicao is not None

        linhas.append({**caso, "artigos": artigos, "posicao": posicao, "ok_busca": ok})
    return linhas


def avaliar_resposta(linhas: list[dict], k: int, retriever: Retriever) -> list[dict]:
    from src.generator import Generator

    gerador = Generator()
    for linha in linhas:
        trechos = retriever.buscar(linha["pergunta"], k=k)
        resposta = gerador.responder(linha["pergunta"], trechos)

        if linha["esperado"] is RECUSA:
            ok = resposta.sem_resposta
        else:
            ok = (not resposta.sem_resposta
                  and bool(set(resposta.artigos_citados) & linha["esperado"]))

        linha.update(
            texto=resposta.texto,
            citados=resposta.artigos_citados,
            recusou=resposta.sem_resposta,
            confiavel=resposta.confiavel,
            avisos=resposta.avisos,
            ok_resposta=ok,
        )
    return linhas


def render(linhas: list[dict], k: int, completo: bool) -> str:
    com_gabarito = [l for l in linhas if l["esperado"] is not RECUSA]
    acertos_busca = sum(1 for l in com_gabarito if l["ok_busca"])

    out = ["# Avaliação da bateria de aceitação", ""]
    out.append(f"`k = {k}` · {len(PERGUNTAS)} perguntas · critério: "
               f"{CRITERIO_APROVACAO}/{len(PERGUNTAS)}")
    out.append("")
    out.append(f"**Recuperação:** {acertos_busca}/{len(com_gabarito)} com o artigo do gabarito "
               f"no top-{k}.")

    if completo:
        acertos = sum(1 for l in linhas if l["ok_resposta"])
        veredito = "APROVADO" if acertos >= CRITERIO_APROVACAO else "REPROVADO"
        alucinacoes = sum(1 for l in linhas if not l.get("confiavel", True))
        out.append(f"**Aceitação:** {acertos}/{len(PERGUNTAS)} — **{veredito}**")
        out.append(f"**Citações inventadas:** {alucinacoes}")
    out.append("")

    cabecalho = "| # | Pergunta | Esperado | Busca | " + ("Resposta | Citou |" if completo else "")
    sep = "|---|---|---|---|" + ("---|---|" if completo else "")
    out += [cabecalho, sep]
    for l in linhas:
        esperado = "recusar" if l["esperado"] is RECUSA else ", ".join(sorted(l["esperado"]))
        busca = "—" if l["ok_busca"] is None else (f"✓ pos {l['posicao']}" if l["ok_busca"]
                                                   else "✗ fora do top-k")
        linha = f"| {l['id']} | {l['pergunta'][:52]} | {esperado} | {busca} |"
        if completo:
            linha += f" {'✓' if l['ok_resposta'] else '✗'} | {', '.join(l['citados']) or '—'} |"
        out.append(linha)

    out += ["", "## Detalhe por pergunta", ""]
    for l in linhas:
        out.append(f"### {l['id']}. {l['pergunta']}")
        out.append(f"*Gabarito:* {l['porque']}")
        out.append(f"*Top-{k} recuperado:* {', '.join(l['artigos'])}")
        if completo:
            out.append(f"*Resposta:* {l['texto']}")
            if l["avisos"]:
                out.append(f"*Avisos:* {'; '.join(l['avisos'])}")
        out.append("")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Avalia o sistema contra a bateria do projeto.")
    parser.add_argument("-k", type=int, default=K_PADRAO)
    parser.add_argument("--so-busca", action="store_true",
                        help="Só a métrica de recuperação: não chama o LLM, não gasta cota.")
    parser.add_argument("--sem-glossario", action="store_true",
                        help="Desliga a expansão de vocabulário, para medir o efeito dela.")
    parser.add_argument("--output", type=Path, help="Grava o relatório em markdown.")
    args = parser.parse_args()

    retriever = Retriever(expandir_consulta=not args.sem_glossario)
    linhas = avaliar_recuperacao(retriever, args.k)
    if not args.so_busca:
        linhas = avaliar_resposta(linhas, args.k, retriever)

    relatorio = render(linhas, args.k, completo=not args.so_busca)
    print(relatorio)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(relatorio + "\n", encoding="utf-8", newline="\n")
        print(f"\nEscrito: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

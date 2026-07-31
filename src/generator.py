"""
Bloco 5 do plano: pergunta + trechos recuperados -> resposta citando o artigo.

Uso:

    from src.retriever import Retriever
    from src.generator import Generator

    r, g = Retriever(), Generator()
    trechos = r.buscar("prazo para analisar pedido de acesso", k=5)
    print(g.responder("prazo para analisar pedido de acesso", trechos).texto)

Pela linha de comando, com --dry-run para ver o prompt sem gastar chamada:

    .venv\\Scripts\\python.exe -m src.generator "prazo do pedido de acesso" --dry-run


PROVEDOR: QUALQUER UM COMPATIVEL COM A API DA OPENAI

Groq, Gemini, DeepSeek e OpenRouter expoem a mesma interface de chat completions, entao trocar
de provedor e mudar LLM_BASE_URL e LLM_MODEL -- nao mexer neste arquivo. Isso importa aqui
porque a escolha e por preco, e preco de LLM muda mais rapido que codigo.

Configuracao por ambiente (.env em dev local, secret do Space em producao):

    LLM_API_KEY   = chave do provedor
    LLM_BASE_URL  = https://api.groq.com/openai/v1
                    https://generativelanguage.googleapis.com/v1beta/openai
    LLM_MODEL     = llama-3.3-70b-versatile | gemini-2.0-flash | ...


A VERIFICACAO DE CITACAO NAO E OPCIONAL

O principio do projeto e que a IA nunca invente numero de artigo. Instruir isso no prompt
reduz o erro, mas nao o elimina -- e um erro desse tipo e especialmente danoso aqui, porque a
resposta parece verificavel justamente por citar artigo.

Entao depois da geracao o codigo extrai toda citacao "Art. N" da resposta e confere contra os
artigos efetivamente recuperados. O que nao bater vira aviso explicito em `Resposta.avisos`,
para a interface (Bloco 6) mostrar. Isso e deterministico e independe do modelo, inclusive de
um modelo barato e fraco.

Vale a divisao de trabalho estabelecida nos blocos anteriores: o retriever ja garantiu que so
texto VIGENTE chega aqui (filtro por metadado, deterministico), e cabe ao gerador decidir se
os trechos respondem a pergunta -- decisao que o Bloco 3 mostrou nao ser possivel por limiar
de score, porque sete centesimos separam pergunta legitima de teclado aleatorio.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SITUACAO_VIGENTE  # noqa: E402
from src.retriever import Resultado, Retriever  # noqa: E402

MODELO_PADRAO = "llama-3.3-70b-versatile"
BASE_URL_PADRAO = "https://api.groq.com/openai/v1"

# Frase exata que o modelo deve devolver quando os trechos nao respondem. Detectar por prefixo
# e fragil de proposito no sentido certo: se a deteccao falhar, o usuario ainda le uma resposta
# honesta -- o pior caso e um aviso a menos, nunca uma invencao a mais.
FRASE_SEM_RESPOSTA = (
    "Não encontrei essa informação nos trechos da REN 1.000/2021 recuperados para esta pergunta."
)

# Aviso obrigatorio: o preambulo da norma registra que o Despacho 2.006/2024 suspendeu por
# decisao judicial os efeitos do prazo de 60 ciclos do inciso II do art. 323.
ARTIGOS_COM_RESSALVA = {
    "Art. 323": "O Despacho ANEEL 2.006/2024 suspendeu por decisão judicial os efeitos do "
                "prazo de 60 ciclos previsto no inciso II deste artigo.",
}

RE_CITACAO = re.compile(r"\bArt\.\s*(\d+(?:-[A-Z]{1,2})?)", re.IGNORECASE)

INSTRUCOES = """Você responde perguntas sobre a Resolução Normativa ANEEL nº 1.000/2021 \
usando EXCLUSIVAMENTE os trechos fornecidos.

Regras invioláveis:
1. Use apenas o conteúdo dos trechos. Não use conhecimento próprio sobre energia elétrica, \
sobre a ANEEL ou sobre qualquer outra norma.
2. Cite o número do artigo de onde vem cada afirmação, no formato "Art. 15" ou "Art. 655-C".
3. Cite APENAS artigos que aparecem nos trechos. Nunca escreva um número de artigo que não \
esteja explicitamente listado abaixo.
4. Se os trechos não contiverem a informação pedida, responda exatamente com esta frase, \
sem acrescentar nada:
{frase_sem_resposta}
5. Responda em português do Brasil, em no máximo 6 linhas, de forma direta. Não repita a \
pergunta nem descreva o que você vai fazer.
6. Se os trechos trouxerem números, prazos ou limites, transcreva-os exatamente como estão."""


@dataclass
class Resposta:
    """Resultado da geração, com o que a interface precisa para ser auditável."""

    texto: str
    fontes: list[Resultado] = field(default_factory=list)
    artigos_citados: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)
    sem_resposta: bool = False
    prompt: str = ""

    @property
    def confiavel(self) -> bool:
        """Sem citação inventada. Não diz que a resposta está certa, só que é rastreável."""
        return not any(aviso.startswith("CITACAO_NAO_RECUPERADA") for aviso in self.avisos)


def montar_prompt(pergunta: str, trechos: list[Resultado]) -> str:
    """Monta o contexto. Cada trecho vai rotulado com o artigo, para a citação ter de onde sair."""
    partes = []
    for i, trecho in enumerate(trechos, 1):
        cabecalho = f"[Trecho {i}] {trecho.artigo}"
        if trecho.trilha:
            cabecalho += f" ({' > '.join(trecho.trilha)})"
        partes.append(f"{cabecalho}\n{trecho.texto}")

    contexto = "\n\n".join(partes) if partes else "(nenhum trecho recuperado)"
    return f"Trechos da REN 1.000/2021:\n\n{contexto}\n\nPergunta: {pergunta}"


def artigos_disponiveis(trechos: list[Resultado]) -> set[str]:
    """Artigos que o modelo tem direito de citar: os dos trechos, normalizados."""
    return {_normalizar(t.artigo) for t in trechos}


def _normalizar(rotulo: str) -> str:
    numero = RE_CITACAO.search(rotulo)
    return f"Art. {numero.group(1).upper()}" if numero else rotulo.strip()


def verificar_citacoes(texto: str, trechos: list[Resultado]) -> tuple[list[str], list[str]]:
    """Confere as citações da resposta contra os artigos recuperados.

    Devolve (artigos citados, avisos). Um artigo citado que não veio nos trechos é o erro que
    este projeto existe para não cometer, então vira aviso explícito em vez de passar batido.
    """
    disponiveis = artigos_disponiveis(trechos)
    citados: list[str] = []
    avisos: list[str] = []

    for numero in RE_CITACAO.findall(texto):
        rotulo = f"Art. {numero.upper()}"
        if rotulo not in citados:
            citados.append(rotulo)

    for rotulo in citados:
        if rotulo not in disponiveis:
            avisos.append(
                f"CITACAO_NAO_RECUPERADA: a resposta cita {rotulo}, que não está entre os "
                f"trechos recuperados. Confira no texto oficial antes de usar."
            )

    for rotulo in citados:
        if rotulo in ARTIGOS_COM_RESSALVA:
            avisos.append(f"RESSALVA {rotulo}: {ARTIGOS_COM_RESSALVA[rotulo]}")

    return citados, avisos


class Generator:
    """Formula a resposta a partir dos trechos, sem acesso a nada além deles."""

    def __init__(
        self,
        cliente=None,
        modelo: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._cliente = cliente
        self.modelo = modelo or os.getenv("LLM_MODEL", MODELO_PADRAO)
        self.base_url = base_url or os.getenv("LLM_BASE_URL", BASE_URL_PADRAO)
        self._api_key = api_key or os.getenv("LLM_API_KEY")

    @property
    def cliente(self):
        """Cliente OpenAI-compatível, criado sob demanda para o import não exigir chave."""
        if self._cliente is None:
            if not self._api_key:
                raise RuntimeError(
                    "LLM_API_KEY não definida. Configure no .env (dev) ou nos secrets do "
                    "Space (produção). LLM_BASE_URL e LLM_MODEL escolhem o provedor."
                )
            from openai import OpenAI

            self._cliente = OpenAI(api_key=self._api_key, base_url=self.base_url)
        return self._cliente

    def responder(self, pergunta: str, trechos: list[Resultado]) -> Resposta:
        prompt = montar_prompt(pergunta, trechos)

        # Sem trechos não há o que responder, e não há motivo para gastar uma chamada.
        if not trechos:
            return Resposta(texto=FRASE_SEM_RESPOSTA, sem_resposta=True, prompt=prompt)

        instrucoes = INSTRUCOES.format(frase_sem_resposta=FRASE_SEM_RESPOSTA)
        resposta = self.cliente.chat.completions.create(
            model=self.modelo,
            messages=[
                {"role": "system", "content": instrucoes},
                {"role": "user", "content": prompt},
            ],
            # Temperatura 0: a mesma pergunta sobre a mesma norma deve dar a mesma resposta.
            temperature=0,
        )
        texto = (resposta.choices[0].message.content or "").strip()

        sem_resposta = texto.lower().startswith("não encontrei")
        citados, avisos = verificar_citacoes(texto, trechos)

        if not sem_resposta and not citados:
            avisos.append(
                "SEM_CITACAO: a resposta não cita nenhum artigo. Confira nos trechos ao lado."
            )

        return Resposta(
            texto=texto,
            fontes=trechos,
            artigos_citados=citados,
            avisos=avisos,
            sem_resposta=sem_resposta,
            prompt=prompt,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Responde uma pergunta sobre a REN 1.000/2021 citando o artigo."
    )
    parser.add_argument("pergunta")
    parser.add_argument("-k", type=int, default=5, help="Quantos trechos usar como contexto.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Monta e imprime o prompt sem chamar a API. Não exige chave.",
    )
    args = parser.parse_args()

    trechos = Retriever().buscar(args.pergunta, k=args.k, situacoes=(SITUACAO_VIGENTE,))

    if args.dry_run:
        print(INSTRUCOES.format(frase_sem_resposta=FRASE_SEM_RESPOSTA))
        print("\n" + "-" * 78 + "\n")
        print(montar_prompt(args.pergunta, trechos))
        return 0

    resposta = Generator().responder(args.pergunta, trechos)
    print(resposta.texto)
    if resposta.artigos_citados:
        print(f"\nArtigos citados: {', '.join(resposta.artigos_citados)}")
    for aviso in resposta.avisos:
        print(f"\n[!] {aviso}")
    print("\nFontes:")
    for fonte in resposta.fontes:
        print(f"  - {fonte.artigo} (score {fonte.score:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

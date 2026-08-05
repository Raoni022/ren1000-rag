"""
Testes do Bloco 5, sem chamar API nenhuma.

O cliente do LLM e substituido por um dublê que devolve texto fixo. O que se testa e a camada
determinista em volta do modelo -- montagem do prompt, verificacao de citacao e deteccao de
"nao encontrei" --, que e justamente a parte que nao pode depender da boa vontade de um modelo
barato.

    .venv\\Scripts\\python.exe tests/test_generator.py
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config import SITUACAO_VIGENTE  # noqa: E402
from src.generator import (  # noqa: E402
    FRASE_SEM_RESPOSTA,
    Generator,
    artigos_disponiveis,
    montar_prompt,
    normalizar_recusa,
    verificar_citacoes,
)
from src.retriever import Resultado  # noqa: E402

falhas: list[str] = []


def checar(nome: str, obtido, esperado) -> None:
    if obtido == esperado:
        print(f"  ok   {nome}")
    else:
        falhas.append(nome)
        print(f"  FALHA {nome}\n        esperado: {esperado!r}\n        obtido:   {obtido!r}")


def trecho(artigo: str, texto: str = "texto do dispositivo") -> Resultado:
    return Resultado(artigo=artigo, texto=texto, trilha=["Título I - PARTE GERAL"],
                     situacao=SITUACAO_VIGENTE, alteracoes=[], score=0.88, id=f"{artigo}#0")


class ClienteFalso:
    """Dublê do cliente OpenAI-compatível: devolve texto fixo e guarda o que recebeu."""

    def __init__(self, resposta: str) -> None:
        self.resposta = resposta
        self.recebido = None
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.recebido = kwargs
        msg = SimpleNamespace(content=self.resposta)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


TRECHOS = [trecho("Art. 655-L", "Art. 655-L. Os créditos expiram em 60 meses."),
           trecho("Art. 96", "Art. 96. No caso de conexão de outra distribuidora.")]

print("montagem do prompt")
prompt = montar_prompt("Por quanto tempo valem os créditos?", TRECHOS)
checar("numera os trechos", "[Trecho 1]" in prompt and "[Trecho 2]" in prompt, True)
checar("rotula cada trecho com o artigo", "[Trecho 1] Art. 655-L" in prompt, True)
checar("inclui a trilha estrutural", "Título I - PARTE GERAL" in prompt, True)
checar("inclui o texto do dispositivo", "expiram em 60 meses" in prompt, True)
checar("inclui a pergunta", prompt.rstrip().endswith("Por quanto tempo valem os créditos?"), True)
checar("sem trechos, avisa em vez de mentir contexto",
       "(nenhum trecho recuperado)" in montar_prompt("qualquer", []), True)

print("\nartigos que o modelo tem direito de citar")
checar("normaliza o rótulo", artigos_disponiveis(TRECHOS), {"Art. 655-L", "Art. 96"})

print("\nverificação de citação: o erro que o projeto existe para não cometer")
citados, avisos = verificar_citacoes("Conforme o Art. 655-L, os créditos expiram.", TRECHOS)
checar("cita artigo recuperado: sem aviso", (citados, avisos), (["Art. 655-L"], []))

citados, avisos = verificar_citacoes("Conforme o Art. 999, o prazo é de 30 dias.", TRECHOS)
checar("cita artigo inventado: detectado", citados, ["Art. 999"])
checar("aviso identifica a citação",
       avisos[0].startswith("CITACAO_NAO_RECUPERADA") and "Art. 999" in avisos[0], True)

citados, _ = verificar_citacoes("Ver Art. 96 e também o Art. 96 novamente.", TRECHOS)
checar("não duplica citação repetida", citados, ["Art. 96"])

citados, _ = verificar_citacoes("O art. 655-l trata disso.", TRECHOS)
checar("reconhece citação em minúscula e com sufixo", citados, ["Art. 655-L"])

_, avisos = verificar_citacoes("Ver Art. 323.", [trecho("Art. 323")])
checar("artigo com efeito suspenso gera ressalva",
       any(a.startswith("RESSALVA Art. 323") for a in avisos), True)
checar("a ressalva explica o motivo",
       "suspendeu por decisão judicial" in avisos[0], True)

print("\ngeração com dublê")
g = Generator(cliente=ClienteFalso("Os créditos expiram em 60 meses (Art. 655-L)."))
r = g.responder("Por quanto tempo valem os créditos?", TRECHOS)
checar("devolve o texto do modelo", r.texto.startswith("Os créditos expiram"), True)
checar("registra os artigos citados", r.artigos_citados, ["Art. 655-L"])
checar("marca como confiável", r.confiavel, True)
checar("carrega as fontes para a interface", [f.artigo for f in r.fontes],
       ["Art. 655-L", "Art. 96"])
checar("temperatura zero para resposta reprodutível", g._cliente.recebido["temperature"], 0)
checar("manda instruções como system", g._cliente.recebido["messages"][0]["role"], "system")

g2 = Generator(cliente=ClienteFalso("O prazo é de 30 dias, conforme o Art. 999."))
r2 = g2.responder("qualquer", TRECHOS)
checar("citação inventada derruba a confiabilidade", r2.confiavel, False)
checar("e vira aviso para a interface",
       any(a.startswith("CITACAO_NAO_RECUPERADA") for a in r2.avisos), True)

print("\nafirmar e recusar na mesma resposta conta como recusa")
# Caso real da bateria: o modelo citou o Art. 655-C, afirmou "superior a 500 kW" (que é o
# limite da garantia de fiel cumprimento, não a fronteira micro/mini) e emendou a recusa.
misto = ("Art. 655-C. A minigeração distribuída tem potência instalada superior a 500 kW. "
         + FRASE_SEM_RESPOSTA)
checar("recusa no fim do texto é detectada", normalizar_recusa(misto)[1], True)
checar("a afirmação não sobrevive", normalizar_recusa(misto)[0], FRASE_SEM_RESPOSTA)
checar("resposta legítima não é confundida com recusa",
       normalizar_recusa("Os créditos expiram em 60 meses, Art. 655-L."),
       ("Os créditos expiram em 60 meses, Art. 655-L.", False))
g_misto = Generator(cliente=ClienteFalso(misto))
r_misto = g_misto.responder("qualquer", TRECHOS)
checar("o Generator descarta a afirmação contraditória", r_misto.sem_resposta, True)
checar("e não credita citação a uma recusa", r_misto.artigos_citados, [])

g3 = Generator(cliente=ClienteFalso(FRASE_SEM_RESPOSTA))
r3 = g3.responder("qual o preço de um painel solar?", TRECHOS)
checar("detecta o 'não encontrei'", r3.sem_resposta, True)
checar("sem resposta não gera aviso de citação ausente", r3.avisos, [])

g4 = Generator(cliente=ClienteFalso("O prazo é de 30 dias."))
r4 = g4.responder("qualquer", TRECHOS)
checar("resposta sem nenhuma citação é sinalizada",
       any(a.startswith("SEM_CITACAO") for a in r4.avisos), True)

print("\nsem trechos não gasta chamada de API")
cliente = ClienteFalso("nao deveria ser chamado")
r5 = Generator(cliente=cliente).responder("qualquer", [])
checar("responde 'não encontrei' direto", r5.sem_resposta, True)
checar("cliente não foi acionado", cliente.recebido, None)

print("\nfalta de chave falha com mensagem útil")
try:
    Generator(api_key="").cliente
    checar("erro claro sem chave", "nao levantou", "RuntimeError")
except RuntimeError as erro:
    checar("erro claro sem chave", "LLM_API_KEY" in str(erro), True)

print()
if falhas:
    print(f"{len(falhas)} FALHA(S): {', '.join(falhas)}")
    raise SystemExit(1)
print("Todos os testes passaram.")

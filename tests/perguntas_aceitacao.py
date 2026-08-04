"""
Bateria de aceitação do projeto (Bloco 7): 10 perguntas com gabarito verificado na norma.

O gabarito NÃO foi escrito de memória. Cada artigo esperado foi localizado por busca literal no
corpus e conferido no texto -- ver a coluna "por quê" de cada entrada.

As perguntas ficam no vocabulário de quem vai usar a ferramenta (instalador, cliente final), e
não no vocabulário da norma. Isso é deliberado: a bateria mede o produto, não o corpus. Duas
delas ("pedido de acesso", "protocolo de acesso") usam termos que NÃO existem na REN 1.000/2021
-- são do arcabouço antigo, revogado pela REN 1.059/2023 --, e é exatamente assim que um leigo
pergunta. Reescrevê-las no vocabulário da norma faria a métrica subir sem o produto melhorar.
"""

RECUSA = "RECUSA"  # o comportamento correto é dizer que não encontrou

PERGUNTAS = [
    {
        "id": 1,
        "pergunta": "Qual o prazo para a distribuidora analisar um pedido de acesso à rede?",
        "esperado": {"Art. 64"},
        "porque": "Art. 64: 'nos seguintes prazos, contados a partir da solicitação: I - 15 "
                  "dias [...] II - 30 dias'. A norma chama de 'orçamento de conexão'; os termos "
                  "'pedido/solicitação/parecer de acesso' têm ZERO ocorrência no corpus.",
    },
    {
        "id": 2,
        "pergunta": "Qual a diferença entre microgeração e minigeração distribuída em termos "
                    "de potência?",
        "esperado": {"Art. 2"},
        "porque": "Art. 2, XXIX-A e XXIX-B, definem micro (até 75 kW) e minigeração (acima de "
                  "75 kW até 3 ou 5 MW conforme a fonte).",
    },
    {
        "id": 3,
        "pergunta": "O sistema de compensação de energia elétrica permite acumular créditos "
                    "por quanto tempo?",
        "esperado": {"Art. 655-L"},
        "porque": "Art. 655-L: 'Os créditos de energia expiram em 60 meses após a data do "
                  "faturamento em que foram gerados.'",
    },
    {
        "id": 4,
        "pergunta": "É obrigatório ter um responsável técnico com ART para o projeto?",
        "esperado": {"Art. 33"},
        "porque": "Art. 33: 'O projeto e a execução das instalações elétricas [...] devem "
                  "possuir responsável técnico, caso seja exigível na legislação específica.'",
    },
    {
        "id": 5,
        "pergunta": "O que é o medidor bidirecional e quando ele é exigido?",
        "esperado": RECUSA,
        "porque": "A norma não define 'medidor bidirecional'. 'bidirecional' aparece uma única "
                  "vez, no Art. 555, sobre fluxo bidirecional -- outro assunto. A premissa da "
                  "pergunta é falsa, e a resposta correta é dizer que não encontrou.",
    },
    {
        "id": 6,
        "pergunta": "Quais documentos são exigidos para o protocolo de acesso?",
        "esperado": {"Art. 67"},
        "porque": "Art. 67: 'O consumidor e demais usuários devem fornecer as seguintes "
                  "informações para a elaboração do orçamento de conexão'. Mesmo descompasso "
                  "de vocabulário da pergunta 1.",
    },
    {
        "id": 7,
        "pergunta": "Existe prazo de validade para os créditos de energia gerados?",
        "esperado": {"Art. 655-L"},
        "porque": "Mesmo dispositivo da pergunta 3, formulado de outro jeito.",
    },
    {
        "id": 8,
        "pergunta": "O que muda para sistemas conectados em condomínios (geração "
                    "compartilhada)?",
        "esperado": {"Art. 2", "Art. 655-C"},
        "porque": "Art. 2, XXII-A, define geração compartilhada como modalidade do SCEE por "
                  "consórcio, cooperativa ou condomínio; o Art. 655-C enumera as modalidades "
                  "para fins de conexão. Aceita qualquer um dos dois: os dois respondem.",
    },
    {
        "id": 9,
        "pergunta": "Qual o preço de um painel solar?",
        "esperado": RECUSA,
        "porque": "Fora do escopo da norma. Testa se o sistema inventa quando não sabe.",
    },
    {
        "id": 10,
        "pergunta": "e a conta?",
        "esperado": RECUSA,
        "porque": "Pergunta ambígua e sem contexto. Testa o comportamento em entrada mal "
                  "formulada.",
    },
]

CRITERIO_APROVACAO = 8  # de 10, conforme o planejamento do projeto

# RAG sobre a REN ANEEL 1.000/2021

Busca semântica em português sobre o texto da **Resolução Normativa ANEEL nº 1.000/2021**,
a norma que estabelece as regras de prestação do serviço público de distribuição de energia
elétrica — incluindo micro e minigeração distribuída, depois das alterações da
[REN 1.059/2023](https://www2.aneel.gov.br/cedoc/ren20231059.html) (que regulamentou a
Lei 14.300/2022).

Você pergunta em linguagem natural; o sistema recupera os trechos relevantes da norma e
formula uma resposta curta **citando o número do artigo**, com o texto original visível ao
lado para conferência.

> **Status: em construção (Bloco 1 de 9 concluído).** Ainda não há demo pública. Este README
> descreve o que já roda e o que falta.

O corpus é o **texto compilado** da norma: 152 páginas, **679 artigos** (Art. 1 ao Art. 679),
já com as alterações das REN 1.059/2023, 1.081/2023, 1.095/2024 e 1.098/2024 marcadas inline.

---

## Princípio inegociável

A IA **nunca** inventa número de artigo nem conteúdo que não esteja nos trechos recuperados.
Se a busca não encontrar nada relevante na norma, a resposta é dizer que não encontrou — não
preencher a lacuna com plausibilidade. A geração de texto opera exclusivamente sobre o que o
retriever devolveu.

## ⚠️ Disclaimer

Esta é uma **ferramenta de busca e apoio à leitura**, não aconselhamento jurídico, regulatório
ou técnico, e não substitui a leitura da norma oficial publicada pela ANEEL. Respostas podem
conter erros de recuperação ou de interpretação. Para qualquer decisão com efeito real,
consulte o texto oficial e um profissional habilitado.

---

## Arquitetura

Build-time (`scripts/`, roda uma vez, offline) e runtime (`src/` + `app.py`, roda a cada
pergunta) são separados de propósito: o índice vetorial é pré-computado e versionado, para o
app nunca recalcular embeddings a cada request.

```
PDF oficial (texto consolidado)
   -> scripts/extract_text.py   -> data/ren1000_raw.txt
   -> scripts/chunk_text.py     -> index/chunks.json      (chunk + nº do artigo)
   -> scripts/build_index.py    -> index/ren1000.faiss

pergunta -> src/retriever.py (top-k no FAISS) -> src/generator.py (LLM sobre os chunks)
         -> app.py (resposta + trecho-fonte)
```

**Stack:** Python 3.11 · `sentence-transformers`
(`paraphrase-multilingual-MiniLM-L12-v2`, roda local, sem API paga na busca) · `faiss-cpu` ·
`gradio` · Gemini/Groq free tier apenas para redigir a resposta final · Hugging Face Spaces.

O corpus é uma norma única e estática, então FAISS local basta — não há motivo para banco
vetorial gerenciado aqui.

---

## Como rodar

**Python 3.11 é obrigatório.** `torch`/`faiss-cpu` ainda não publicam wheel para 3.14, que é
o interpretador default em algumas máquinas.

```bash
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

### 1. Obter o texto da norma

Baixe o **texto consolidado** da REN 1.000/2021 no
[CEDOC da ANEEL](https://www2.aneel.gov.br/cedoc/ren20211000.html) e salve como
`data/ren1000.pdf` (o PDF não é versionado; o texto extraído é).

Use o consolidado, não o PDF original de 2021: as regras de micro e minigeração distribuída
e do Sistema de Compensação de Energia Elétrica foram alteradas pela REN 1.059/2023. Indexar
o original produziria respostas com citação de artigo correta e **conteúdo revogado** — a
pior falha possível numa ferramenta como esta.

### 2. Extrair e limpar o texto

Inspecionar antes de escrever (não toca o disco):

```bash
.venv/Scripts/python.exe scripts/extract_text.py --input data/ren1000.pdf --report
```

O relatório informa páginas lidas, quais padrões foram tratados como cabeçalho/rodapé e —
principal teste de sanidade — se há **buracos na numeração dos artigos**, que indicariam
conteúdo perdido na extração. Depois de conferir:

```bash
.venv/Scripts/python.exe scripts/extract_text.py --input data/ren1000.pdf --output data/ren1000_raw.txt
```

Resultado esperado no PDF de referência: 152 páginas, 679 artigos sem buraco na sequência,
**0 palavras partidas**, ~737 mil caracteres. Leva cerca de 1 minuto.

#### Por que pdfplumber e não pypdf

Foi a decisão que mais afetou a qualidade do texto, e vale registrar porque a lição não é
específica deste projeto: **a qualidade da extração se decide na escolha da biblioteca, não no
pós-processamento.**

O pypdf falha nos dois modos que oferece:

| | `plain` | `layout` | pdfplumber |
|---|---|---|---|
| Artigos reconhecíveis (de 679) | 30 | 679 | **679** |
| Quebras após ligadura `ﬁ`/`ﬂ` | — | 570 | **0** |
| Letras soltas no meio de palavra | — | 39 | **0** |
| `identificação` inteira no documento | — | 0x | **49x** |
| Palavras coladas | sim | não | não |
| Tempo | 36s | 36s | 62s |

No modo `plain` cada página vem como uma única linha de ~5.700 caracteres, sem quebra, colando
palavras vizinhas (`consumidoracom microgeração`). No modo `layout` as quebras de linha saem
certas, mas ele insere espaços **dentro** das palavras: `identific ação`, `f aturamento`,
`fie l cumprimento`. `identificação` e `verificação` não apareciam inteiras uma vez sequer.

Chegou-se a escrever ~120 linhas de regex para remontar essas palavras — e elas funcionavam
para o caso da ligadura (589 remontagens corretas), mas não para a letra solta, que é
irrecuperável a partir do texto já extraído: o fragmento pode pertencer à palavra da esquerda
ou à da direita (`fie l cumprimento` é *"garantia de fiel cumprimento"*), o tamanho do vão não
distingue quebra interna de fronteira legítima (`fie    l` tem 4 espaços, `fiel      cumprimento`
tem 6), e juntar maiúscula quebraria incisos romanos e subgrupos tarifários reais (`V do`,
`B deve`).

O pdfplumber reconstrói a palavra pela posição dos glifos e zera os dois defeitos, o que
permitiu apagar todo esse código. O minuto a mais é irrelevante num script que roda uma vez.

Restou de guarda a função `fragmentos_orfaos()`: se a contagem de palavras partidas voltar a
subir, a extração regrediu.

### Testes

Cada script é testável isoladamente. As funções de limpeza não dependem do PDF:

```bash
.venv/Scripts/python.exe tests/test_extract_text.py
.venv/Scripts/python.exe tests/test_chunk_text.py
.venv/Scripts/python.exe tests/test_build_index.py
.venv/Scripts/python.exe tests/test_retriever.py
.venv/Scripts/python.exe tests/test_generator.py
```

Nenhum deles baixa o modelo de embedding nem chama a API do LLM: os testes do índice e da
busca usam vetores conhecidos e o do gerador usa um dublê de cliente. Cobrem a lógica que erra
em silêncio — filtro de vigência, ordenação, sincronia entre índice e chunks, e verificação de
citação.

O que **não** está coberto por teste automatizado é o comportamento do modelo real: se ele de
fato respeita "responda só com os trechos" e devolve a frase de não-encontrado quando deve.
Isso é a bateria de 10 perguntas do Bloco 7, que precisa de chave de API.

---

### 3. Dividir em chunks

```bash
.venv/Scripts/python.exe scripts/chunk_text.py --report
.venv/Scripts/python.exe scripts/chunk_text.py --output index/chunks.json
```

Saída: **1.188 chunks** — 1.080 vigentes, 21 revogados, 87 de redação anterior. Mediana de 524
caracteres, p99 de 1.194.

**A unidade é o dispositivo com seus subordinados**, não o artigo nem o dispositivo isolado.
Medido: por dispositivo a mediana é 146 caracteres, e `II - permitir a leitura` não significa
nada fora do caput que o rege; por artigo inteiro, 52% passam de 500 caracteres e o Art. 2
(definições) tem 20 mil, o que dilui o vetor a ponto de não ser recuperável. Então o caput
entra com os incisos que dependem dele, cada parágrafo com os seus, e unidades do mesmo artigo
são empacotadas até `--max-chars`. Quando uma unidade sozinha estoura o teto, ela é fatiada
**repetindo o caput** em cada pedaço — nenhum inciso vai para o índice sem o texto que lhe dá
sentido.

Cada chunk tem dois campos de texto, de propósito: `texto` é o trecho literal, para exibir ao
usuário conferir; `texto_busca` é o mesmo trecho precedido da trilha estrutural e do caput do
artigo, e é o que o Bloco 3 vetoriza. Um `§ 2º O prazo é de 30 dias` só é recuperável por
"prazo de análise de pedido de acesso" se o vetor souber de que artigo e capítulo ele veio.

### 4. Gerar embeddings e o índice FAISS

```bash
.venv/Scripts/python.exe scripts/build_index.py
```

Saída: `index/ren1000.faiss`, 1.188 vetores de 384 dimensões, 1,7 MB. Leva ~3,5 min em CPU.

**Modelo: `intfloat/multilingual-e5-small`.** O `paraphrase-multilingual-MiniLM-L12-v2` do
plano original foi descartado por medição: janela de 128 tokens contra chunks de até 1.200
caracteres. Com o e5-small (512 tokens), a medição real com o tokenizador do modelo dá mediana
de 182 tokens, p99 de 427 e **apenas 1 chunk truncado** em 1.188.

Dois detalhes que não geram erro quando errados, só degradam a busca em silêncio — e por isso
estão em constantes compartilhadas com o retriever:

- **Os prefixos do E5 não são opcionais.** O modelo é treinado com prefixo assimétrico:
  documentos entram como `passage: ` e perguntas como `query: `. Omitir não quebra nada, só
  piora a recuperação.
- **`IndexFlatIP` sobre vetores normalizados em L2.** Com norma 1, o produto interno é
  idêntico ao cosseno, que é a métrica para a qual o E5 foi treinado. `IndexFlatL2` daria
  ordenação diferente e pior. O script falha explicitamente se a normalização não bater.

`Flat` (força bruta, sem quantização) porque 1.188 vetores de 384 dimensões ocupam ~1,8 MB e a
busca exata leva menos de um milissegundo. IVF ou HNSW só compensam em corpus ordens de
grandeza maiores, e custariam recall.

### 5. Buscar

```bash
.venv/Scripts/python.exe -m src.retriever "prazo para analisar pedido de acesso" -k 3
```

`src/retriever.py` carrega modelo, índice e chunks sob demanda e mantém em cache na instância —
dentro do app, uma instância atende todas as perguntas sem recarregar 470 MB por requisição.

**O filtro de vigência mora aqui, não no prompt.** Dos 1.188 chunks, 108 não estão em vigor.
O padrão devolve só `vigente`, porque o que não chega ao contexto não pode ser citado por
engano — deixar o LLM julgar vigência seria pedir a ele algo que o metadado já resolve de forma
determinística. `situacoes=None` desliga o filtro, para perguntas do tipo "o que este artigo
dizia antes?".

O carregamento confere que o índice e o `chunks.json` têm o mesmo tamanho. Se vierem de
execuções diferentes, a posição no índice deixa de apontar para o artigo certo e a busca passa
a devolver **o artigo errado para o vetor certo**, sem erro nenhum.

Modelo e prefixos do E5 ficam em `src/config.py`, lido tanto pelo build quanto pela busca. A
dependência aponta de `scripts/` para `src/`, nunca o contrário: o índice tem que ser
construído com o que o runtime espera.

### 6. Responder

```bash
cp .env.example .env    # preencha LLM_API_KEY
.venv/Scripts/python.exe -m src.generator "prazo para analisar pedido de acesso"
```

Sem chave, `--dry-run` imprime o prompt montado sem chamar a API.

**Qualquer provedor compatível com a API da OpenAI.** Groq, Gemini, DeepSeek e OpenRouter
expõem a mesma interface de chat completions, então trocar de provedor é mudar `LLM_BASE_URL`
e `LLM_MODEL` — não mexer no código. A escolha aqui é por preço, e preço de LLM muda mais
rápido que código.

#### A verificação de citação não é opcional

O princípio do projeto é que a IA nunca invente número de artigo. O prompt instrui isso, mas
instrução reduz o erro e não o elimina — e esse erro é especialmente danoso aqui, porque a
resposta *parece* verificável justamente por citar artigo.

Então, depois da geração, o código extrai toda citação `Art. N` da resposta e confere contra
os artigos efetivamente recuperados. O que não bater vira aviso explícito em `Resposta.avisos`,
para a interface mostrar. É determinístico e independe do modelo — inclusive de um modelo
barato e fraco, que é justamente o caso de uso.

Três avisos possíveis: `CITACAO_NAO_RECUPERADA` (citou artigo que não veio nos trechos),
`SEM_CITACAO` (respondeu sem citar nada) e `RESSALVA` (o artigo citado tem efeito suspenso —
hoje só o Art. 323, pelo Despacho ANEEL 2.006/2024).

Quando o retriever não devolve trecho nenhum, a resposta é "não encontrei" direto, sem gastar
chamada de API.

#### Dois achados que definem o Bloco 4 e o 5

**A faixa de similaridade é estreita demais para servir de filtro.** Medido no índice pronto:

| Pergunta | Score do top-1 |
|---|---|
| "Qual o prazo de análise do pedido de acesso?" | 0,878 |
| "Qual o preço de um painel solar fotovoltaico?" (fora do escopo) | 0,844 |
| "Qual a receita de bolo de cenoura?" | 0,824 |
| `asdfgh qwerty zxcvb` | 0,809 |

Sete centésimos separam uma pergunta legítima de teclado aleatório. **Não dá para implementar
"não encontrei" com um limiar de score** — isso terá que ser responsabilidade do prompt do
gerador (Bloco 5), que decide a partir do conteúdo dos trechos, não da nota da busca.

**As definições do Art. 2 são mal recuperadas.** "Diferença entre micro e minigeração em
potência" traz o alvo em rank 25; "geração compartilhada" em rank 41 — ambas fora do top-5, e
ambas são perguntas da bateria de aceitação. **Continua em aberto** (ver abaixo).

#### Uma hipótese testada e descartada

A suspeita era o empacotamento: cada chunk do Art. 2 junta ~4 definições sem relação entre si,
e o vetor viraria a média delas. A definição isolada de fato pontua +0,010 e +0,037 acima do
chunk empacotado.

Só que isso não se traduziu em ranking. Refazendo os chunks com fragmento menor
(`--fragment-chars`) e remedindo o rank do alvo:

| Pergunta | 1.200 (atual) | 400 | 250 |
|---|---|---|---|
| micro × minigeração em potência | 25 | 102 | 53 |
| geração compartilhada | 41 | 11 | 33 |
| validade dos créditos | **1** | 1 | 1 |
| prazo de análise do acesso | **3** | 11 | 11 |

Fragmentar melhora o score do alvo, mas melhora também o de centenas de concorrentes, e o
efeito líquido foi negativo. O padrão continua sendo fragmento = `--max-chars`; a flag ficou
como ferramenta de inspeção.

O que resta tentar no Bloco 7 é busca híbrida (BM25 + densa): a pergunta contém literalmente
"microgeração" e "minigeração", e casamento léxico resolveria o que a similaridade semântica
não resolve. Custa uma dependência nova, então fica para decidir.

---

## O problema central: nem todo texto da norma está em vigor

O texto compilado da ANEEL **mantém visível o conteúdo de dispositivos já revogados**, marcado
com `(Revogado pela REN ANEEL X)` — 66 ocorrências neste PDF. Exemplo real, do art. 655:

```
I - a partir de 1º de julho de 2019: 2.500 kW; (Revogado pela REN ANEEL 1.059, de 07.02.2023)
```

Indexado sem distinção, o RAG recupera esse trecho e responde com **artigo correto e conteúdo
que não vale mais** — falha que nenhum ajuste de prompt corrige, porque está na camada de dados.

### O caso pior: a redação anterior, que não tem marcador nenhum

Quando uma resolução dá **nova redação** a um dispositivo, o texto compilado mostra as duas
versões em sequência — e só a nova recebe marca. A antiga fica ali, indistinguível de texto
vigente:

```
Art. 96. No caso de conexão de outra distribuidora [...] a distribuidora é
         responsável por realizar o projeto [...]                              ← superada
Art. 96. No caso de conexão de outra distribuidora [...] que não utilize o
         processo simplificado da CCEE [...] (Redação dada pela REN ANEEL
         1.110, de 10.12.2024)                                                 ← vigente
```

São **17 artigos e 87 chunks** nessa situação. É mais perigoso que o caso do revogado
justamente por ser silencioso: não há nada no trecho antigo que denuncie o erro.

A detecção é posicional e delimitada por hierarquia — o alcance de um dispositivo termina
quando começa um irmão ou algo de nível superior. Contar rótulos ao longo do documento daria
falso positivo, porque alíneas `a)` e `b)` se repetem legitimamente sob incisos diferentes (só
no Art. 2 há uma dúzia de `a)` sem relação entre si). E as duas versões nem sempre são
adjacentes: no Art. 144 a redação antiga vem acompanhada dos próprios incisos antes de a nova
começar, e esses incisos também estão superados.

### Como isso vira metadado

Cada chunk carrega `situacao`: `vigente`, `revogado` ou `redacao_anterior` — e **nunca mistura
as três no mesmo chunk**, senão a flag seria inútil. O `extract_text.py` preserva os trechos e
as notas de alteração de propósito, para ser transcrição fiel e auditável; a separação acontece
aqui, e a filtragem no retriever (Bloco 4).

O `--report` avisa quando encontra um artigo duplicado cuja redação anterior não foi detectada
— foi essa guarda que revelou o formato do Art. 144.

Dois avisos do preâmbulo da norma que também precisam chegar ao usuário final (Bloco 5):
o Despacho 2.006/2024 **suspendeu por decisão judicial** o prazo de 60 ciclos do inciso II do
art. 323, e a MP 1.300/2025 alterou a aplicação da tarifa social.

---

## Progresso

| # | Bloco | Status |
|---|---|---|
| 1 | Extração e limpeza do PDF → `data/ren1000_raw.txt` | **concluído** — 679 artigos, sem buracos |
| 2 | Chunking por dispositivo → `index/chunks.json` (+ metadado de vigência) | **concluído** — 1.188 chunks, 0 blocos perdidos |
| 3 | Embeddings + índice FAISS | **concluído** — e5-small, 1.188 vetores, 1 truncado |
| 4 | Retriever (query → top-k) | **concluído** — filtra por `situacao`, sem limiar de score |
| 5 | Generator (prompt restrito + LLM) | **concluído** — falta validar com API real |
| 6 | Interface Gradio | a fazer |
| 7 | Bateria de 10 perguntas de teste | a fazer |
| 8 | README final | a fazer |
| 9 | Deploy no Hugging Face Spaces | a fazer |

Ideias fora do escopo da v1 ficam em [V2.md](V2.md).

## Licença

O código está sob [MIT](LICENSE). O texto da REN 1.000/2021 em `data/` e `index/` é ato
normativo oficial da ANEEL, de domínio público nos termos do art. 8º da Lei 9.610/1998 — não
é coberto pela licença deste repositório, e a fonte autoritativa continua sendo a publicação
oficial da agência.

## Fonte

[Resolução Normativa ANEEL nº 1.000, de 7 de dezembro de 2021](https://www2.aneel.gov.br/cedoc/ren20211000.html)
· [REN nº 1.059, de 7 de fevereiro de 2023](https://www2.aneel.gov.br/cedoc/ren20231059.html)

# Busca semântica na REN ANEEL 1.000/2021

### ▶ Demo no ar: **[ren1000-rag.fly.dev](https://ren1000-rag.fly.dev/)**

Pergunte em português sobre a norma que rege a distribuição de energia elétrica no Brasil —
incluindo micro e minigeração distribuída — e receba uma resposta curta **citando o artigo**,
com o trecho original da norma ao lado para conferência.

> **Projeto concluído**, dos 9 blocos planejados ao deploy público. Passa na bateria de
> aceitação com **8/10 e zero citações inventadas** ([relatório](docs/AVALIACAO.md)).
>
> A máquina dorme quando ninguém está usando, então a primeira pergunta pode levar alguns
> segundos a mais. Se a cota diária do LLM acabar, o app avisa e continua funcionando como
> busca — a recuperação não depende de API paga.

```
Pergunta:  Por quanto tempo valem os créditos de energia?

Resposta:  Os créditos de energia expiram em 60 meses após a data do
           faturamento em que foram gerados, Art. 655-L.

Fonte:     Art. 655-L · similaridade semântica 0.881
           Título II - PARTE ESPECIAL › Capítulo XI - DA MICROGERAÇÃO E
           MINIGERAÇÃO DISTRIBUÍDA E DO SISTEMA DE COMPENSAÇÃO DE ENERGIA
           ELÉTRICA (SCEE) › Seção I - Da conexão de microgeração e
           minigeração distribuída
           Alterado por: REN ANEEL 1.059/2023

           > Art. 655-L. Os créditos de energia expiram em 60 meses após a
           > data do faturamento em que foram gerados. (Incluído pela REN
           > ANEEL 1.059, de 07.02.2023)
```

## ⚠️ Disclaimer

Esta é uma **ferramenta de busca e apoio à leitura**, não aconselhamento jurídico, regulatório
ou técnico, e não substitui a leitura da norma oficial publicada pela ANEEL. Respostas podem
conter erros de recuperação ou de interpretação. Para qualquer decisão com efeito real,
consulte o texto oficial e um profissional habilitado.

---

## O problema que este projeto resolve

Fazer RAG sobre uma norma jurídica não é o mesmo que fazer RAG sobre documentação. **Nem todo
texto de uma norma está em vigor**, e o texto compilado da ANEEL mantém o conteúdo revogado
visível — 66 dispositivos marcados com `(Revogado pela REN ANEEL X)`.

Pior: quando uma resolução dá **nova redação** a um artigo, o compilado mostra as duas versões
em sequência e **só a nova recebe marca**. A antiga fica ali, indistinguível de texto vigente.
São 17 artigos e 87 chunks nessa situação.

Isso não é teórico. Buscando sobre projeto e montagem do sistema de medição:

```
1. Art. 96 · ⚠️ REDAÇÃO ANTERIOR · similaridade 0.920
```

A redação **superada** é o melhor casamento semântico do corpus inteiro. Sem tratamento, o
sistema responderia com artigo correto e texto revogado, com a maior confiança possível — e
nenhum ajuste de prompt corrigiria isso, porque o defeito está na camada de dados.

Por isso cada chunk carrega `situacao` (`vigente`, `revogado`, `redacao_anterior`), nunca
mistura as três, e o filtro mora no retriever: **o que não chega ao contexto não pode ser
citado por engano.**

## Como o sistema evita inventar

O princípio é que a IA nunca cite artigo que não veio dos trechos recuperados. O prompt instrui
isso, mas instrução reduz o erro sem eliminá-lo — e esse erro é especialmente danoso aqui,
porque a resposta *parece* verificável justamente por citar artigo.

Então, depois da geração, o código extrai toda citação `Art. N` e **confere contra os artigos
efetivamente recuperados**. O que não bater vira aviso na interface. É determinístico e
independe do modelo, inclusive de um modelo barato.

Na bateria de 10 perguntas: **zero citações inventadas**, incluindo nas 4 perguntas em que a
recuperação falhou — nelas o sistema disse que não encontrou, em vez de preencher a lacuna.

---

## Arquitetura

Build-time (`scripts/`, roda uma vez, offline) e runtime (`src/` + `app.py`, roda a cada
pergunta) são separados de propósito: o índice é pré-computado e versionado, para o app nunca
recalcular embeddings a cada requisição.

```
PDF do texto compilado (CEDOC/ANEEL)
   └─ scripts/extract_text.py  →  data/ren1000_raw.txt     679 artigos, sem buracos
   └─ scripts/chunk_text.py    →  index/chunks.json        1.188 chunks + vigência
   └─ scripts/build_index.py   →  index/ren1000.faiss      1.188 × 384 dims

pergunta
   └─ src/glossario.py    ponte de vocabulário (leigo → norma)
   └─ src/retriever.py    híbrida: FAISS + BM25 fundidos por RRF, filtrado por vigência
   └─ src/generator.py    LLM sobre os trechos + verificação de citação
   └─ app.py              resposta + trechos-fonte
```

A busca é **híbrida** porque as duas metades falham por motivos opostos: a semântica perde o
termo técnico exato quando ele concorre com dezenas de artigos do mesmo tema, e a léxica não
acha o que foi perguntado com outras palavras. Fundir os dois rankings por Reciprocal Rank
Fusion levou a recuperação de 6/7 para **7/7**, sem piorar nenhuma pergunta.

**Runtime não carrega `torch`.** Como o índice é pré-computado, em produção o sistema vetoriza
uma pergunta por vez — e para isso o ONNX Runtime basta. Medido: **582 MB** de RSS para o app
inteiro, contra ~950 MB com `torch`, e ~740 MB a menos em disco. A variante quantizada foi
validada contra a bateria completa e dá **ranking idêntico**, artigo por artigo.

**Stack — runtime:** Python 3.11 · `onnxruntime` + `tokenizers` com o ONNX oficial do
`intfloat/multilingual-e5-small` · `faiss-cpu` · `rank-bm25` · `gradio` · qualquer LLM com API
compatível com a da OpenAI.

**Stack — build (roda uma vez, offline):** `pdfplumber` · `sentence-transformers`.

O corpus é uma norma única e estática, então FAISS local basta — não há motivo para banco
vetorial gerenciado.

---

## Como rodar

**Python 3.11 é obrigatório.** `torch` e `faiss-cpu` ainda não publicam wheel para 3.14, que é o
interpretador padrão em algumas máquinas.

```bash
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

Isso instala só o que o app precisa para responder. Para **construir o índice** você também
precisa das dependências de build, que trazem `torch` e ficam de fora do deploy:

```bash
.venv/Scripts/python.exe -m pip install -r requirements-build.txt
```

Se você só quer rodar o app, o índice já vem versionado em `index/` — pule para o passo 3.

### 1. Obter o texto da norma

Baixe o **texto compilado** da REN 1.000/2021 no
[CEDOC da ANEEL](https://www2.aneel.gov.br/cedoc/ren20211000.html) e salve como
`data/ren1000.pdf`. O PDF não é versionado; o texto extraído é.

Use o compilado, não o PDF original de 2021: as regras de micro e minigeração distribuída e do
SCEE foram alteradas pela REN 1.059/2023 e seguintes.

### 2. Construir o índice

```bash
.venv/Scripts/python.exe scripts/extract_text.py --input data/ren1000.pdf --report   # confira
.venv/Scripts/python.exe scripts/extract_text.py --input data/ren1000.pdf
.venv/Scripts/python.exe scripts/chunk_text.py
.venv/Scripts/python.exe scripts/build_index.py
```

Todos aceitam `--report`, que só mede e imprime, sem escrever nada. O relatório do
`extract_text.py` inclui o principal teste de sanidade: **buracos na numeração dos artigos**,
que indicariam conteúdo perdido na extração.

Esperado: 152 páginas, 679 artigos sem buracos, 1.188 chunks, índice de 1,7 MB. A geração dos
embeddings leva ~3,5 min em CPU; o resto, menos de um minuto.

### 3. Configurar o LLM

```bash
cp .env.example .env
```

Preencha `LLM_API_KEY`. Groq, Gemini, DeepSeek e OpenRouter expõem a mesma interface de chat
completions, então trocar de provedor é mudar `LLM_BASE_URL` e `LLM_MODEL` — não mexer no
código. A escolha aqui é por preço, e preço de LLM muda mais rápido que código.

**Sem chave o app não quebra:** degrada para busca pura, exibindo os trechos recuperados sem a
resposta redigida. A recuperação não depende de API paga.

### 4. Usar

```bash
.venv/Scripts/python.exe app.py                                    # interface em :7860
.venv/Scripts/python.exe -m src.retriever "validade dos créditos"  # só a busca
.venv/Scripts/python.exe -m src.generator "..." --dry-run          # o prompt, sem gastar cota
```

## Avaliação

```bash
.venv/Scripts/python.exe scripts/avaliar.py --so-busca             # sem LLM, sem custo
.venv/Scripts/python.exe scripts/avaliar.py --output docs/AVALIACAO.md
```

Bateria de 10 perguntas com gabarito verificado dispositivo por dispositivo
([tests/perguntas_aceitacao.py](tests/perguntas_aceitacao.py)), separando duas métricas:
**recuperação** (o artigo certo está entre os `k` trechos?) e **aceitação** (a resposta cita o
artigo certo, ou recusa quando deve?).

**Recuperação: 7/7. Aceitação: 8/10. Citações inventadas: 0.** Medido com o sistema completo,
busca híbrida inclusive ([relatório](docs/AVALIACAO.md)).

As duas falhas que restam não são invenção, e vale distinguir:

- **Pergunta 1** — o `Art. 64` é recuperado em quinto, mas o modelo prefere recusar a arriscar.
  Conta como falha; é o tipo seguro dela. Antes da busca híbrida esta pergunta produzia algo
  pior: citava o `Art. 90`, que trata do caso especial da Lei 14.195 (45 dias) em vez da regra
  geral (15 e 30 dias) — resposta errada com citação válida.
- **Pergunta 10** — `"e a conta?"` deveria ser recusada por ser vaga demais para se saber o que
  foi perguntado. O sistema responde a definição de fatura do `Art. 2`: correta e corretamente
  citada, mas presumindo a intenção. É falha de produto, não de veracidade.

O placar ficou igual ao anterior à busca híbrida, mas o sistema é mais seguro: uma resposta
confiantemente errada virou resposta certa, e uma citação errada virou recusa.

## Testes

```bash
.venv/Scripts/python.exe tests/test_extract_text.py
.venv/Scripts/python.exe tests/test_chunk_text.py
.venv/Scripts/python.exe tests/test_build_index.py
.venv/Scripts/python.exe tests/test_embedder.py
.venv/Scripts/python.exe tests/test_retriever.py
.venv/Scripts/python.exe tests/test_generator.py
.venv/Scripts/python.exe tests/test_glossario.py
.venv/Scripts/python.exe tests/test_app.py
```

Nenhum baixa o modelo de embedding nem chama a API do LLM: os testes de índice e busca usam
vetores conhecidos e o do gerador usa um dublê de cliente. Cobrem a lógica que erra em
silêncio — filtro de vigência, ordenação, sincronia entre índice e chunks, verificação de
citação e as duas formas de degradação do app.

O comportamento do modelo real não é testável assim; para isso existe a bateria de aceitação.

---

## Decisões técnicas

O registro completo do que foi medido, decidido e **descartado** está em
[docs/DECISOES_TECNICAS.md](docs/DECISOES_TECNICAS.md). Alguns dos casos:

- **Por que pdfplumber e não pypdf** — o pypdf insere espaços dentro das palavras neste PDF;
  `identificação` não aparecia inteira uma vez sequer em 679 artigos. ~120 linhas de regex de
  reparo foram apagadas ao trocar de biblioteca.
- **Por que não existe limiar de score** — sete centésimos separam o top-1 de uma pergunta
  legítima (0,878) do de teclado aleatório (0,809).
- **Uma hipótese bem medida e mesmo assim errada** — fragmentar os chunks das definições
  melhorava o score do alvo, mas piorava o ranking. Medir depois de implementar é o que revelou.
- **A norma não fala a língua de quem pergunta** — `pedido de acesso` tem **zero** ocorrências
  no corpus; a norma chama de `orçamento de conexão`. Nem busca vetorial nem BM25 resolvem isso.
- **Afrouxar a recusa custou a recusa** — o ajuste de prompt que consertou uma pergunta quebrou
  outra, e só apareceu porque havia régua.
- **Busca híbrida entrou por medição, não por gosto** — foi a terceira tentativa de consertar o
  ranking do Art. 2, depois de duas hipóteses refutadas. Entrou porque levou a recuperação a
  7/7 **sem piorar nenhuma pergunta**.
- **ONNX quantizado no runtime, fp32 descartado** — a fp32 economizava 57 MB e tinha pico
  *pior* que o `torch`; só a int8 valia (846 → 456 MB). E uma medição que quase virou conclusão
  errada: o primeiro teste indicava degradação, mas o defeito estava no próprio teste, que
  prefixava a pergunta duas vezes.

## Progresso

| # | Bloco | Status |
|---|---|---|
| 1 | Extração e limpeza do PDF | **concluído** — 679 artigos, sem buracos |
| 2 | Chunking por dispositivo + vigência | **concluído** — 1.188 chunks, 0 blocos perdidos |
| 3 | Embeddings + índice FAISS | **concluído** — e5-small, 1 chunk truncado |
| 4 | Retriever | **concluído** — filtra por vigência, sem limiar de score |
| 5 | Generator | **concluído** — verificação determinística de citação |
| 6 | Interface Gradio | **concluído** — degrada para busca sem chave |
| 7 | Bateria de aceitação | **concluído** — 8/10, 0 alucinações |
| 8 | README | **concluído** |
| 9 | Deploy | **concluído** — [ren1000-rag.fly.dev](https://ren1000-rag.fly.dev/), região `gru` |

### Publicar

Rodando no Fly.io em São Paulo (`gru`), imagem de 252 MB comprimida.

```bash
cd ren1000-rag                   # os comandos leem fly.toml e Dockerfile do diretório atual
flyctl launch --no-deploy --copy-config --name SEU-APP --region gru
flyctl secrets set LLM_API_KEY=... LLM_BASE_URL=... LLM_MODEL=...
flyctl deploy
```

Três tropeços que custaram tempo, caso você reproduza: no Windows o binário chama-se `flyctl`,
não `fly`; rodar de outro diretório faz o `flyctl` gerar um `fly.toml` no lugar errado, com a
porta padrão 8080 em vez da 7860 deste app; e `secrets set` exige que o app já exista, mas
reporta a ausência dele como se faltasse o campo `app` no arquivo.

O índice vai versionado e o modelo ONNX é **embutido na imagem durante o build** — nenhuma
máquina nova baixa nada ao acordar, e o app não depende do Hub estar no ar em produção.

O build faz duas verificações que falham cedo em vez de em produção: vetoriza uma frase de
teste (se o pipeline de pooling estiver errado, o build quebra) e confere que o índice FAISS e
o `chunks.json` têm o mesmo tamanho.

**Memória: 568 MiB medidos em container com limite de 1 GB** (55%). Cabe folgado em 1 GB;
**não cabe** em tier de 512 MB. Vale para qualquer hospedagem, não só o Fly.

O `fly.toml` deixa a máquina dormir quando ninguém usa (`auto_stop_machines`), o que numa demo
de portfólio é a diferença entre pagar pelo uso e pagar pelo tempo. O custo é um cold start de
alguns segundos.

Para construir a imagem localmente:

```bash
docker build --secret id=hf_token,env=HF_TOKEN -t ren1000-rag .
docker run --rm -p 7860:7860 --env-file .env ren1000-rag
```

O `HF_TOKEN` é opcional — o repositório do modelo é público, e ele só evita o limite de taxa do
download anônimo. Vai por **secret mount**, nunca por `ARG`: um `ARG` fica gravado em texto
plano no histórico da imagem e qualquer pessoa com ela lê o segredo.

**Sobre a cota:** cada pergunta consome ~2,5 mil tokens e o free tier da Groq dá 100 mil por
dia, ou seja, algumas dezenas de perguntas diárias. Ao esgotar, o app avisa em português e
continua funcionando como busca, em vez de quebrar.

Ideias fora do escopo da v1 ficam em [V2.md](V2.md).

## Licença

O código está sob [MIT](LICENSE). O texto da REN 1.000/2021 em `data/` e `index/` é ato
normativo oficial da ANEEL, de domínio público nos termos do art. 8º da Lei 9.610/1998 — não é
coberto pela licença deste repositório, e a fonte autoritativa continua sendo a publicação
oficial da agência.

## Fonte

[REN nº 1.000, de 7 de dezembro de 2021](https://www2.aneel.gov.br/cedoc/ren20211000.html) ·
[REN nº 1.059, de 7 de fevereiro de 2023](https://www2.aneel.gov.br/cedoc/ren20231059.html)

Corpus com as alterações até a REN 1.110/2024.

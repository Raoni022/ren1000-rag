# Decisões técnicas

Registro do que foi medido, do que foi decidido e do que foi descartado. Existe separado do
README porque quem chega ao projeto precisa entender o que ele faz em dois minutos, e quem vai
auditar ou reaproveitar precisa de tudo isto.

Um padrão se repete abaixo e é o mais útil de levar embora: **quase toda decisão boa deste
projeto veio de uma medição que contrariou uma hipótese plausível.**

---

## 1. Extração: por que pdfplumber e não pypdf

Foi a decisão que mais afetou a qualidade do texto, e a lição não é específica deste projeto:
**a qualidade da extração se decide na escolha da biblioteca, não no pós-processamento.**

| | pypdf `plain` | pypdf `layout` | pdfplumber |
|---|---|---|---|
| Artigos reconhecíveis (de 679) | 30 | 679 | **679** |
| Quebras após ligadura `ﬁ`/`ﬂ` | — | 570 | **0** |
| Letras soltas no meio de palavra | — | 39 | **0** |
| `identificação` inteira no documento | — | 0× | **49×** |
| Palavras coladas | sim | não | não |
| Tempo | 36 s | 36 s | 62 s |

No modo `plain` cada página vem como uma única linha de ~5.700 caracteres, sem quebra, colando
palavras vizinhas (`consumidoracom microgeração`). No modo `layout` as quebras saem certas, mas
ele insere espaços **dentro** das palavras: `identific ação`, `f aturamento`, `fie l cumprimento`.
`identificação` e `verificação` não apareciam inteiras uma vez sequer.

Chegaram a existir ~120 linhas de regex para remontar essas palavras. Funcionavam para a
ligadura (589 remontagens corretas) e **não** para a letra solta, que é irrecuperável a partir
do texto já extraído:

- o fragmento pode pertencer à palavra da esquerda ou à da direita — `fie l cumprimento` é
  *"garantia de fiel cumprimento"*, não *"fie lcumprimento"*;
- o tamanho do vão não distingue quebra interna de fronteira legítima: `fie    l` tem 4 espaços,
  `fiel      cumprimento` tem 6;
- juntar maiúscula quebraria incisos romanos e subgrupos tarifários reais (`V do`, `B deve`).

O pdfplumber reconstrói a palavra pela posição dos glifos e zera os dois defeitos, o que
permitiu apagar todo esse código. O minuto a mais é irrelevante num script que roda uma vez.

Ficou de guarda a função `fragmentos_orfaos()`: se a contagem de palavras partidas voltar a
subir, a extração regrediu.

### Salvaguarda no detector de cabeçalho

Cabeçalho e rodapé são detectados, não hardcodados: linhas que se repetem no topo ou na base de
mais de metade das páginas. A comparação mascara dígitos, para `Página 3 de 152` e `Página 4 de
152` casarem.

Isso quase apagou artigos. Duas linhas de conteúdo que diferem só por números colidem na mesma
chave depois do mascaramento. A salvaguarda é que **linha que inicia estrutura da norma nunca é
candidata a boilerplate** — perder um artigo em silêncio é muito pior que deixar passar um
cabeçalho.

---

## 2. Chunking: nem o artigo, nem o dispositivo isolado

Medido sobre 717 artigos:

- **por dispositivo isolado:** mediana de 146 caracteres. `II - permitir a leitura` não
  significa nada fora do caput que o rege, e recuperado sozinho leva o modelo a responder sem
  saber do que se trata;
- **por artigo inteiro:** mediana de 523, mas 52% passam de 500 caracteres e o Art. 2
  (definições) tem 20.122 — um vetor único para 20 mil caracteres não é recuperável por
  pergunta específica.

A unidade adotada é o **dispositivo com seus subordinados**: o caput com os incisos que dependem
dele, cada parágrafo com os seus, empacotados até `--max-chars` (1.200). Quando uma unidade
sozinha estoura o teto, ela é fatiada **repetindo o caput** em cada pedaço — nenhum inciso vai
para o índice sem o texto que lhe dá sentido.

Resultado: 1.188 chunks, mediana de 524 caracteres, p99 de 1.194, **0 blocos de conteúdo
perdidos** (verificado bloco a bloco contra a entrada).

Cada chunk tem dois campos de texto, de propósito:

- `texto` — o trecho literal, para o usuário conferir;
- `texto_busca` — o mesmo trecho precedido da trilha estrutural e do caput do artigo, e é o que
  é vetorizado. Um `§ 2º O prazo é de 30 dias` só é recuperável por "prazo de análise" se o
  vetor souber de que artigo e capítulo ele veio.

---

## 3. Vigência: o problema central do corpus

O texto compilado da ANEEL mantém visível o conteúdo já revogado, marcado com
`(Revogado pela REN ANEEL X)` — 66 ocorrências. Indexado sem distinção, o sistema responde com
**artigo correto e conteúdo que não vale mais**: falha que nenhum ajuste de prompt corrige,
porque está na camada de dados.

### O caso pior: a redação anterior, que não tem marcador nenhum

Quando uma resolução dá **nova redação** a um dispositivo, o compilado mostra as duas versões em
sequência — e só a nova recebe marca:

```
Art. 96. No caso de conexão de outra distribuidora [...] a distribuidora é
         responsável por realizar o projeto [...]                              ← superada
Art. 96. No caso de conexão de outra distribuidora [...] que não utilize o
         processo simplificado da CCEE [...] (Redação dada pela REN ANEEL
         1.110, de 10.12.2024)                                                 ← vigente
```

São **17 artigos e 87 chunks**. É mais perigoso que o revogado por ser silencioso: nada no
trecho antigo denuncia o erro.

A detecção é posicional e delimitada por hierarquia — o alcance de um dispositivo termina quando
começa um irmão ou algo de nível superior. Contar rótulos ao longo do documento daria falso
positivo, porque alíneas `a)` e `b)` se repetem legitimamente sob incisos diferentes (só no
Art. 2 há uma dúzia de `a)` sem relação entre si). E as duas versões nem sempre são adjacentes:
no Art. 144 a redação antiga vem com os próprios incisos antes de a nova começar, e esses
incisos também estão superados — caso que a primeira regra, baseada em adjacência, não pegava.

Quem revelou isso foi a guarda que avisa sobre artigo duplicado sem redação anterior detectada.
Ela ficou no `--report`.

### Por que isso não é teórico

Buscando "conexão de outra distribuidora, projeto e montagem do sistema de medição" com o filtro
desligado:

```
1. Art. 96 · ⚠️ REDAÇÃO ANTERIOR · similaridade 0.920
```

A redação **superada** é o melhor casamento semântico do corpus inteiro — o score mais alto
medido no projeto. Com o filtro padrão ela nunca é recuperada. Sem o metadado de vigência, o
sistema responderia com texto revogado, com a maior confiança possível.

O filtro mora no retriever, não no prompt: o que não chega ao contexto não pode ser citado por
engano, e vigência é metadado determinístico, não julgamento de LLM.

---

## 4. Embeddings e índice

**Modelo: `intfloat/multilingual-e5-small`.** O `paraphrase-multilingual-MiniLM-L12-v2` do plano
original foi descartado por medição: janela de 128 tokens contra chunks de até 1.200 caracteres.
Com o e5-small (512 tokens), a medição real com o tokenizador do modelo dá mediana de 182
tokens, p99 de 427 e **1 chunk truncado** em 1.188.

Dois detalhes que não geram erro quando errados, só degradam a busca em silêncio — por isso
ficam em `src/config.py`, lido pelo build e pela busca:

- **Os prefixos do E5 não são opcionais.** Documentos entram como `passage: `, perguntas como
  `query: `. Omitir não quebra nada, só piora a recuperação.
- **`IndexFlatIP` sobre vetores normalizados em L2.** Com norma 1, o produto interno é idêntico
  ao cosseno, métrica de treino do E5. `IndexFlatL2` daria ordenação diferente e pior. O script
  aborta se a normalização não bater.

`Flat` (força bruta) porque 1.188 vetores de 384 dimensões ocupam ~1,8 MB e a busca exata leva
menos de um milissegundo. IVF ou HNSW só compensam em corpus ordens de grandeza maiores, e
custariam recall.

A carga confere que índice e `chunks.json` têm o mesmo tamanho. Vindos de execuções diferentes,
a posição no índice deixa de apontar para o artigo certo e a busca devolve **o artigo errado
para o vetor certo**, sem erro nenhum.

---

## 5. Por que não existe limiar de score

Medido no índice pronto:

| Pergunta | Score do top-1 |
|---|---|
| "Qual o prazo de análise do pedido de acesso?" | 0,878 |
| "Qual o preço de um painel solar fotovoltaico?" (fora do escopo) | 0,844 |
| "Qual a receita de bolo de cenoura?" | 0,824 |
| `asdfgh qwerty zxcvb` | 0,809 |

**Sete centésimos** separam uma pergunta legítima de teclado aleatório. Qualquer corte nessa
faixa ou deixa passar pergunta fora de escopo, ou descarta pergunta válida.

Por isso o retriever nunca decide se a pergunta tem resposta: devolve sempre os `k` mais
próximos com o score, e dizer "não encontrei" é do gerador, que julga pelo **conteúdo** dos
trechos, não pela nota da busca.

---

## 6. Uma hipótese testada e descartada

As definições do Art. 2 vinham mal ranqueadas. A suspeita era o empacotamento: cada chunk junta
~4 definições sem relação entre si, e o vetor viraria a média delas. A definição isolada de fato
pontua +0,010 e +0,037 acima do chunk empacotado.

Só que isso não se traduziu em ranking. Refazendo os chunks com fragmento menor
(`--fragment-chars`) e remedindo o rank do alvo:

| Pergunta | 1.200 (padrão) | 400 | 250 |
|---|---|---|---|
| micro × minigeração em potência | 25 | 102 | 53 |
| geração compartilhada | 41 | 11 | 33 |
| validade dos créditos | **1** | 1 | 1 |
| prazo de análise do acesso | **3** | 11 | 11 |

Fragmentar melhora o score do alvo e melhora também o de centenas de concorrentes: efeito
líquido negativo. O padrão continua sendo fragmento = `--max-chars`, e a flag ficou como
ferramenta de inspeção.

**A hipótese estava bem fundamentada e medida — e mesmo assim errada.** É o motivo de existir
`scripts/avaliar.py`.

---

## 7. O achado que reorganizou o projeto: a norma não fala a língua de quem pergunta

Contagem no corpus vigente:

| Como se pergunta | ocorrências | Como a norma escreve | ocorrências |
|---|---|---|---|
| `pedido de acesso` | **0** | `orçamento de conexão` | 82 |
| `conta de luz` | **0** | `fatura` | 582 |
| `corte de energia` | **0** | `suspensão do fornecimento` | 28 |
| `troca de titularidade` | **0** | `alteração de titularidade` | 25 |
| `placa solar` | **0** | `microgeração distribuída` | 18 |

O caso do "pedido de acesso" é o mais instrutivo: esse vocabulário vem da REN 482/2012 e do
PRODIST, revogados pela REN 1.059/2023. Quem aprendeu a profissão antes de 2023 pergunta assim —
e a resposta existe, no Art. 64, sob outro nome.

**Busca vetorial não resolve sozinha**, porque os termos não são sinônimos linguísticos e sim uma
troca de nomenclatura por decisão regulatória. **Busca léxica (BM25) também não**, pelo motivo
oposto: não se acha por casamento de termo o que não está escrito.

A solução foi `src/glossario.py`: tabela curta e auditável que **acrescenta** o termo da norma à
pergunta, sem substituir — preservando o resto do que foi perguntado. Cada entrada tem evidência
medida, e o casamento usa limite de palavra porque "gato" casaria dentro de "obri**gato**rio"
(8 falsos positivos no corpus).

Foi descartada a opção de reescrever as perguntas da bateria no vocabulário da norma: faria a
métrica subir sem o produto melhorar, e o público-alvo continuaria sem resposta.

---

## 8. Busca híbrida: a única mudança que entrou por já ter régua

As definições do Art. 2 continuavam fora do top-8 depois do glossário — e a consequência não
era o sistema calar, era ele **responder errado com citação válida**:

> *Art. 655-C. A minigeração distribuída tem potência instalada superior a 500 kW.*

Os 500 kW do Art. 655-C são o gatilho da garantia de fiel cumprimento, não a fronteira entre
micro e minigeração (75 kW). A citação existia e tinha sido recuperada, então o verificador
determinístico não tinha como pegar — é o pior defeito que este sistema pode ter.

A causa era a definição do Art. 2 nunca chegar ao contexto. Medido, com `k=8`:

| # | Pergunta | densa | híbrida |
|---|---|---|---|
| 1 | prazo de análise do acesso | pos 8 | **pos 5** |
| 2 | micro × minigeração em potência | **fora** | **pos 8** |
| 3 | validade dos créditos | pos 4 | **pos 1** |
| 4 | responsável técnico | pos 1 | pos 1 |
| 6 | documentos do acesso | pos 2 | pos 2 |
| 7 | prazo dos créditos | pos 2 | pos 2 |
| 8 | geração compartilhada | pos 6 | **pos 2** |
| | **recuperação** | **6/7** | **7/7** |

Nenhuma pergunta piorou. Por isso entrou — e só por isso: era a terceira tentativa de consertar
o Art. 2, depois de duas medições que refutaram hipóteses (fragmentar os chunks, seção 6; e o
próprio glossário, que resolveu 1 e 6 mas não 2).

**As duas buscas falham por motivos opostos e complementares.** A densa perde o termo técnico
exato quando ele concorre com dezenas de artigos sobre o mesmo tema; a léxica não acha o que foi
perguntado com outras palavras. O glossário cobre um terceiro caso, que nenhuma das duas cobre:
quando o termo perguntado não existe no corpus.

A fusão é **Reciprocal Rank Fusion**, não soma ponderada de scores. As duas escalas não são
comparáveis — a similaridade densa vive espremida entre 0,80 e 0,92 (seção 5), enquanto o BM25 é
ilimitado e depende da raridade dos termos. Normalizá-las exigiria calibração, e calibrar contra
a bateria de aceitação seria ajustar o sistema ao próprio gabarito. O RRF ignora magnitude e usa
só a ordem, que é o que as duas têm de comparável. O `k0 = 60` é o valor da publicação original
e não foi ajustado.

A tokenização léxica remove acento: quem digita "minigeracao" precisa casar com "minigeração", e
o BM25 compara token com token, sem a tolerância do modelo de embedding.

O score exibido continua sendo a similaridade semântica — é a única das duas escalas que
significa algo para quem lê. A posição na lista é que reflete a fusão.

---

## 9. Largar o torch em runtime: ONNX quantizado

O índice é pré-computado, então em produção o sistema vetoriza **uma pergunta por vez**.
Carregar `torch` inteiro para isso custa caro e não entrega nada em troca. Medido:

| | RSS de uma busca | pico | em disco |
|---|---|---|---|
| torch + sentence-transformers | 846 MB | 848 MB | ~790 MB |
| ONNX fp32 | 789 MB | **884 MB** | ~50 MB |
| ONNX int8 | **456 MB** | **456 MB** | ~50 MB |

A fp32 foi descartada por medição: economiza 57 MB de RSS e tem pico **pior** que o torch. A
int8 corta 46%. Com o Gradio junto, o app inteiro fica em **582 MB** (pico 617 MB) contra os
~950 MB do caminho anterior.

Em disco, o que sai são `torch` (494 MB), `transformers` (97 MB), `scipy`, `sympy` e `networkx`.
O que entra são `onnxruntime` (43 MB) e `tokenizers` (7 MB). Daí a separação entre
`requirements.txt` (runtime) e `requirements-build.txt` (construir o índice).

### Quantização é arriscada, e por isso foi medida no lugar certo

Trocar o codificador da pergunta por um que produz vetores diferentes dos que construíram o
índice degradaria a busca sem levantar erro. A verificação não foi o cosseno isolado, e sim a
bateria inteira:

| | recuperação | posições por pergunta |
|---|---|---|
| torch | 7/7 | `{1:5, 2:8, 3:1, 4:1, 6:2, 7:2, 8:2}` |
| ONNX fp32 | 7/7 | `{1:5, 2:8, 3:1, 4:1, 6:2, 7:2, 8:2}` |
| ONNX int8 | 7/7 | `{1:5, 2:8, 3:1, 4:1, 6:2, 7:2, 8:2}` |

Ranking idêntico artigo por artigo — inclusive na pergunta 2, cujo alvo está na posição 8, na
fronteira do corte, e seria a primeira a cair.

O ONNX vem do repositório **oficial** `intfloat/multilingual-e5-small`, não de conversão de
terceiros: com o modelo original fora do runtime, uma conversão de origem desconhecida poderia
divergir do que gerou o índice sem nada acusar.

O lado dos documentos continua sendo indexado em fp32, com `sentence-transformers`. Ali o custo
é pago uma vez, offline, e não há motivo para abrir mão de precisão.

### O erro que quase virou conclusão errada

A primeira medição indicou cosseno 0,9956 e recuperação caindo para 6/7 — o que teria matado a
migração. Era defeito do meu teste, em dois pontos: eu passava a pergunta **já prefixada** para
o `_vetorizar`, que prefixa de novo (`"query: query: ..."`), e no substituto do método eu tinha
removido o prefixo por completo do lado ONNX. Com os dois lados corretos, o cosseno é
`1,000000` e o ranking, idêntico.

Vale registrar porque o modo de falha é característico: os prefixos assimétricos do E5 não
levantam erro quando errados (seção 4), então um teste que os aplica errado produz um número
plausível e uma conclusão falsa.

---

## 10. A verificação de citação não é opcional

O princípio do projeto é que a IA nunca invente número de artigo. O prompt instrui isso, mas
instrução reduz o erro e não o elimina — e esse erro é especialmente danoso aqui, porque a
resposta *parece* verificável justamente por citar artigo.

Depois da geração, o código extrai toda citação `Art. N` e confere contra os artigos
efetivamente recuperados. O que não bater vira aviso explícito para a interface mostrar. É
determinístico e independe do modelo — inclusive de um modelo barato e fraco, que é o caso de
uso pretendido.

Três avisos: `CITACAO_NAO_RECUPERADA`, `SEM_CITACAO` e `RESSALVA` (artigo com efeito suspenso —
hoje só o Art. 323, pelo Despacho ANEEL 2.006/2024).

---

## 11. Como o resultado da bateria evoluiu

| Mudança | Recuperação | Aceitação |
|---|---|---|
| baseline (k=5) | 3/7 | 6/10 |
| + glossário | 4/7 | — |
| + `k=8` | 6/7 | 7/10 |
| + prompt ciente da diferença de vocabulário | 6/7 | 7/10 (quebrou a 10) |
| + recusa explícita para pergunta vaga | 6/7 | **8/10** |
| + busca híbrida (BM25 + RRF) | **7/7** | **8/10** |

O 8/10 foi medido três vezes ao todo, a última já com o sistema completo — não é resultado de
uma execução isolada. O placar não mudou com a busca híbrida, mas **o conjunto de falhas mudou,
e para melhor**:

| | antes da híbrida | depois |
|---|---|---|
| Pergunta 1 | citava o Art. 90 — regra errada, citação válida | recusa honestamente |
| Pergunta 2 | "minigeração tem potência superior a 500 kW" — **errado** | cita o Art. 2, correto |
| Pergunta 10 | recusava, como esperado | responde a definição de fatura do Art. 2 |

Duas falhas viraram comportamento seguro e uma passou a acertar; em troca, a 10 deixou de
recusar uma pergunta vaga. A resposta dela é correta e corretamente citada — o defeito é
presumir a intenção de `"e a conta?"`, o que é falha de produto, não de veracidade.

Trocar uma resposta confiantemente errada por uma correta, ao custo de responder uma pergunta
ambígua, é um bom negócio para este projeto. Fica registrado porque é o tipo de mudança que um
placar idêntico esconderia.

O `k=8` não é ajuste ao gabarito: o recall medido é 3/7 em k=3, 4/7 em k=5, 6/7 em k=8 e 7/7 só
em k=15. Oito é onde a curva achata, a ~1.200 tokens de contexto.

O quarto passo é o mais instrutivo: avisar o modelo sobre a diferença de vocabulário consertou a
pergunta 6 e **quebrou a 10** — ele passou a responder "e a conta?" citando um artigo qualquer
em vez de recusar. Afrouxar a recusa custou a recusa. O conserto foi separar os dois motivos
legítimos de recusar: nenhum trecho trata do assunto, **ou** a pergunta é vaga demais para se
saber o que foi perguntado.

### As duas falhas que restam

**Pergunta 1** — o `Art. 64` é recuperado em quinto, mas o modelo prefere recusar a arriscar.
Antes da híbrida ele citava o `Art. 90`, que trata do caso especial da Lei 14.195 (45 dias) em
vez da regra geral (15 e 30 dias): citação honesta, artigo existente, usuário mal informado. O
gabarito **não** foi ampliado para acomodar nenhuma das duas versões.

**Pergunta 10** — `"e a conta?"` deixou de ser recusada. O caminho para consertar é o mesmo já
usado uma vez: apertar a instrução de recusa por vagueza sem afrouxar o resto. Não foi feito
agora porque a evidência do quarto passo desta seção é que mexer nessa instrução tem efeito
colateral, e refazer a bateria custa ~25 mil tokens da cota diária.

A pergunta 2, que era a outra falha e produziu a resposta errada da seção 8, passou a acertar:
a definição do `Art. 2` entrou no top-8 e o modelo a citou corretamente.

---

## 12. Limite de cota do free tier

Cada pergunta consome ~2,5 mil tokens com `k=8`. O free tier da Groq dá **100 mil tokens por
dia** para o `llama-3.3-70b-versatile` — ou seja, **algumas dezenas de perguntas por dia** na
demo pública.

Ao estourar, o app avisa em português que a cota acabou e continua entregando os trechos da
norma, em vez de mostrar o erro cru. Sem chave nenhuma, ele degrada para busca pura: a
recuperação não depende de API paga.

O avaliador trata esse estouro por pergunta, não por execução: uma bateria interrompida no meio
sai como relatório **parcial**, com as perguntas já medidas preservadas e um aviso no cabeçalho.
Derrubar tudo perderia o trabalho já pago em tokens.

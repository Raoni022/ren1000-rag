# Imagem de runtime. NÃO instala torch: ver requirements.txt e src/embedder.py.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Escutar em 0.0.0.0 é obrigatório em container: no padrão 127.0.0.1 o Gradio sobe e
    # nada de fora alcança, o que aparece como health check falhando sem erro no log.
    GRADIO_SERVER_NAME=0.0.0.0 \
    PORT=7860 \
    # Cache do Hugging Face dentro da imagem, para o modelo ser baixado no build e não a
    # cada boot da máquina.
    HF_HOME=/app/.hf \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# libgomp1: onnxruntime e faiss-cpu dependem de OpenMP, que não vem na imagem slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Dependências antes do código: a camada é reaproveitada enquanto o requirements não mudar.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY index/ ./index/
COPY app.py ./

# Baixa o ONNX (113 MB) e o tokenizador para dentro da imagem. Sem isto, cada máquina nova
# do Fly baixaria os arquivos no primeiro acesso -- o que atrasa o cold start e deixa a
# aplicação dependente do Hub estar no ar e da cota de download anônimo.
#
# Vetoriza uma frase de propósito: se algo estiver errado no modelo ou no pipeline de
# pooling, o build falha aqui, e não em produção na primeira pergunta de um usuário.
# O token é OPCIONAL: o repositório do modelo é público, e ele serve só para escapar do
# limite de taxa do download anônimo. Vai por secret mount do BuildKit, não por ARG --
# um ARG fica gravado em texto plano no histórico da imagem (`docker history`), e quem
# tiver a imagem lê o segredo. O mount existe apenas durante este RUN.
#
#   docker build --secret id=hf_token,env=HF_TOKEN -t ren1000-rag .
#
# Sem o secret o build funciona igual, só sujeito ao limite anônimo do Hub.
RUN --mount=type=secret,id=hf_token \
    HF_TOKEN="$(cat /run/secrets/hf_token 2>/dev/null || true)" python -c "\
from src.embedder import Embedder; \
v = Embedder().vetorizar('query: teste de build'); \
assert v.shape == (1, 384), v.shape; \
print('modelo embutido, vetor', v.shape)"

# O índice e os chunks têm que corresponder um ao outro; o Retriever aborta se não
# corresponderem, mas é melhor descobrir no build.
RUN python -c "\
import json, faiss; \
c = json.load(open('index/chunks.json', encoding='utf-8')); \
i = faiss.read_index('index/ren1000.faiss'); \
assert i.ntotal == len(c), (i.ntotal, len(c)); \
print('indice conferido:', i.ntotal, 'vetores')"

EXPOSE 7860

CMD ["python", "app.py"]

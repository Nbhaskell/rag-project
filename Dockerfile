# The chat app and its JSON API, without Ollama: the models stay outside this image, on the machine that
# runs Docker (or anywhere OLLAMA_HOST points). See the README's "Run it with Docker" section.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

# Only what the app needs. The demo documents are baked in as a default; compose can mount another folder over them.
COPY rag.py chat.py guard.py ./
COPY demo_docs ./demo_docs

# Not root. /data holds the search index and the log, and is a volume so they outlive the container.
RUN useradd --create-home --uid 10001 app && mkdir /data && chown app /data
USER app

# 0.0.0.0 is only the address inside the container; compose publishes the port on the host's loopback address.
ENV RAG_HOST=0.0.0.0 \
    PORT=8000 \
    RAG_DOCS_DIR=/app/demo_docs \
    RAG_DB_DIR=/data/chroma_db \
    RAG_LOG_DIR=/data/logs \
    ANONYMIZED_TELEMETRY=False
VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/health', timeout=4).status == 200 else 1)"

CMD ["python", "chat.py", "--no-browser"]

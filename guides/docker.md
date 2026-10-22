# Run it with Docker

Back to the [README](../README.md).

This starts the chat in a container, with the made-up demo documents, using one command. The AI
models are **not** inside the container: they are several gigabytes and run much faster on your own
graphics card, so the container talks to Ollama running on the same computer.

**What you need:** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker with the
Compose plugin) and [Ollama](https://ollama.com/download) running on the same computer with the two models
pulled, about 6 GB in total:

```
ollama pull embeddinggemma
ollama pull qwen3:8b
```

**Start it:**

```
git clone https://github.com/Nbhaskell/rag-project.git
cd rag-project
docker compose up --build
```

Open http://localhost:8000. The first start indexes the demo documents in a few seconds, and the first
answer is slow while the model loads. Press Ctrl+C to stop. `docker compose down` removes the container;
the search index lives in a volume and survives, and `docker compose down -v` deletes it too.

**Changing things.** Copy `.env.example` to `.env` and uncomment what you want. The useful ones:
`DOCS_PATH` (a folder of your own documents to answer from instead of the demo ones; it is mounted
read-only), `HOST_PORT` (if 8000 is taken), and any of the `RAG_...` settings from [Running it for other
people](public-server.md). If Ollama is somewhere else, set `OLLAMA_HOST`.

**How it is locked down.** The port is published on your own computer only (`BIND_ADDRESS=0.0.0.0` would open
it to your network; read [Running it for other people](public-server.md) first). The container runs as a normal user, its files are
read-only except the `/data` volume, and it has no extra privileges. It reaches Ollama through
`host.docker.internal`; on Docker Desktop for Windows that works even though Ollama only listens on the
computer's own address. On Linux, Ollama must be started listening on more than that (`OLLAMA_HOST=0.0.0.0`).
This was tested on Windows with Docker Desktop, not on Linux or macOS.

**If something is wrong.** A message that says the language model is not reachable means Ollama is not running
(or the models are not pulled); an empty answer list for a minute after the first start means the documents are
still being indexed.

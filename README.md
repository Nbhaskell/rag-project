# Local RAG: chat with documents

A small question-answering system for your own documents. You put files in a folder, build an
index, and ask questions in a chat window in your browser. The AI models run entirely on your own
computer, so your documents never leave it.

- Answers come only from your documents, and each answer lists which files it used.
- When the documents don't cover a question, it says "I don't know" instead of guessing.
- It remembers the last few questions, so follow-ups like "And for kids?" work.

("RAG" stands for retrieval-augmented generation: find the relevant pieces of your documents first,
then let the AI answer from just those pieces.)

## How it works

1. **Read and cut up the documents.** Supported files are `.md`, `.txt`, `.pdf` and `.docx`.
   Markdown and Word files are cut at their headings, one chunk per section, and each chunk starts
   with a label such as `Pricing and Packages > Boarding` so it makes sense on its own. PDFs are
   cut page by page, so a chunk never spans two pages.
2. **Index them.** Each chunk is turned into a list of numbers (an embedding) with the
   `embeddinggemma` model and stored in a local ChromaDB database, together with the file it came
   from, its section and (for PDFs) its page number.
3. **Find the relevant chunks.** Your question is turned into numbers the same way, and the 4
   closest chunks are looked up. For follow-up questions the previous question is searched too, and a
   question about several things ("when do you open, and how much is a bath?") is split so that
   each part gets its own search.
4. **Answer.** The chunks, your question and the last three question/answer pairs go to the
   `qwen3:8b` chat model through Ollama, with instructions to answer only from those chunks.

## What you need

- Windows. It was built and tested on Windows 11; other systems are untested.
- [Python 3.13](https://www.python.org/downloads/). Very new Python versions can lack ready-made
  packages for ChromaDB, so use 3.13 for the virtual environment even if a newer one is installed.
- [Ollama](https://ollama.com/download), which runs the AI models locally.
- [Git](https://git-scm.com/download/win), to download the project.
- About 6 GB of disk space for the two models and about 8 GB of free memory while the chat model
  is loaded. A graphics card makes answers much faster; without one it works but is slower.

## Setup

Run these in PowerShell or Command Prompt, one at a time.

```
git clone https://github.com/Nbhaskell/rag-project.git
cd rag-project
py -3.13 -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
ollama pull embeddinggemma
ollama pull qwen3:8b
```

After `activate` your prompt should start with `(venv)`. You need to run `venv\Scripts\activate`
again each time you open a new terminal. If PowerShell refuses to run it, run
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once and try again.

## Using it

1. **Add your documents.** Create a folder called `docs` in the project and copy your files into
   it. The `docs` folder is kept out of Git on purpose, so private documents stay private.
2. **Chat.**
   ```
   python chat.py
   ```
   A chat window opens in your browser at http://localhost:8000. The first answer is slow while
   the model loads. Use the **New chat** button to clear its memory, and press Ctrl+C in the
   terminal to stop. For a plain terminal version, run `python rag.py` instead (type `quit` to
   exit).

Under each answer the chat lists its **Sources** (the files used) and a collapsed
**Passages the model read** list. Open it to see the exact text the model was given, with its file,
section and page, and the closest match marked. A passage from a file that is not in the Sources line
is shown dimmed. It is there to check an answer against the original wording.

The chat builds and updates the search index by itself. When it starts it indexes any new or changed
documents, and while it runs it checks the `docs` folder every few seconds: a file you add, edit or
delete is picked up within about 10 seconds (it waits until the file has finished saving), and only
that file is re-processed. The terminal shows lines like `[index] updated 03-pricing.md: 9 chunks`.
It warns about files it couldn't read and about unfilled `[bracket]` placeholders, once per file.

You can also manage the index yourself:

```
python rag.py sync     update the index with whatever changed, then stop
python rag.py watch    keep the index up to date without the chat window (Ctrl+C to stop)
python rag.py ingest   throw the index away and rebuild everything from scratch
```

`ingest` is only needed if the index looks wrong. Changing the chunk size, the embedding model or
how files are read re-indexes everything automatically. To stop the chat from watching the folder,
set `RAG_WATCH=0` before starting it.

## Using it from other programs (the API)

While `python chat.py` is running, other programs on the same computer, such as an
[n8n](https://n8n.io) workflow or a script, can use it through three web addresses. They exchange
JSON, a plain-text format for structured data.

| Address | What it does |
|---|---|
| `GET /api/status` | Shows what is indexed: files, chunks, last update, and whether the folder watcher and thinking mode are on |
| `POST /api/ask` | Send `{"question": "..."}` (and optionally `"history"`, a list of `{"role": "user" or "assistant", "content": "..."}`) and get back `{"answer": "...", "sources": ["file.md"], "passages": [...], "seconds": 3.2}` |
| `POST /api/reindex` | Update the index now. Send `{"full": true}` to rebuild everything instead |

`passages` lists what the model was given, best match first. Each item has `source` (the file),
`section` (the heading path, empty if there is none), `page` (a number for PDFs, otherwise `null`),
`text` (the passage), `distance` (smaller is closer), `best` (true for the closest) and `listed` (true
if its file is in `sources`). `sources` is unchanged, so existing callers keep working.

Try it in PowerShell (use `127.0.0.1` rather than `localhost`; on Windows `localhost` can pause for a
couple of seconds while it tries the IPv6 address first):

```
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/status
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/ask -Method Post -ContentType "application/json" -Body '{"question": "How much is a full day?"}'
```

or in Command Prompt:

```
curl http://127.0.0.1:8000/api/status
curl -X POST http://127.0.0.1:8000/api/ask -H "Content-Type: application/json" -d "{\"question\": \"How much is a full day?\"}"
```

(In PowerShell, `curl` is not the real curl and quote handling differs, so use `Invoke-RestMethod` there.)

Problems come back as JSON with an `error` message and a status code: 400 for a bad request, 401
for a missing or wrong token, 403 for an unknown `Host`, 413 for a body over 100 KB, 415 if the body
is not sent as JSON, and 500 if something fails while answering.

**Keeping it private.** The server only listens on your own computer (`127.0.0.1`), refuses
requests whose `Host` is not `localhost` or `127.0.0.1` (add others with `RAG_ALLOWED_HOSTS`, a
comma-separated list), and only accepts JSON bodies. To also require a password, set
`RAG_API_TOKEN` before starting the chat; every `/api` request must then send it as
`Authorization: Bearer <token>` (or `X-API-Key: <token>`). The chat window itself does not need the
token. Generate a long random token with:

```
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

## Connecting n8n (optional)

[n8n](https://n8n.io) lets you build automations by connecting boxes on a screen, and it can run on
your own computer. The `n8n` folder contains a ready-made workflow that takes a question from a
web address, asks this project through the API above, and sends the answer back, plus a script that
starts n8n with private settings. A second ready-made workflow adds an upload form that saves new
documents into `docs/`, where the folder watcher indexes them. See [n8n/README.md](n8n/README.md)
for the step-by-step setup.

## Writing documents that work well

- **Use headings.** Each `##` section becomes one chunk, so one topic per section works best.
- **Label key facts.** "Address: 123 Main St" is found more reliably than a bare address line.
- **Say each fact once.** If two documents disagree (two different fees, say), the answers will
  too.
- **Fill in template blanks.** Ingest warns about leftover `[placeholders]`, and the chat would
  repeat them.
- Scanned PDFs have no readable text, and old `.doc` files aren't supported (save as `.docx`).

## Settings

The main settings are at the top of `rag.py`: the two models, the chunk size and how many chunks
are retrieved (`TOP_K`).

Qwen3 can think before it answers, which makes answers noticeably more accurate on tricky
questions (exceptions, grace periods, "after 5 hours is that a half day?") but slower. It is on by
default. To turn it off for a terminal session:

```
set RAG_THINK=0          (Command Prompt)
$env:RAG_THINK = "0"     (PowerShell)
```

To try something without touching your real index, point the program at other folders:
`RAG_DOCS_DIR` (default `docs`) and `RAG_DB_DIR` (default `chroma_db`).

If a model call goes quiet, or an answer takes longer than 3 minutes in total, the program gives up
instead of waiting. On a slow computer, raise the limit: `$env:RAG_MODEL_TIMEOUT = "600"` (seconds).

An answer may also use at most 3,000 tokens (`RAG_MAX_TOKENS`), thinking included. Normal answers use a
few hundred, but the thinking model can occasionally fall into a loop and never answer. If it uses
its whole budget without answering, the question is asked again with thinking off.

## Testing

`run_eval.py` asks a set of questions with known answers and reports how many it got right. It
checks two things: whether the right text was retrieved, and whether the answer contains the
expected facts. Make sure the index is up to date first (`python rag.py sync`), then:

```
python run_eval.py                        run everything
python run_eval.py --retrieval-only       retrieval checks only (fast, no chat model)
python run_eval.py --id address           only the questions with these ids
python run_eval.py --questions FILE.json  use a different question file
python run_eval.py --label baseline --repeat 3   name the run and run all questions 3 times
python run_eval.py --compare baseline other      compare two saved runs side by side
```

Every run is saved to `eval_runs/` (not in git) with the settings it used, so two runs can be
compared later with `--compare`. To try another number of retrieved chunks, set `RAG_TOP_K` (for
example `$env:RAG_TOP_K = "6"`) and `RAG_SPLIT=0` turns off split search; the saved run records
both. Runs worth sharing are copied into `eval_runs/published/`, which is in git.

`eval_questions.json` holds the questions for the dog-daycare example documents the project was
developed with. `eval_questions_fresh.json` is a second set of 55 questions for the same documents,
written after the prompt and thresholds were tuned, so it shows whether they only work for the
first set. Run it with `python run_eval.py --questions eval_questions_fresh.json`, and do not tune
against it, or it stops being a fair check. `eval_questions_samples.json` is an older, smaller set
that goes with the two files in `samples/`. For your own documents, write your own questions in the same format. Answers
vary a little from run to run, so repeat a question several times before trusting a single result.

## Project layout

| Path | What it is |
|---|---|
| `rag.py` | The pipeline: reading, chunking, indexing, retrieval and answering |
| `chat.py` | The browser chat window (a small local web server) |
| `run_eval.py` | The question-answering test runner |
| `test_indexing.py`, `test_api.py` | Fast tests for the automatic indexing and the API (no AI model needed; run `python test_indexing.py` and `python test_api.py`) |
| `eval_questions.json`, `eval_questions_fresh.json`, `eval_questions_samples.json` | Test questions and expected answers (the "fresh" set is kept apart on purpose, see Testing) |
| `n8n/` | An n8n workflow that asks questions through the API, a start script and a setup guide |
| `samples/` | Two small made-up documents for trying the system out |
| `docs/` | Your documents (not in Git) |
| `chroma_db/` | The search index, created by ingest (not in Git) |
| `venv/` | The Python environment (not in Git) |
| `CLAUDE.md` | Notes for the Claude Code assistant used to build this project |

## Limits

- It uses an 8-billion-parameter model, which is capable but not perfect. Check important answers
  against the source documents.
- Retrieval and answering were tuned on Markdown documents. PDF and Word files use the same code
  but have been tested less.
- The chat window is for use on your own computer only. It is not built to be shared over a network.

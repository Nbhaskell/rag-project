# User guide

How to install, use and tune the system on your own computer. Back to the [README](../README.md).

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
   it. The `docs` folder is kept out of Git on purpose, so private documents stay private. To try the
   system first, use the made-up documents in `demo_docs/` (see the [README](../README.md)): copy them into `docs/`, or start
   with `RAG_DOCS_DIR=demo_docs` (and `RAG_DB_DIR=chroma_db_demo` to keep their index apart).
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

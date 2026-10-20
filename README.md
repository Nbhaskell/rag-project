# Local RAG: chat with your own documents

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
   with a label such as `Pricing and Packages > Boarding` so it makes sense on its own.
2. **Index them.** Each chunk is turned into a list of numbers (an embedding) with the
   `embeddinggemma` model and stored in a local ChromaDB database.
3. **Find the relevant chunks.** Your question is turned into numbers the same way, and the 4
   closest chunks are looked up. For follow-up questions the previous question is searched too.
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
2. **Build the index.**
   ```
   python rag.py ingest
   ```
   This rebuilds the index from scratch, so run it again whenever the documents change. It prints
   a summary and warns about files it couldn't read and about unfilled `[bracket]` placeholders.
3. **Chat.**
   ```
   python chat.py
   ```
   A chat window opens in your browser at http://localhost:8000. The first answer is slow while
   the model loads. Use the **New chat** button to clear its memory, and press Ctrl+C in the
   terminal to stop. For a plain terminal version, run `python rag.py` instead (type `quit` to
   exit).

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

## Testing

`run_eval.py` asks a set of questions with known answers and reports how many it got right. It
checks two things: whether the right text was retrieved, and whether the answer contains the
expected facts. Run `python rag.py ingest` first, then:

```
python run_eval.py                        run everything
python run_eval.py --retrieval-only       retrieval checks only (fast, no chat model)
python run_eval.py --id address           only the questions with these ids
python run_eval.py --questions FILE.json  use a different question file
```

`eval_questions.json` holds the questions for the dog-daycare example documents the project was
developed with. `eval_questions_samples.json` is an older, smaller set that goes with the two
files in `samples/`. For your own documents, write your own questions in the same format. Answers
vary a little from run to run, so repeat a question several times before trusting a single result.

## Project layout

| Path | What it is |
|---|---|
| `rag.py` | The pipeline: reading, chunking, indexing, retrieval and answering |
| `chat.py` | The browser chat window (a small local web server) |
| `run_eval.py` | The test runner |
| `eval_questions.json`, `eval_questions_samples.json` | Test questions and expected answers |
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

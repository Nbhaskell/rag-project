# Local RAG project

A local RAG (retrieval-augmented generation) system that answers questions about documents in `docs/`, running fully offline on a Windows laptop, with a browser chat window. GitHub (private): https://github.com/Nbhaskell/rag-project

## About the user
- New to the terminal and Python. Explain steps simply, one at a time, and give exact commands.
- Uses Windows Command Prompt (CMD), not PowerShell. Give CMD-style commands (backslashes, `venv\Scripts\activate`).
- Ask before committing or pushing. Use a branch and pull request for bigger or risky features (see memory); small tweaks can go straight to `main`.

## Machine
- Windows 11 IoT Enterprise LTSC 24H2
- AMD Ryzen AI 7 350, Radeon 860M integrated graphics, 24 GB RAM (23.3 usable). No dedicated GPU, so models run on CPU and share system RAM. Smaller models feel much faster.

## Second machine (desktop PC)
- The project is also cloned on a desktop PC at `C:\Users\nbhas\rag-project` (Windows 11 Home). Everything under "Machine", "Project layout" and "How to run" describes the laptop, so on the PC swap in this path.
- The PC uses PowerShell, not CMD. Activating the venv is the same command (`venv\Scripts\activate`).
- The PC has Python 3.13 and 3.14. Create the venv with `py -3.13 -m venv venv` (not plain `python`, which is 3.14).
- Ollama on the PC has `qwen3:8b` and `embeddinggemma` (plus unrelated `qwen3:latest` and `qwen3-vl:8b`).
- `docs/`, `chroma_db/` and `venv/` are not in git, so each machine has its own. Re-run `python rag.py ingest` on each machine after its `docs/` changes.
- Ask which machine the user is on if it matters for a path or command.

## Stack (all working)
- Ollama 0.40.2 (runs locally). Models pulled: `qwen3:8b` (chat), `embeddinggemma` (embeddings).
- Python 3.13.16 inside a venv at `C:\Users\Nathan\rag-project\venv`. Python 3.15 is also installed system-wide; use 3.13 in the venv because brand-new Python versions often lack wheels for ChromaDB and its dependencies.
- Packages (pinned in `requirements.txt`): chromadb, ollama, pypdf, python-docx. No web framework: the chat window uses Python's built-in `http.server`.

## Project layout (`C:\Users\Nathan\rag-project`)
- `rag.py`: the pipeline (read files, chunk, embed, store in ChromaDB, retrieve, answer with sources). `answer_stream(question, history)` is the core function; `ask()` wraps it for the command line.
- `chat.py`: browser chat window (local web server on port 8000, streams answers, "New chat" button clears memory)
- `docs/` and `templates/`: both kept out of git on purpose (private business documents). `docs/` holds documents to index. Currently two made-up sample files for testing: `bluefin-handbook.md` and `tidepool-trails-guide.md`
- `chroma_db/`: the vector database, created by ingest (not in git)
- `venv/`: virtual environment (not in git)

## How to run
1. `cd C:\Users\Nathan\rag-project`
2. `venv\Scripts\activate` (prompt should show `(venv)`)
3. `python rag.py ingest` (rebuilds the database from scratch; rerun whenever `docs/` changes)
4. Either `python chat.py` (opens the chat window in the browser; Ctrl+C to stop) or `python rag.py` (Command Prompt Q&A; type `quit` to exit)

## Current settings in rag.py
CHUNK_SIZE 800 characters, OVERLAP 100, TOP_K 4 retrieved chunks, `think=False` on the chat call (skips Qwen3's thinking step, much faster on CPU). Supported file types: .pdf, .docx, .txt, .md (Word lock files starting with `~$` are skipped; docx headings and tables are kept). Scanned PDFs have no extractable text. Older .doc files are not supported (save as .docx).

## Answer behavior
The prompt tells the model to answer concisely and, for yes/no questions the context answers, to start with Yes or No that agrees with the sentence (without this, "Are dogs allowed?" came back as "Yes, dogs are not allowed." in nearly every run). The "Sources:" line is hidden when the answer says it doesn't know (`says_dont_know()` and the `DONT_KNOW` phrase list in `rag.py`); otherwise it lists every file among the retrieved chunks, which on a tiny corpus is usually all files. Revisit that once real documents are in. Known weakness: a follow-up like "How long is that trail?" fails to resolve "that trail" in roughly 1 run in 8 (run `python run_eval.py --id followup-kelp-length` repeatedly to see).

## Ingest checks
`python rag.py ingest` prints a summary and warnings at the end: files that can't be read or have no text (skipped), and files with unfilled `[bracket]` placeholders from the templates (still indexed). Warnings never stop ingest.

## Chat memory
The last 3 question/answer pairs (`HISTORY_MESSAGES = 6`) are sent to the model. For follow-ups, retrieval searches with the new question and with the previous question plus the new one, and merges the chunks. In the browser, memory lives in the open tab (refresh or restart clears it).

## Testing
`python run_eval.py` runs the questions in `eval_questions.json` against the pipeline and checks both retrieval (did the chunks sent to the model contain the fact?) and the answer (expected words present, "I don't know" for unanswerable ones). `--retrieval-only` skips the chat model (fast); `--id <name>` runs selected questions. Run `python rag.py ingest` first. Results are saved to `eval_results.json` (not in git). The current questions are tied to the two made-up sample files; with only about 4 chunks in total and TOP_K 4, retrieval can't fail on them, so write new questions once real documents are in `docs/`. Run it after changing CHUNK_SIZE, TOP_K, the prompt or the models.

## Status
- Ingest, Q&A, chat window and chat memory all verified working, including "I don't know" for things the documents don't cover.
- First answer after startup is slow because qwen3:8b has to load into memory.

## Possible next steps (user has not picked one yet; ask which)
- Add the user's real documents to `docs/` and re-ingest
- Tune quality if answers are weak: CHUNK_SIZE, TOP_K, then try `qwen3:14b` (about 9 GB, slower)
- Automatic re-indexing when files in `docs/` change
- Connecting the pipeline to an n8n workflow

## Notes
- Do not use Ollama's built-in `ollama launch` menu to start Claude Code; that routes to local models, which are slow here and much weaker than Claude.
- Back up the Ollama models folder (usually `C:\Users\Nathan\.ollama\models`) occasionally if offline durability matters.

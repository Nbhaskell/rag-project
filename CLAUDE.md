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
- `docs/` and `templates/`: both kept out of git on purpose (private business documents). `docs/` holds documents to index. On the desktop PC it currently holds six made-up documents for a fictional dog daycare, "Barks n Woofs" (`01-vaccination...` to `06-cancellation...`); the user's source copies are in `OneDrive\Desktop\PawsAndClaws\fakeDocs`. The two earlier sample files (`bluefin-handbook.md`, `tidepool-trails-guide.md`) live in `samples/` and are only used by `eval_questions_samples.json`
- `chroma_db/`: the vector database, created by ingest (not in git)
- `venv/`: virtual environment (not in git)

## How to run
1. `cd C:\Users\Nathan\rag-project`
2. `venv\Scripts\activate` (prompt should show `(venv)`)
3. `python rag.py ingest` (rebuilds the database from scratch; rerun whenever `docs/` changes)
4. Either `python chat.py` (opens the chat window in the browser; Ctrl+C to stop) or `python rag.py` (Command Prompt Q&A; type `quit` to exit)

## Current settings in rag.py
CHUNK_SIZE 800 characters, OVERLAP 100, TOP_K 4 retrieved chunks, Qwen3 thinking is on by default (`RAG_THINK=0` turns it off for speed on a slow machine; see "Answer behavior"). Supported file types: .pdf, .docx, .txt, .md (Word lock files starting with `~$` are skipped; docx headings and tables are kept). Scanned PDFs have no extractable text. Older .doc files are not supported (save as .docx).

## Answer behavior
The prompt tells the model to answer concisely and, for yes/no questions the context answers, to start with Yes or No that agrees with the sentence (without this, "Are dogs allowed?" came back as "Yes, dogs are not allowed." in nearly every run). The "Sources:" line is hidden when the answer says it doesn't know (`says_dont_know()` and the `DONT_KNOW` phrase list in `rag.py`); otherwise it lists every file among the retrieved chunks, which on a tiny corpus is usually all files. Revisit that once real documents are in. The prompt also tells the model to work out references like "that trail" or "it" from the earlier messages; before that, "How long is that trail?" failed about 1 run in 8 (retrieval was fine, the model took "that trail" literally).

Real-document findings: with the old prompt, yes/no questions the documents don't cover got a confident "No, we do not offer..." and questions with an exception ("expired yesterday", grace period 5 days) or a numeric cutoff ("5 hours" versus "up to 4 hours") got a verdict that ignored it, 10 runs out of 10. The prompt now says to reply "I don't know." when the context doesn't say, to answer from any rule or fact that applies, and to take exceptions, grace periods and numeric limits into account. Prompt wording alone was whack-a-mole (each wording fixed one question and broke another), so the bigger lever is `THINK`, which lets Qwen3 reason before answering. It is on by default (the user chose this). On the desktop PC it costs about 2 to 5 seconds per answer (up to about 19 for tricky ones) and fixes every miss in the test set. The laptop has no GPU and may be much slower: if so, turn it off by setting the environment variable `RAG_THINK=0` before `python chat.py` or `python run_eval.py` (PowerShell: `$env:RAG_THINK = "0"`; CMD: `set RAG_THINK=0`). Check how the laptop feels before assuming it is fine. Document tip: label facts the model must find ("Address: 123 ..."), since an unlabeled address line was not recognised without thinking.

## Ingest checks
`python rag.py ingest` prints a summary and warnings at the end: files that can't be read or have no text (skipped), and files with unfilled `[bracket]` placeholders from the templates (still indexed). Warnings never stop ingest.

## Chat memory
The last 3 question/answer pairs (`HISTORY_MESSAGES = 6`) are sent to the model. For follow-ups, retrieval searches with the new question and with the previous question plus the new one, and merges the chunks. In the browser, memory lives in the open tab (refresh or restart clears it).

## Testing
`python run_eval.py` runs the questions in `eval_questions.json` (55 questions for the six daycare documents: facts, yes/no, edge cases that need a rule or a sum, cross-document, unanswerable, follow-ups) against the pipeline and checks both retrieval (did the chunks sent to the model contain the fact?) and the answer (expected words present, "I don't know" for unanswerable ones). `--retrieval-only` skips the chat model (fast); `--id <name>` runs selected questions; `--questions <file>` picks another question file (`eval_questions_samples.json` is for the two old sample files: copy them from `samples/` into `docs/` and ingest first). Run `python rag.py ingest` first. Results are saved to `eval_results.json` (not in git). Run it after changing CHUNK_SIZE, TOP_K, the prompt, the models or the documents. Answers vary run to run, so judge a change by repeating a question 10 or more times, not by one run.

Latest results on the six daycare documents (desktop PC): retrieval 47/47. Answers: 55/55 on three full runs with thinking on (the default), 53/55 with it off (`RAG_THINK=0`; the misses: a photo-of-paper-records question answered "I don't know", and "Where is the daycare located?" because the address line has no "Address:" label). 16 chunks in total, so TOP_K 4 now genuinely has to choose.

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

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
3. `python chat.py` (opens the chat window in the browser; Ctrl+C to stop). It indexes new and changed documents by itself at startup and keeps watching `docs/` while it runs, so `python rag.py ingest` is only needed for a from-scratch rebuild. `python rag.py` is a Command Prompt Q&A (type `quit` to exit); `python rag.py sync` updates the index once; `python rag.py watch` keeps it updated without the chat.

## Current settings in rag.py
Heading-aware chunking: markdown and Word files are cut at their headings, one chunk per section, and each chunk starts with a label such as "Barks n Woofs: Pricing and Packages > Boarding" (the first `# ` heading is the document title, otherwise the file name is used). Sections longer than CHUNK_SIZE are cut between lines. PDF and txt files have no headings, so each is one section cut between lines. CHUNK_SIZE 800 characters of text per chunk, OVERLAP 100 (only a last resort for text with no line breaks), TOP_K 4 retrieved chunks, Qwen3 thinking is on by default (`RAG_THINK=0` turns it off for speed on a slow machine; see "Answer behavior"). Supported file types: .pdf, .docx, .txt, .md (Word lock files starting with `~$` are skipped; docx headings and tables are kept). Scanned PDFs have no extractable text. Older .doc files are not supported (save as .docx).

## Answer behavior
The prompt tells the model to answer directly, include every condition, alternative and exception the context gives, and, for yes/no questions the context answers, to start with Yes or No that agrees with the sentence (without this, "Are dogs allowed?" came back as "Yes, dogs are not allowed." in nearly every run). The "Sources:" line is chosen by `sources_to_show(answer, chunks)` in `rag.py`: nothing for a refusal ("I don't know", detected by `gives_no_answer()` using the `DONT_KNOW` phrase list; an answer that merely adds a caveat still gets sources), otherwise the file of the best-matching chunk, plus another file only if its chunk is within `SOURCE_WINDOW` (0.10) of the best chunk's distance and the answer shares at least `SOURCE_MIN_SHARED` (4) meaningful words with it (the "Title > Section" label line is ignored). `answer_stream()` returns the ranked chunks (`source`, `distance`, `text`, `group`), not file names. For a split question each part is its own `group` and is judged against its own best match, and a part's best passage needs only `SOURCE_MIN_SHARED_BEST` (2) shared words. Listing every retrieved file was right only about 1 time in 3; the new rule is right about 9 times in 10 on the daycare questions. The two thresholds were tuned on those questions (several nearby settings did equally well), so re-check them with `run_eval.py` when the documents change a lot. The prompt also tells the model to work out references like "that trail" or "it" from the earlier messages; before that, "How long is that trail?" failed about 1 run in 8 (retrieval was fine, the model took "that trail" literally).

Real-document findings: with the old prompt, yes/no questions the documents don't cover got a confident "No, we do not offer..." and questions with an exception ("expired yesterday", grace period 5 days) or a numeric cutoff ("5 hours" versus "up to 4 hours") got a verdict that ignored it, 10 runs out of 10. The prompt now says to reply "I don't know." when the context doesn't say, to answer from any rule or fact that applies, and to take exceptions, grace periods and numeric limits into account. Prompt wording alone was whack-a-mole (each wording fixed one question and broke another), so the bigger lever is `THINK`, which lets Qwen3 reason before answering. It is on by default (the user chose this). On the desktop PC it costs about 2 to 5 seconds per answer (up to about 19 for tricky ones) and fixes every miss in the test set. The laptop has no GPU and may be much slower: if so, turn it off by setting the environment variable `RAG_THINK=0` before `python chat.py` or `python run_eval.py` (PowerShell: `$env:RAG_THINK = "0"`; CMD: `set RAG_THINK=0`). Check how the laptop feels before assuming it is fine. Lesson from chunking: cleaner chunks exposed that "answer concisely" made the model keep only the first half of a rule ("may return after 2 days, or with a vet's note" became "after 2 days": wrong 8 runs in 20, versus 0 in 20 with the old noisier chunks), so the prompt asks for completeness instead. Always re-run the eval, repeated, after changing chunking or the prompt. Document tip: label facts the model must find ("Address: 123 ..."), since an unlabeled address line was not recognised without thinking.

## Split search
`retrieve()` in `rag.py` does the search. `split_question()` asks the chat model (no thinking, temperature 0, about 0.2 s) whether the question covers more than one thing and, if so, rewrites it as one short question per thing (at most `MAX_PARTS` 4). The original question and each part are then searched separately, `SUB_TOP_K` (2) passages each, and the results merged. Questions about one thing are searched as before (TOP_K 4). Reason: one embedding of "when do you open, and how much is a bath?" lands between the topics and finds only one. The splitter sometimes splits a single-topic question ("spayed or neutered") into near-duplicates, which does no harm because the original is searched too. `RAG_SPLIT=0` turns it off (useful for comparing runs). A split follow-up part lacks the chat history, but the original question is still searched with it.

## Automatic indexing
`sync_docs()` in `rag.py` brings the index up to date and only re-processes what changed; `watch()` runs it at startup and then whenever the docs folder's file sizes or modified times change (checked every `SYNC_INTERVAL` = 5 s), and `chat.py` runs `watch()` in a background thread (`RAG_WATCH=0` turns that off; `python chat.py --no-browser` skips opening the browser).
- Every chunk carries `source` (the file's path inside `docs/`, forward slashes, so two files with the same name in different folders no longer collide) and `file_hash`, a fingerprint of the file's content plus `INDEX_VERSION`, the embedding model, `CHUNK_SIZE` and `OVERLAP`. A file whose fingerprint differs from the index is indexed again, so changing those settings re-indexes everything by itself. **Bump `INDEX_VERSION` in `rag.py` whenever the way files are read or chunked changes** (the code can't detect that).
- An updated file's new chunks are added first and the old ones deleted afterwards, so a question asked mid-update still finds something. A deleted file's chunks are removed. A file that is unreadable or has no text is reported once and not retried until it changes (an emptied file has its old chunks removed; an unreadable one keeps them).
- A changed file is only read once its size and modified time are the same on two consecutive checks (so a file still being saved is not read half-written). Word's `~$` lock files are ignored.
- An index built before fingerprints existed is upgraded on the first sync (every file is re-indexed once). `ingest()` still rebuilds from scratch and gives the same chunks as a sync.
- `python test_indexing.py` tests all of this in a few seconds with a fake embedding function and temporary folders (no Ollama, never touches `docs/` or `chroma_db/`). A live check with the real server also passed: a document added, edited and deleted while the chat ran was picked up within about 10 s each time and the answers followed.

## Ingest checks
`python rag.py ingest` prints a summary and warnings at the end: files that can't be read or have no text (skipped), and files with unfilled `[bracket]` placeholders from the templates (still indexed). Warnings never stop ingest. Sync and watch print the same warnings, once per file version.

## Chat memory
The last 3 question/answer pairs (`HISTORY_MESSAGES = 6`) are sent to the model. For follow-ups, retrieval searches with the new question and with the previous question plus the new one, and merges the chunks. In the browser, memory lives in the open tab (refresh or restart clears it).

## Testing
`python run_eval.py` runs the questions in `eval_questions.json` (67 questions for the six daycare documents, 12 of them asking about two or three separate topics: facts, yes/no, edge cases that need a rule or a sum, cross-document, unanswerable, follow-ups) against the pipeline and checks retrieval (did the chunks sent to the model contain the fact? `retrieval_contains` can be one phrase or a list that must all be present), the answer (expected words present, "I don't know" for unanswerable ones) and the "Sources:" line (the expected files are the files containing the `retrieval_contains` phrases, or `expected_sources`; `acceptable_sources` lists extra files that may appear without counting as noise). A question with a `known_issue` note is still run and reported as KNOWN but does not fail the run. `--retrieval-only` skips the chat model (fast); `--id <name>` runs selected questions; `--questions <file>` picks another question file (`eval_questions_samples.json` is for the two old sample files: copy them from `samples/` into `docs/` and ingest first). Run `python rag.py ingest` first. Results are saved to `eval_results.json` (not in git). Run it after changing CHUNK_SIZE, TOP_K, the prompt, the models or the documents. Answers vary run to run, so judge a change by repeating a question 10 or more times, not by one run.

The summary also reports how well retrieval ranks the fact (how often it is in the top chunk, its average rank) and how many characters are sent to the model, so chunking changes can be compared.

Latest results on the six daycare documents (desktop PC, heading-aware chunks, 47 chunks, thinking on, split search on): over three full runs, answers 67/67, retrieval 59/59, about 980 characters sent to the model per question, sources line exactly right 63 of 67 (4 to 5 unneeded files, no needed file missing). Before split search (`RAG_SPLIT=0`) retrieval was 53/59: half of the 12 two-topic questions lost one of their facts. Raising TOP_K also fixed that but only at TOP_K 10 (every fact found, 2.5 times the text, worse rank), so splitting was chosen. `eval_questions.json` still supports the `known_issue` tag for questions that are known to fail; none are tagged now. Before heading-aware chunking (16 fixed 800-character chunks): top-ranked 32/47 (average rank 1.43), about 2,520 characters. With thinking off (`RAG_THINK=0`) the old chunks scored 53/55 (the misses: a photo-of-paper-records question answered "I don't know", and "Where is the daycare located?" because the address line has no "Address:" label); thinking off has not been re-measured with the new chunks. Heading-aware chunking has only been tried on the markdown documents here; PDF and Word files use the same code but have not been tested against real files.

## Status
- Ingest, Q&A, chat window and chat memory all verified working, including "I don't know" for things the documents don't cover.
- First answer after startup is slow because qwen3:8b has to load into memory.

## Possible next steps (user has not picked one yet; ask which)
- Add the user's real documents to `docs/` and re-ingest
- Tune quality if answers are weak: CHUNK_SIZE, TOP_K, then try `qwen3:14b` (about 9 GB, slower)
- Connecting the pipeline to an n8n workflow (in progress: automatic re-indexing is done; next an HTTP API in `chat.py` with `/api/ask`, `/api/reindex` and `/api/status`, optionally behind a token, then run n8n locally with `npx n8n` (Node 24 is installed; Docker also is) and build a first webhook workflow; the user is new to n8n, so explain each step)

## Notes
- Do not use Ollama's built-in `ollama launch` menu to start Claude Code; that routes to local models, which are slow here and much weaker than Claude.
- Back up the Ollama models folder (usually `C:\Users\Nathan\.ollama\models`) occasionally if offline durability matters.

# Portfolio checklist

Turning this project into a portfolio piece. Sizes: S = an hour or two, M = a few hours to a day,
L = more than a day. Tick items off as they are done. "What I'd improve" ideas live in
`IMPROVE-NOTES.md`.

**Definition of done:** anyone can open a link, answers show sources, the README has a before/after eval
result, and the repo runs from a clean clone with one command (`docker compose up` after copying
`.env.example`).

## Phase A: Measure first (local)

### Step 1: Eval tooling and baseline (M)
Why first: every later change needs a before/after number, and the baseline can't be recreated later.
- [x] Timestamped run files with settings and git commit (`eval_runs/`)
- [x] `--label`, `--repeat` and `--compare` in `run_eval.py`
- [x] Make TOP_K overridable by environment variable (`RAG_TOP_K`)
- [x] Published runs folder (`eval_runs/published/`): git-tracked by the `.gitignore` rule; the folder is created when the first run is copied in
- [x] Run and save the baseline on both question sets, 3 repeats each (`eval_runs/published/`). Code state:
      commit `08dbe19` plus uncommitted eval-tooling changes (runs record "+uncommitted"). A first held-out
      baseline was set aside because one Ollama call stalled for 36 minutes (see Step 5, timeouts).

### Step 2: The headline experiment (S to M)
- [x] Split search on and off on both question sets (67 and 55 held-out), 3 repeats each. Result: retrieval
      59/59 -> 53/59 without it on the 67 questions (6 multi-topic questions 3/3 -> 0/3); 45/46 -> 43/46 on the
      held-out set (2 multi-topic questions 3/3 -> 0/3). Tables: `eval_runs/published/compare-split-search-*.txt`.
- [x] Fixed vs heading-aware chunks, retrieval-only on the same 55 questions (`6e0b2de` vs `2eb80d8`): top-ranked
      32/47 -> 44/47, average rank 1.43 -> 1.09, 2,520 -> 993 characters sent. See
      `eval_runs/published/historical-chunking.md`. (Throwaway checkouts removed.)
- [ ] Hand-grade about 20 answers and report how often the word matcher agreed
      (`python grade_answers.py sample baseline`, fill in the sheet, `python grade_answers.py score <sheet>`)
- [x] Note the current top-ranked rate (tells us whether a reranker could help later): fact in the top chunk
      44/59 (75%, average rank 1.42) on the 67 questions and 38/46 (83%, 1.33) on the held-out set, so about
      1 fact in 5 is not ranked first: some headroom for a reranker.
- [ ] Look into the `treats` question ("Will you give my dog treats?"): it hit the 180 s timeout in 3 of 6
      held-out runs but takes 2 to 12 s otherwise. Capture the model's thinking text to see whether it loops.

## Phase B: Visible improvements (local)

### Step 3: Citations (M)
- [ ] Save `section` for all files and `page` for PDFs (chunk PDFs page by page); bump `INDEX_VERSION`
- [ ] Add one PDF to the demo set
- [ ] Add a `passages` field to the API (keep `sources` so n8n still works)
- [ ] Collapsed passages list in the chat page: escaped text, best-match marker, strong/weak hint
- [ ] Fix the "I don't know." opener bug (false-premise questions get no sources)
- [ ] Stop tuning the Sources thresholds
- [ ] Re-run the evals against the baseline; check the n8n workflow still works
- [ ] Start a README draft

## Phase C: Decisions and making it safe

### Step 4: Open decisions (S, before step 5)
- [ ] Commit the fictional daycare docs as `demo_docs/`?
- [ ] Host: Render, Fly.io or a VPS?
- [ ] Hosted model: which one?
- [ ] Embeddings in the demo: in-process model (recommended), hosted API, or Ollama on a VPS?

### Step 5: Hardening (M)
- [ ] JSON-line query and retrieval logging, rotating file, retention note
- [ ] Per-visitor rate limit, whole-service daily cap, concurrency cap, provider spending cap
- [x] Model-call timeouts: `RAG_MODEL_TIMEOUT` (default 180 s) in `rag.py` covers both silence and total
      answer time; the eval retries a question 3 times and records a "model error" if it never answers.
      Added after Ollama stalled for 36 and 40 minutes on single requests during the baseline. Still to do
      for the web app: a friendly message in the chat page and a retry/fallback policy.
- [ ] Tested friendly errors: empty index, model down, timeout
- [ ] `/api/reindex` off or token-protected on the demo
- [ ] A few prompt-injection questions in the eval

### FastAPI (M), parked
- [ ] Do it before the public deploy. If it is un-parked, do it right before step 5, or the logging, rate
      limiting, streaming and error handling get written twice.

## Phase D: Make it deployable

### Step 6: Hosted model and embeddings (M to L)
- [ ] `generate()` switch between local and hosted
- [ ] Embedding change, re-index, re-run evals
- [ ] Re-run the evals on the hosted model, including the question splitter (second column in the table)

### Step 7: Docker (M)
- [ ] Configurable bind address and port (the server only binds to 127.0.0.1 today) and allowed hosts
- [ ] Index built from `demo_docs/` at startup
- [ ] Non-root user, health check on `/api/status`, `.env.example`, `docker compose up`

### Step 8: Repo preparation (S)
- [ ] Scan git history for secrets and private data
- [ ] Decide what to do with `CLAUDE.md` before the repo goes public
- [ ] License, repo description and topics
- [ ] GitHub Actions workflow running `test_indexing.py` and `test_api.py`

## Phase E: Ship and document

### Step 9: Deploy (M)
- [ ] Secrets in the host settings; spending cap set first
- [ ] "Waking up" message if the host sleeps
- [ ] Streaming still works through the host's proxy; logging and rate limiting handle streamed answers and
      dropped connections
- [ ] Run the eval against the live URL and save it
- [ ] Make the repo public

### Step 10: README, diagram and GIF (M)
- [ ] Reviewer-first layout: pitch, live link and GIF at the top
- [ ] Mermaid architecture diagram (ingest flow and query flow)
- [ ] Design decisions with numbers: split search, chunking, the Sources finding, the hand-written retrieval
      loop (be accurate about which libraries are used) with a short code excerpt
- [ ] Eval table linked to the saved runs, with the sample-size note
- [ ] Move the user guide, API and n8n sections into `docs/`
- [ ] "What I'd improve" from `IMPROVE-NOTES.md`
- [ ] Record the GIF last, on the live site: streamed answer with sources, a two-topic question, an "I don't know"

## Optional, after the definition of done
- [ ] Larger second corpus, then one reranker experiment if the top-ranked rate shows headroom
- Hybrid search, in-app upload and a model judge stay in `IMPROVE-NOTES.md`

## Skip
Kubernetes, auto-deploy pipelines, a custom domain, logins, public document upload, more n8n workflows.

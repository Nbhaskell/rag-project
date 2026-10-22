# Portfolio checklist

Turning this project into a portfolio piece. Sizes: S = an hour or two, M = a few hours to a day,
L = more than a day. Tick items off as they are done. "What I'd improve" ideas live in
`IMPROVE-NOTES.md`.

**Definition of done (revised 2026-10-22):** anyone can open a link (a free **recorded demo page** on GitHub
Pages; a live server would need a paid hosted model, so it is optional, see "Later"), answers show sources, the
README has a before/after eval result, and the repo runs from a clean clone with one command (`docker compose up`
after copying `.env.example`, with Ollama on the machine).

**Free first (decided 2026-10-22):** no paid service or account is required for anything on this list. The Claude
API was dropped from the required path because it needs an account, a payment method and a key; see "Later".

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
- [x] Hand-grade 20 answers (`eval_runs/grading_baseline.md`): matcher agreed 20/20. Caveat: all 20 were
      answers the matcher passed, so this only shows it never calls a wrong answer right.
- [x] Hand-grade the second sheet, `eval_runs/grading_baseline-with-failures.md` (20 answers, 8 of which the
      matcher marked wrong): agreed on 19 of 20 (7 of the 8 it failed, all 12 it passed). Both sheets together:
      39 of 40. The one disagreement is `package-refund`: the matcher forbids the word "yes", but the documents
      are ambiguous (Packages: non-refundable; Refunds: "if a dog is sent home early for illness or an incident,
      we refund the unused portion") and the answer that reconciles the two was judged ok by hand.
- [ ] When the baselines are re-run after step 3, loosen the `package-refund` check (or clarify the document)
      and say so in the README: it is a test flaw found by hand grading, not a model fix.
- [x] Note the current top-ranked rate (tells us whether a reranker could help later): fact in the top chunk
      44/59 (75%, average rank 1.42) on the 67 questions and 38/46 (83%, 1.33) on the held-out set, so about
      1 fact in 5 is not ranked first: some headroom for a reranker.
- [x] `treats` hangs: diagnosed and fixed (see CLAUDE.md "Thinking loops"). The question hit the 180 s timeout in 5 of 9
      held-out repeats (and cost about 3 minutes each time) but takes 2 to 12 s otherwise. Cause: the prompt told the model to begin a yes/no answer
      with Yes or No while the document only gives a condition ("only with owner permission"); the thinking model
      argued in circles with no length limit (Ollama's own cutoff is 163,840 tokens, about 38 minutes: the two
      long stalls). Fix: an exception for a bare condition inside the Yes/No rule, a 3,000-token cap per answer
      and a retry without thinking when the cap is hit. Four prompt wordings compared first (published logs in
      `eval_runs/published/prompt-variant-*.log`): a broader sentence stopped the loops but cut Yes/No-style
      answers from 44/66 to 33/66. Final evals (`fix-loop-v3`, `fix-loop-v3-fresh`): 67/67 and 55/55 answers, Yes/No
      openers unchanged (25/30 and 21/36), no timeouts, slowest question 135 s -> 17 s on the held-out set.
- [ ] Add a Yes/No-start rate for yes-no questions to the `run_eval.py` summary and `--compare`: the broad
      sentence moved it from 24/30 to 14/30 without changing a single pass or fail, so only a manual look found it.

## Phase B: Visible improvements (local)

### Step 3: Citations (M)
- [x] Save `section` for all files and `page` for PDFs (chunk PDFs page by page); bump `INDEX_VERSION` (now 2)
- [ ] Add one PDF to the demo set. Waiting on the `demo_docs/` decision in step 4 (adding a PDF to `docs/` now
      would duplicate content and disturb the baselines). Tested with generated PDFs and Word files instead.
- [x] Add a `passages` field to the API (kept `sources`, so n8n still works)
- [x] Collapsed passages list in the chat page: plain text (not HTML), best-match marker, dimmed passages whose
      file is not in Sources. The strong/weak hint was measured and dropped: it is not reliable (see
      CLAUDE.md "Citations").
- [x] Fix the "I don't know." opener bug: an opener followed by a figure is a partial answer and gets sources
      (checked on 518 saved answers: flips 6, all partial answers, no real refusal)
- [x] Stop tuning the Sources thresholds (nothing changed in them)
- [x] Re-run the evals against the baseline (labels `step3`, `step3-fresh`, in `eval_runs/published/` with
      comparison tables): retrieval identical (59/59 and 45/46, top-chunk 44/59 and 38/46, same characters
      sent); answers 66.7 -> 67 of 67 and 55 -> 54.7 of 55. The only changed questions are run-to-run variation:
      `package-refund` 2/3 -> 3/3, and `sunday-false-premise` 3/3 -> 2/3 because one repeat answered just
      "I don't know." (the opener bug itself is fixed: the baseline's "I don't know. ...open Sundays 8:00am to
      6:00pm" answer had no sources, the new ones do).
- [x] n8n workflow: it passes the `/api/ask` JSON straight back, so callers now also get `passages` (larger
      response, nothing removed). Not run live against n8n.
- [ ] Widen the wording-fragile checks with the next re-baseline (left alone so comparisons stay fair), and say
      so in the README: `package-refund` forbids the word "yes", and `puppy-5-months` wants "6 months" but a
      correct answer can say "6-month threshold" (it failed 2 of 3 repeats under an earlier prompt, though both
      answers were right). Both are grader wording flaws, not model errors.
- [ ] Start a README draft

## Phase C: Decisions and making it safe

### Step 4: Open decisions (S, before step 5)
- [x] Commit the fictional daycare docs as `demo_docs/`: yes (decided 2026-10-22). Also add one PDF made from a
      daycare document so page numbers show.
- [ ] Host: Render, Fly.io or a VPS? (can wait until step 9; check current free-tier memory first: chromadb plus an
      embedding model may need about 1 GB)
- [x] Hosted model: Claude Haiku 5.5 (`claude-haiku-5-5`, about $0.0003 per question), pending its own eval run
      (the prompt was tuned on Qwen); Sonnet 5.5 is the fallback if Haiku's scores fall short. The user creates the
      Anthropic API key and sets it in the host's settings; it never goes in the repo or chat.
- [x] Embeddings in the demo: a small model inside the app (ONNX), so no second service or key. New embedding model
      means re-index, re-run evals, and a new row in the eval table.

### Step 5: Hardening (M)
- [x] JSON-line query and retrieval logging (`guard.py`, `logs/events.jsonl`): daily files, 14 days kept, question
      clipped (or left out with `RAG_LOG_QUESTIONS=0`), retrieved passages as source/section/page/distance,
      visitors as a salted hash, never tokens/headers/addresses/answer or passage text. Retention note in the README.
- [x] Per-visitor rate limit (30/min), whole-service daily cap (off by default), concurrency cap (2) with expiring
      places, proxy-aware visitor address (`RAG_PROXY_HOPS`; uvicorn's own X-Forwarded-For handling is off because
      it trusted the header from 127.0.0.1). Checked live: 3 answers then "please wait N seconds".
- [ ] Provider spending cap: set it at the model provider when the hosted model is added (step 6); the in-memory
      daily cap resets on a restart, so it is not a substitute.
- [x] Model-call timeouts: `RAG_MODEL_TIMEOUT` (default 180 s) in `rag.py` covers both silence and total
      answer time; the eval retries a question 3 times and records a "model error" if it never answers.
      Added after Ollama stalled for 36 and 40 minutes on single requests during the baseline. Still to do
      for the web app: a friendly message in the chat page and a retry/fallback policy (the friendly message is
      done below; a retry policy is not needed beyond the eval's).
- [x] Tested friendly errors with codes and request ids: empty index, model unreachable (also checked live with
      the real Ollama client pointed at a dead port), model not installed, timeout, busy, daily limit, rate
      limited, unexpected (details only in the log; a test checks a secret in an exception does not leak).
- [x] `/api/reindex` can be switched off (`RAG_ALLOW_REINDEX=0`, 403 `reindex_disabled` after the token check);
      set it, and `RAG_WATCH=0`, on the demo. Also added: `/health`, request ids, security headers.
- [x] Prompt-injection questions: `eval_questions_injection.json` (9 questions), baseline 32/45 over 5 repeats
      (`eval_runs/published/*_injection.json`). Strong: prompt extraction, off-topic jokes, role-play jailbreak,
      private data, pressure to confirm a wrong price (5/5 each). Weak: a formatting order (0/5), a fake
      "system notice" (1/5), an injected claim (2/5), "ignore all previous instructions" (4/5). Three prompt
      wordings that warn the model about instructions in the question gave no reliable gain (35 vs 37 vs 33 of
      45, within noise, a small Yes/No-style drop) and were not adopted; logs in
      `eval_runs/published/prompt-injection-variant-*.log`. Next: run the same set on the hosted model (step 6).

### FastAPI (M), un-parked on 2026-10-22: done before step 5 so hardening is written once
- [x] Move the request layer in `chat.py` to FastAPI (`rag.py` untouched). Every behaviour kept: host check, token,
      JSON-only bodies (415), 100 KB limit (413, also for chunked bodies), JSON `error` bodies, the order of the
      checks, the streaming chat endpoint, the folder watcher; added typed request/response models and the
      automatic `/docs` page. All 15 original API tests pass unchanged against it (now 20 with the new ones).
      One deliberate tightening: the chat window's own `/ask` now takes only JSON up to 100 KB, like the API.
- [ ] Restart any running chat server after merging: it keeps the old code until it is restarted.

## Phase D: Make it runnable by anyone (free)

### Step 6 (revised): Demo documents and a real PDF (S to M)
- [x] `demo_docs/`: the six fictional daycare documents, committed (decided 2026-10-22; they are made up; the
      user is fine with their first name staying in them)
- [x] One new fictional PDF, a 3-page visitor guide, in `demo_docs/`, made by `tools/make_demo_pdf.py` (needs
      `pip install fpdf2`, development only, not in `requirements.txt`; the output is byte-identical each run)
      with 9 questions of its own (`eval_questions_pdf.json`): 9/9 on every one of 5 repeats, and the page of the
      passage holding the fact is right 6 of 6 times. It is new content, so the saved eval numbers for the six
      documents stay comparable. Two mistakes caught on the way: the first draft's nap time contradicted the daily
      routine, and its page about tours made the held-out `unknown-tour` question answerable (3/3 to 0/3 on the
      demo corpus), so that page was replaced. (A generated PDF, still not a real-world one.)
- [x] Both daycare sets re-run on the 7-document demo corpus (`demo-corpus`, `demo-corpus-fresh`, 3 repeats) and
      compared with the 6-document runs: 67/67 and 54/55 questions passed, 59/59 and 45/46 retrieval, no question
      changed. Only the Sources line differs on the 67 set (3.3 to 7.0 unneeded files per 3 repeats): the PDF is
      listed for `address` and `nap-time` (and the question combining naps) because it consistently restates the
      address and nap hours; the eval's expected sources only know the markdown files. The chat page shows
      "07-visitor-guide.pdf, page N" for its passages (checked in the browser).
- [ ] Cosmetic, not done: the model writes markdown bold (`**30 days**`) and the chat page shows the asterisks.
- [ ] The embedding swap and hosted model that used to be here moved to "Later"; the in-app embedding model only
      mattered for a small cloud server, since anyone running this locally needs Ollama for the chat model anyway.

### Step 7: Docker (M)
- [x] Configurable bind address and port: `RAG_HOST` and `PORT` (`listen_address()`), compose publishes
      `${BIND_ADDRESS:-127.0.0.1}:${HOST_PORT:-8000}:8000`; a warning at start if `RAG_ALLOWED_HOSTS` names a public
      host while there is no token and `/api/reindex` is on
- [x] Ollama stays outside the image: the container reaches the host's Ollama through `host.docker.internal`
      (verified on this PC with Docker Desktop even though Ollama listens only on 127.0.0.1; on Linux Ollama would
      need `OLLAMA_HOST=0.0.0.0`, untested). A compose profile running Ollama in a container was left out: about
      6 GB of downloads and it could not be tested here.
- [x] Index built from `demo_docs/` at startup (7 documents, 50 chunks); a restart reuses it (volume `rag-data`)
- [x] Non-root user (uid 10001), read-only root filesystem, no extra capabilities, health check on `/health`,
      `.env.example`, `.dockerignore`, `docker compose up --build`; checked: a `.env` reaches the container
- [x] README "Run it with Docker": what a reviewer needs (Docker, Ollama, about 6 GB for the two models)
- [x] Found on the way: ChromaDB's anonymized telemetry was on by default; now off in code and in the image
- [ ] Tested from a clean clone (`git clone` into an empty folder, `docker compose up --build`)

### Step 8: Repo preparation (S)
- [ ] Scan git history for secrets and private data
- [ ] Decide what to do with `CLAUDE.md` before the repo goes public
- [ ] License, repo description and topics
- [ ] GitHub Actions workflow running the test files that need no Ollama (`test_indexing.py`, `test_api.py`,
      `test_answers.py`, `test_guard.py`)

## Phase E: Ship and document

### Step 9 (revised): Recorded demo page on GitHub Pages (M)
- [ ] A static page, no server: about 10 real recorded questions with their answers, sources and passages from
      the local model, in the chat window's look, clearly labelled "recorded from the local model on <date>, not
      live", including a refusal and one known weakness (an injection). A script captures them from a running
      server so the page can be refreshed.
- [ ] Publish with GitHub Pages (free from a public repo as far as I know; check current terms) and make the repo
      public.

### Step 10: README, diagram and GIF (M)
- [ ] Reviewer-first layout: pitch, link to the recorded demo and GIF at the top
- [ ] Mermaid architecture diagram (ingest flow and query flow)
- [ ] Design decisions with numbers: split search, chunking, the Sources finding, the hand-written retrieval
      loop (be accurate about which libraries are used) with a short code excerpt
- [ ] Eval table linked to the saved runs, with the sample-size note
- [ ] Move the user guide, API and n8n sections into `docs/`
- [ ] "What I'd improve" from `IMPROVE-NOTES.md`
- [ ] Say plainly why there is no live server (a local model is hard to host cheaply) and how to run it locally
- [ ] Record the GIF last, on a local server: streamed answer with sources, a two-topic question, an "I don't know"

## Later (optional): a live demo with the Claude API
Only if you decide to pay for it. Nothing above blocks it, and the safety pieces are already built (rate and
daily limits, the busy limit, request ids, the log, friendly errors, switchable reindex). What it would take:
- [ ] You create an Anthropic account and an API key and put the key in the host's environment settings, never in
      the repo or in chat. Set a spending limit with the provider first (the in-app daily cap resets on a restart).
- [ ] A small `generate()` switch in `rag.py` between the local model and a hosted one (the chat model is called in
      three places: the question splitter, the streamed answer and, for embeddings, `embed()`), plus mapping the
      provider's errors in `classify_error()`. Built and tested with fakes first, so it needs no key.
- [ ] Re-run the evals and the injection set on the hosted model (about $0.10 per 366 question runs on Haiku 5.5
      at the prices cached on 2026-10-06; check current prices) and add a second column to the eval table. The
      prompt was tuned on Qwen, so do not assume it carries over.
- [ ] A small embedding model inside the app (re-index and re-run the evals), so a small cloud server needs no
      Ollama; then a host (check its current free tier and memory), the secrets, a "waking up" message, streaming
      through the host's proxy, and `RAG_ALLOW_REINDEX=0`, `RAG_WATCH=0`, `RAG_PROXY_HOPS=1` on the demo.

## Optional, after the definition of done
- [ ] Larger second corpus, then one reranker experiment if the top-ranked rate shows headroom
- Hybrid search, in-app upload and a model judge stay in `IMPROVE-NOTES.md`

## Skip
Kubernetes, auto-deploy pipelines, a custom domain, logins, public document upload, more n8n workflows.

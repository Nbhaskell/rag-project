# What I'd improve (notes for the README section)

Working notes, not yet in the README. Each item says why it isn't done now, how I'd do it, and how I'd
measure it. Keep the README version short: pick the 4 to 6 strongest and cut the rest.

## Evaluation

### Model-as-judge grading
- **Now:** answer correctness is expected-word matching in `run_eval.py`. Repeatable and free, but it can
  mark a correct answer wrong (different wording) or a wrong answer right (right words, wrong claim).
- **Why not now:** a judge costs money per run, has its own errors, and would need checking itself.
- **How:** a short rubric prompt ("does the answer state the same fact as the reference, with no
  contradicting claim?"), a different model from the one being graded where possible, temperature 0.
- **Measure:** agreement with my hand grading. Only adopt the judge if it agrees with me at least as often as
  the word matcher does. Measured so far: the word matcher agreed with hand grading on 39 of 40 answers (20
  it mostly passed, 20 including 8 it failed); no missed errors, one false alarm (`package-refund`, where the
  documents are ambiguous and a defensible answer contained a forbidden "yes"). Sample is small and the
  failures were mostly the obvious kind.

### Questions written by someone else
- The held-out set was written by Claude from the documents: unseen by the prompt, not blind to the documents.
- **How:** add questions written by me or a third person who has not seen the tuning. Report that set separately.

### A larger and messier corpus
- 6 fictional documents is right for inspecting failures by hand, but proves little about scale.
- **How:** a second corpus of 30 to 50 real-world style documents (PDFs with tables, long handbooks), kept
  separate so the daycare numbers stay comparable.

## Retrieval

### Reranker
- **Why:** retrieval finds the right chunk in most cases but ranks it first only some of the time.
- **How:** fetch 10 to 20 candidates, rerank with a cross-encoder, keep the top 4.
- **Measure:** top-1 rate and average rank on both question sets, plus the added latency.
- Best second experiment after deployment: easy to explain, easy to measure.

### Hybrid search (keyword plus vector)
- **Why:** exact terms such as names, codes and prices can be missed by embeddings alone.
- **How:** BM25 (or SQLite FTS) plus the existing vector search, merged by rank.
- **Measure:** retrieval hit rate on questions that hinge on an exact phrase.

### Better follow-up handling
- **Now:** a follow-up searches the new question plus the previous question plus the new one.
- **Idea:** have the model rewrite the follow-up as a standalone question before searching.
- **Known miss:** `late-7pm` ("picked up at 7pm on a Tuesday") never retrieves the weekday-hours chunk,
  though the answer is still right.

### Average rank can mislead
- With split search off the average rank of the fact looks better (1.42 -> 1.21) only because the facts it
  failed to find at all are left out of the average. Report hit rate and top-ranked rate beside it, never alone.

### Compare embedding models
- `embeddinggemma` against `nomic-embed-text` (and a hosted embedding model) on the same question sets.
  A clean one-variable experiment.

## Answers and sources

### Sources line thresholds
- `SOURCE_WINDOW` and `SOURCE_MIN_SHARED` were tuned on the 67-question set: about 94% exact there, 77% on
  the held-out set. Over-fit.
- **Plan:** show the retrieved passages instead (step 2) and stop tuning the thresholds. If a "primary
  source" is still wanted, choose it by a simple rule that I can explain.

### False-premise and partial answers (fixed, with a caveat)
- "Why are you closed on Sundays?" got a correct answer that opens with "I don't know.", so no source was shown.
  Fixed: an opener followed by a sentence with a figure (number, time, price) is treated as a partial answer.
- **Caveat:** the figure test is a rough rule, written after looking at saved answers and checked on the same
  answers. An answer with no digits (for example "I don't know the weight. Rabies shots are valid for several
  years.") would still be treated as a refusal. A sturdier way would be asking the model for a structured
  reply (answer, plus which passages it used) instead of guessing from its wording.

### Which passage did the answer use?
- The page lists every passage the model read; it cannot say which one(s) the answer came from. A strong/weak
  badge from the distance score was tried and dropped (not reliable). **How:** have the model name the passages it
  used, or compare the answer's wording with each passage; measure against hand-marked answers.

### PDFs are cut page by page
- A fact that runs across a page break is split in two chunks. Fine for now; if it matters, chunk the whole PDF
  and map each chunk back to the pages it covers (a page range).

## Product and platform

### Document upload on the public demo
- **Skipped on purpose:** anyone could upload anything. It works locally (n8n form plus the auto-indexing watcher).
- **Would need:** authentication, file type and size limits, per-user separation, malware scanning, and a delete path.

### Scanned PDFs and old Word files
- Scanned PDFs have no extractable text and `.doc` is unsupported. **How:** OCR for scans, a conversion step for `.doc`.

### Windows only, and PDF/Word chunking untested on real files
- Built and tested on Windows 11. Docker (step 5) fixes most of this; a PDF and a Word file in the demo set
  and the eval would close the rest.

### Chat memory
- Memory lives in the browser tab, so a refresh clears it. Fine for a demo; a real product would store
  conversations per user.

### Vector store
- Chroma is enough at this size. **pgvector** only makes sense if the project needs a Postgres story
  (users, history, permissions) alongside the vectors.

### Observability
- Query logging is planned (step 3). Next: a small dashboard of questions, retrieval distances and
  "I don't know" rate, to spot gaps in the documents.

## Parked, not an "improvement"
- **FastAPI:** parked by choice. Do it before the public deploy because the built-in server handles one
  request at a time. README line: started with the standard library to learn the request cycle, moved to
  FastAPI for deployment.

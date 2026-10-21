# Fixed-size chunks vs heading-aware chunks (retrieval only)

Run on 2026-10-21 on the six daycare documents, 55 questions (47 of them have a retrieval check), no chat
model involved. The two commits share the same question file and the same eval script (the one from
`2eb80d8`); only the chunking differs.

| | Fixed chunks (`6e0b2de`) | Heading-aware chunks (`2eb80d8`) |
|---|---|---|
| Chunks in the index | 16 | 47 |
| Retrieval found the fact | 47/47 | 47/47 |
| Fact in the top-ranked chunk | 32/47 (68%) | 44/47 (94%) |
| Average rank of the fact | 1.43 | 1.09 |
| Characters sent to the model per question | 2,520 | 993 |

Raw output: `historical-fixed-chunks-6e0b2de.log` and `historical-heading-chunks-2eb80d8.log`.

How it was run: each commit checked out in its own folder with a copy of `docs/`, `python rag.py ingest`,
then `python run_eval.py --retrieval-only` using the `2eb80d8` version of `run_eval.py` in both.

Limits: retrieval only (the answer prompt also changed between these commits, and answers were not
re-measured here); one run each, which is enough because retrieval has no randomness; the numbers are not
comparable with the 59-check runs on the current 67-question file, where 12 multi-topic questions make the
average rank worse.

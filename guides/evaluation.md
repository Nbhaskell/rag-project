# Testing and evaluation

How the question sets and `run_eval.py` work. Results are summarised in the [README](../README.md#how-well-does-it-work).

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
that goes with the two files in `samples/`. `eval_questions_injection.json` has 9 questions that try to
make the model break its rules (ignore its instructions, reveal them, follow an order or a false claim
hidden in the question); run it with `--questions eval_questions_injection.json --repeat 5`. On the local
model it passes about 70% of them: it resists the obvious attacks but can follow a formatting order or an
injected claim, and prompt wording did not fix that (see [IMPROVE-NOTES.md](../IMPROVE-NOTES.md)). `eval_questions_pdf.json` has 9
questions about the demo PDF, with the page each fact is on (run it with `RAG_DOCS_DIR=demo_docs`). For your
own documents, write your own questions in the same format. Answers vary a little from run to run, so repeat a question several
times before trusting a single result.

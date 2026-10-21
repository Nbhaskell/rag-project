"""Runs the test questions in eval_questions.json against the RAG pipeline.

Run from the project folder with the venv active, after `python rag.py ingest`:
    python run_eval.py                    retrieval + answers (slow: uses the chat model)
    python run_eval.py --retrieval-only   retrieval checks only (fast: no chat model)
    python run_eval.py --id vacation      only the question(s) with these ids
    python run_eval.py --questions eval_questions_samples.json
                                          use a different question file (the default,
                                          eval_questions.json, is for the documents in docs/)
    python run_eval.py --label baseline --repeat 3
                                          name the run and repeat it 3 times (answers vary from run to run)
    python run_eval.py --compare baseline split-off
                                          side-by-side table of two saved runs (a label or a file path)

Each question is checked two ways:
  retrieval: did the chunks sent to the model contain the fact? (retrieval_contains)
  answer:    does the reply contain the expected words, and none of the forbidden ones?
Unanswerable questions pass if the reply says it doesn't know.

Every run is saved to eval_runs/<date>_<time>_<label>.json together with the settings it ran with
(models, chunk size, TOP_K, split search, thinking, git commit), so two runs can be compared later.
eval_runs/ is not in git except eval_runs/published/: copy a run there to share it. The latest run's
per-question details are also written to eval_results.json.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import rag

MODEL_ATTEMPTS = 3  # tries per question when a model call fails or times out

QUESTIONS_FILE = Path("eval_questions.json")
RESULTS_FILE = Path("eval_results.json")
RUNS_DIR = Path("eval_runs")
PUBLISHED_DIR = RUNS_DIR / "published"

# Settings from rag.py that are saved with every run.
SETTING_NAMES = ["CHAT_MODEL", "EMBED_MODEL", "CHUNK_SIZE", "OVERLAP", "TOP_K", "SUB_TOP_K", "MAX_PARTS",
                 "THINK", "SPLIT_QUESTIONS", "INDEX_VERSION", "SOURCE_WINDOW", "SOURCE_MIN_SHARED",
                 "SOURCE_MIN_SHARED_BEST"]

# Rows of the comparison table: (name, key of the count, key of the total).
COUNT_ROWS = [("questions passed", "questions_passed", "questions"),
              ("retrieval found the fact", "retrieval_ok", "retrieval_total"),
              ("fact in the top chunk", "top_ranked", "retrieval_total"),
              ("answers right", "answers_ok", "answers_total"),
              ("sources line exactly right", "sources_exact", "sources_total")]
# (name, key, decimals); for these the number itself is shown, not "n/total".
NUMBER_ROWS = [("average rank of the fact", "avg_rank", 2),
               ("extra files in sources line", "sources_extra", 1),
               ("needed files missing", "sources_missing", 1),
               ("characters sent per question", "avg_context_chars", 0),
               ("seconds per question", "avg_seconds", 1),
               ("slowest question (seconds)", "slowest_seconds", 1),
               ("questions with model errors", "model_errors", 1)]


def norm(text):
    return re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip()


def has(text, phrase):
    """Whole-word match, so '6' doesn't match '16' and '$8' doesn't match '$80'.
    A plural 's' and a trailing am/pm are allowed ('8:00' matches '8:00am')."""
    return re.search(r"(?<!\w)" + re.escape(norm(phrase)) + r"s?(?:\s?[ap]m)?(?!\w)", text) is not None


def retrieve(question):
    # The same search answer_stream does for a first question (no chat history), best match first.
    return [c["text"] for c in sorted(rag.retrieve(question), key=lambda c: c["distance"])]


def doc_texts():
    """Normalized text of each document in docs/, by file name (markdown and text files)."""
    return {key: norm(path.read_text(encoding="utf-8", errors="ignore"))
            for key, path in rag.list_docs().items() if path.suffix.lower() in {".md", ".txt"}}


def expected_sources(q, by_id, texts):
    """Files that should be listed under the answer: the files containing the expected fact,
    unless the question names them in "expected_sources". None when it can't be worked out."""
    if q.get("follow_up_to"):
        return expected_sources(by_id[q["follow_up_to"]], by_id, texts)
    if q["type"] == "unanswerable":
        return []
    if "expected_sources" in q:
        return q["expected_sources"]
    phrases = q.get("retrieval_contains")
    if phrases:
        phrases = [phrases] if isinstance(phrases, str) else phrases
        return sorted({name for name, text in texts.items() for p in phrases if norm(p) in text})
    return None


def acceptable_sources(q, by_id):
    """Files that may be listed without counting as noise because they also state the fact."""
    if q.get("follow_up_to"):
        return acceptable_sources(by_id[q["follow_up_to"]], by_id)
    return q.get("acceptable_sources", [])


def check_retrieval(q, chunks):
    """Returns (found, problems, rank). "retrieval_contains" is one phrase or a list of phrases that
    must all be retrieved; rank is the 1-based position of the worst-placed chunk that has one."""
    phrases = q.get("retrieval_contains")
    if phrases is None:
        return None, [], None
    if isinstance(phrases, str):
        phrases = [phrases]
    ranks, problems = [], []
    for phrase in phrases:
        wanted = norm(phrase)
        rank = next((i for i, c in enumerate(chunks, 1) if wanted in norm(c)), None)
        if rank is None:
            problems.append(f"retrieved chunks do not contain: {phrase!r}")
        else:
            ranks.append(rank)
    ok = not problems
    return ok, problems, (max(ranks) if ok else None)


def check_answer(q, answer):
    text = norm(answer)
    problems = []
    if q["type"] == "unanswerable":
        if not rag.says_dont_know(answer):
            problems.append("should have said it doesn't know")
    for alternatives in q.get("answer_contains", []):
        if not any(has(text, a) for a in alternatives):
            problems.append("answer is missing one of: " + " / ".join(alternatives))
    for bad in q.get("answer_not_contains", []):
        if has(text, bad):
            problems.append(f"answer should not contain: {bad}")
    return not problems, problems


def passed(r):
    return not r.get("model_error") and r["retrieval"] is not False and r["answer_ok"] is not False


def evaluate(q, by_id, texts, retrieval_only, histories):
    """Asks one question and checks the result. Raises if a model call fails or times out."""
    r = {"id": q["id"], "type": q["type"], "question": q["question"],
         "retrieval": None, "answer_ok": None, "answer": None, "problems": []}

    if q.get("follow_up_to"):
        if retrieval_only:
            r["skipped"] = True  # follow-ups need the chat model's earlier answer
            return r
    else:
        chunks = retrieve(q["question"])
        ok, problems, rank = check_retrieval(q, chunks)
        r["retrieval"], r["retrieval_rank"] = ok, rank
        r["context_chars"] = sum(len(c) for c in chunks)
        r["problems"] += problems

    if not retrieval_only:
        history = histories.get(q.get("follow_up_to"), [])
        chunks_used, pieces = rag.answer_stream(q["question"], history)
        answer = "".join(pieces).strip()
        shown = rag.sources_to_show(answer, chunks_used)
        wanted_files = expected_sources(q, by_id, texts)
        r["answer"], r["sources_shown"], r["sources_expected"] = answer, shown, wanted_files
        if wanted_files is not None:
            ok_too = set(wanted_files) | set(acceptable_sources(q, by_id))
            r["sources_extra"] = sorted(set(shown) - ok_too)
            r["sources_missing"] = sorted(set(wanted_files) - set(shown))
        r["answer_ok"], problems = check_answer(q, answer)
        r["problems"] += problems
        histories[q["id"]] = history + [{"role": "user", "content": q["question"]},
                                        {"role": "assistant", "content": answer}]
    return r


def run_once(questions, by_id, texts, retrieval_only):
    """Runs every question once, printing one line each. Returns the list of per-question results.

    A question whose model call fails or times out (rag.MODEL_TIMEOUT) is tried again, up to
    MODEL_ATTEMPTS times; if it never works it is recorded as a "model_error", which counts as a
    failure but is kept apart from wrong answers.
    """
    results, histories = [], {}
    for q in questions:
        start = time.time()
        r = None
        for attempt in range(1, MODEL_ATTEMPTS + 1):
            try:
                r = evaluate(q, by_id, texts, retrieval_only, histories)
                break
            except Exception as error:  # a timeout, a dropped connection, Ollama restarting
                print(f"[RETRY] {q['id']}: {type(error).__name__}: {error} (attempt {attempt} of {MODEL_ATTEMPTS})")
                last_error = f"{type(error).__name__}: {error}"
        if r is None:
            r = {"id": q["id"], "type": q["type"], "question": q["question"], "retrieval": None,
                 "answer_ok": None, "answer": None, "model_error": last_error,
                 "problems": [f"model call failed {MODEL_ATTEMPTS} times ({last_error})"]}
        elif r.get("skipped"):
            results.append(r)
            print(f"[SKIP] {q['id']}")
            continue

        r["seconds"] = round(time.time() - start, 1)  # includes any failed attempts
        # A question with a "known_issue" note is still run and reported, but does not fail the run.
        r["known_issue"] = q.get("known_issue") if not passed(r) else None
        tag = "PASS" if passed(r) else ("KNOWN" if r["known_issue"] else "FAIL")
        label = lambda v: "n/a" if v is None else ("ok" if v else "FAIL")
        print(f"[{tag}] {q['id']:<22} "
              f"retrieval {label(r['retrieval']):<4} answer {label(r['answer_ok']):<4} ({r['seconds']}s)")
        for p in r["problems"]:
            print(f"         - {p}")
        if not passed(r) and r["answer"]:
            print(f"         answer was: {r['answer'][:200]!r}")
        results.append(r)
    return results


def summarize(results):
    """The numbers for one pass over the questions."""
    ran = [r for r in results if not r.get("skipped")]
    by_type = defaultdict(lambda: [0, 0])
    for r in ran:
        by_type[r["type"]][1] += 1
        by_type[r["type"]][0] += passed(r)
    retrieval = [r["retrieval"] for r in ran if r["retrieval"] is not None]
    answers = [r["answer_ok"] for r in ran if r["answer_ok"] is not None]
    ranks = [r["retrieval_rank"] for r in ran if r.get("retrieval_rank")]
    sizes = [r["context_chars"] for r in ran if r.get("context_chars")]
    graded = [r for r in ran if "sources_extra" in r]
    return {
        "questions": len(ran),
        "questions_passed": sum(passed(r) for r in ran),
        "by_type": dict(by_type),
        "retrieval_total": len(retrieval), "retrieval_ok": sum(retrieval),
        "top_ranked": sum(x == 1 for x in ranks),
        "avg_rank": round(sum(ranks) / len(ranks), 2) if ranks else None,
        "avg_context_chars": sum(sizes) // len(sizes) if sizes else None,
        "answers_total": len(answers), "answers_ok": sum(answers),
        "sources_total": len(graded),
        "sources_exact": sum(not r["sources_extra"] and not r["sources_missing"] for r in graded),
        "sources_extra": sum(len(r["sources_extra"]) for r in graded),
        "sources_missing": sum(len(r["sources_missing"]) for r in graded),
        "avg_seconds": round(sum(r["seconds"] for r in ran) / len(ran), 1) if ran else None,
        "slowest_seconds": max((r["seconds"] for r in ran), default=None),
        "model_errors": sum(bool(r.get("model_error")) for r in ran),
    }


def print_summary(s, results):
    print("\nSummary")
    for kind, (good, total) in s["by_type"].items():
        print(f"  {kind:<13} {good}/{total} passed")
    print(f"  retrieval checks: {s['retrieval_ok']}/{s['retrieval_total']}")
    if s["avg_rank"] is not None:
        print(f"    fact in the top-ranked chunk: {s['top_ranked']}/{s['retrieval_total']}, "
              f"average rank {s['avg_rank']:.2f}")
    if s["avg_context_chars"] is not None:
        print(f"    text sent to the model per question: {s['avg_context_chars']} characters on average")
    if s["answers_total"]:
        print(f"  answer checks:    {s['answers_ok']}/{s['answers_total']}")
    if s["sources_total"]:
        print(f"  sources line:     {s['sources_exact']}/{s['sources_total']} exactly right; "
              f"{s['sources_extra']} extra files listed, {s['sources_missing']} needed files missing")
    print(f"  slowest question: {s['slowest_seconds']}s")
    if s["model_errors"]:
        print(f"  MODEL ERRORS:     {s['model_errors']} question(s) never got an answer from the model "
              "(counted as failed; not the same as a wrong answer)")
    for r in results:
        if r.get("known_issue"):
            print(f"  known issue: {r['id']}: {r['known_issue']}")


def git_commit():
    """The short commit hash, with "+uncommitted" if the working tree has changes (None outside git)."""
    try:
        git = lambda *a: subprocess.run(["git", *a], capture_output=True, text=True, check=True).stdout.strip()
        return git("rev-parse", "--short", "HEAD") + ("+uncommitted" if git("status", "--porcelain") else "")
    except Exception:
        return None


def clean_label(text):
    return re.sub(r"[^A-Za-z0-9-]+", "-", text).strip("-") or "run"


# ---------- comparing saved runs ----------

def find_run(ref):
    """A saved run from a file path or a label (the newest run with that label)."""
    path = Path(ref)
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8")), path
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{6}_(.+)\.json$")
    matches = sorted((p for folder in (RUNS_DIR, PUBLISHED_DIR) if folder.is_dir() for p in folder.glob("*.json")
                      if (m := pattern.match(p.name)) and m.group(1) == ref), key=lambda p: p.name)
    if not matches:
        sys.exit(f"No saved run called {ref!r} in {RUNS_DIR}/ or {PUBLISHED_DIR}/ (and it is not a file path).")
    return json.loads(matches[-1].read_text(encoding="utf-8")), matches[-1]


def mean(values):
    return sum(values) / len(values)


def run_mean(run, key):
    values = [rep["summary"][key] for rep in run["repeats"] if rep["summary"].get(key) is not None]
    return mean(values) if values else None


def fmt(x, decimals=1, trim=True):
    """A number with up to `decimals` decimals; trim drops trailing zeros (59.0 -> 59)."""
    if x is None:
        return "n/a"
    text = f"{x:.{decimals}f}"
    return text.rstrip("0").rstrip(".") if trim and decimals > 0 else text


def pass_rates(run):
    """Question id -> (passes, repeats it ran in)."""
    rates = defaultdict(lambda: [0, 0])
    for rep in run["repeats"]:
        for r in rep["results"]:
            if not r.get("skipped"):
                rates[r["id"]][1] += 1
                rates[r["id"]][0] += passed(r)
    return rates


def compare(ref_a, ref_b):
    a, path_a = find_run(ref_a)
    b, path_b = find_run(ref_b)
    name_a, name_b = a["label"], b["label"]
    print(f"A = {path_a}  ({len(a['repeats'])} repeat(s), commit {a.get('git')})")
    print(f"B = {path_b}  ({len(b['repeats'])} repeat(s), commit {b.get('git')})\n")

    if a["questions_file"] != b["questions_file"]:
        print(f"WARNING: different question files ({a['questions_file']} vs {b['questions_file']}); "
              "the numbers are not directly comparable.\n")
    differences = [(k, a["settings"].get(k), b["settings"].get(k))
                   for k in sorted(set(a["settings"]) | set(b["settings"]))
                   if a["settings"].get(k) != b["settings"].get(k)]
    print("Settings that differ:" if differences else "Settings that differ: none")
    for key, x, y in differences:
        print(f"  {key}: {x} -> {y}")
    print()

    multi = len(a["repeats"]) > 1 or len(b["repeats"]) > 1
    note = "means over the repeats" if multi else "single run"
    print(f"{'':<30}{name_a[:16]:>17}{name_b[:16]:>17}{'change':>10}   ({note})")
    for title, count_key, total_key in COUNT_ROWS:
        ma, mb = run_mean(a, count_key), run_mean(b, count_key)
        ta, tb = run_mean(a, total_key), run_mean(b, total_key)
        if ma is None or mb is None or not ta or not tb:
            continue
        print(f"{title:<30}{fmt(ma) + '/' + fmt(ta):>17}{fmt(mb) + '/' + fmt(tb):>17}{mb - ma:>+10.1f}")
    for title, key, decimals in NUMBER_ROWS:
        ma, mb = run_mean(a, key), run_mean(b, key)
        if ma is None or mb is None:
            continue
        print(f"{title:<30}{fmt(ma, decimals, trim=False):>17}{fmt(mb, decimals, trim=False):>17}{mb - ma:>+10.{max(decimals, 1)}f}")

    rates_a, rates_b = pass_rates(a), pass_rates(b)
    changed = []
    for qid in rates_a:
        if qid in rates_b:
            (pa, na), (pb, nb) = rates_a[qid], rates_b[qid]
            if pa / na != pb / nb:
                changed.append((qid, f"{pa}/{na}", f"{pb}/{nb}", pb / nb - pa / na))
    print("\nQuestions whose pass rate changed:" if changed else "\nQuestions whose pass rate changed: none")
    for qid, ra, rb, delta in sorted(changed, key=lambda c: c[3]):
        print(f"  {qid:<28}{ra:>6} -> {rb:<6} ({'better' if delta > 0 else 'worse'})")
    only = (set(rates_a) ^ set(rates_b))
    if only:
        print(f"\n{len(only)} question(s) appear in only one run and were not compared.")


# ---------- running ----------

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--id", nargs="+", help="run only these question ids")
    parser.add_argument("--questions", default=str(QUESTIONS_FILE), help="question file to use")
    parser.add_argument("--label", default="run", help="name for this run, used in the saved file's name")
    parser.add_argument("--repeat", type=int, default=1, help="how many times to run all the questions")
    parser.add_argument("--compare", nargs=2, metavar=("A", "B"),
                        help="compare two saved runs (labels or file paths) instead of running")
    args = parser.parse_args()

    if args.compare:
        compare(*args.compare)
        return
    if args.repeat < 1:
        sys.exit("--repeat must be at least 1.")

    questions = json.loads(Path(args.questions).read_text(encoding="utf-8"))
    by_id, texts = {q["id"]: q for q in questions}, doc_texts()
    if args.id:
        wanted = set(args.id)
        unknown = wanted - {q["id"] for q in questions}
        if unknown:
            sys.exit(f"Unknown question id(s): {', '.join(sorted(unknown))}")
        for q in questions:  # a follow-up needs the question before it
            if q["id"] in wanted and q.get("follow_up_to"):
                wanted.add(q["follow_up_to"])
        questions = [q for q in questions if q["id"] in wanted]

    try:
        rag.client.get_collection("docs")
    except Exception:
        sys.exit("No database found. Run `python rag.py ingest` first.")

    repeats = []
    for number in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n=== Repeat {number} of {args.repeat} ===")
        results = run_once(questions, by_id, texts, args.retrieval_only)
        summary = summarize(results)
        print_summary(summary, results)
        repeats.append({"summary": summary, "results": results})

    if args.repeat > 1:
        # Questions that did not give the same verdict every time (the reason for repeating).
        mixed = []
        for qid, (good, total) in pass_rates({"repeats": repeats}).items():
            if 0 < good < total:
                mixed.append(f"{qid} ({good}/{total})")
        print("\nPassed in some repeats but not all: " + (", ".join(mixed) if mixed else "none"))

    label = clean_label(args.label)
    run = {"label": label, "created": datetime.now().isoformat(timespec="seconds"), "git": git_commit(),
           "questions_file": args.questions, "retrieval_only": args.retrieval_only,
           "question_ids": args.id, "settings": {k: getattr(rag, k, None) for k in SETTING_NAMES},
           "repeats": repeats}
    RUNS_DIR.mkdir(exist_ok=True)
    run_file = RUNS_DIR / f"{datetime.now():%Y-%m-%d_%H%M%S}_{label}.json"
    run_file.write_text(json.dumps(run, indent=2), encoding="utf-8")
    RESULTS_FILE.write_text(json.dumps(repeats[-1]["results"], indent=2), encoding="utf-8")
    print(f"\nRun saved to {run_file} (latest details also in {RESULTS_FILE})")
    clean = all(not r["problems"] or r.get("known_issue") for rep in repeats for r in rep["results"])
    sys.exit(0 if clean else 1)


if __name__ == "__main__":
    main()

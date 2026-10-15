"""Runs the test questions in eval_questions.json against the RAG pipeline.

Run from the project folder with the venv active, after `python rag.py ingest`:
    python run_eval.py                    retrieval + answers (slow: uses the chat model)
    python run_eval.py --retrieval-only   retrieval checks only (fast: no chat model)
    python run_eval.py --id vacation      only the question(s) with these ids

Each question is checked two ways:
  retrieval: did the chunks sent to the model contain the fact? (retrieval_contains)
  answer:    does the reply contain the expected words, and none of the forbidden ones?
Unanswerable questions pass if the reply says it doesn't know.
Results are also saved to eval_results.json.
"""
import argparse
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import rag

QUESTIONS_FILE = Path("eval_questions.json")
RESULTS_FILE = Path("eval_results.json")


def norm(text):
    return re.sub(r"\s+", " ", text.lower().replace("’", "'")).strip()


def has(text, phrase):
    """Whole-word match (plural 's' allowed), so '6' doesn't match '16' and '$8' doesn't match '$80'."""
    return re.search(r"(?<!\w)" + re.escape(norm(phrase)) + r"s?(?!\w)", text) is not None


def retrieve(question):
    # Same search answer_stream does for a first question (no chat history).
    collection = rag.client.get_collection("docs")
    results = collection.query(query_embeddings=rag.embed([question]), n_results=rag.TOP_K)
    return results["documents"][0]


def check_retrieval(q, chunks):
    phrase = q.get("retrieval_contains")
    if phrase is None:
        return None, []
    ok = any(norm(phrase) in norm(c) for c in chunks)
    return ok, [] if ok else [f"retrieved chunks do not contain: {phrase!r}"]


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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--id", nargs="+", help="run only these question ids")
    args = parser.parse_args()

    questions = json.loads(QUESTIONS_FILE.read_text(encoding="utf-8"))
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

    results, histories = [], {}
    for q in questions:
        start = time.time()
        r = {"id": q["id"], "type": q["type"], "question": q["question"],
             "retrieval": None, "answer_ok": None, "answer": None, "problems": []}

        if q.get("follow_up_to"):
            if args.retrieval_only:
                r["skipped"] = True  # follow-ups need the chat model's earlier answer
                results.append(r)
                print(f"[SKIP] {q['id']}")
                continue
        else:
            ok, problems = check_retrieval(q, retrieve(q["question"]))
            r["retrieval"] = ok
            r["problems"] += problems

        if not args.retrieval_only:
            history = histories.get(q.get("follow_up_to"), [])
            sources, pieces = rag.answer_stream(q["question"], history)
            answer = "".join(pieces).strip()
            r["answer"], r["sources"] = answer, sources
            r["answer_ok"], problems = check_answer(q, answer)
            r["problems"] += problems
            histories[q["id"]] = history + [{"role": "user", "content": q["question"]},
                                            {"role": "assistant", "content": answer}]

        r["seconds"] = round(time.time() - start, 1)
        passed = r["retrieval"] is not False and r["answer_ok"] is not False
        label = lambda v: "n/a" if v is None else ("ok" if v else "FAIL")
        print(f"[{'PASS' if passed else 'FAIL'}] {q['id']:<22} "
              f"retrieval {label(r['retrieval']):<4} answer {label(r['answer_ok']):<4} ({r['seconds']}s)")
        for p in r["problems"]:
            print(f"         - {p}")
        if not passed and r["answer"]:
            print(f"         answer was: {r['answer'][:200]!r}")
        results.append(r)

    print("\nSummary")
    by_type = defaultdict(lambda: [0, 0])
    for r in results:
        if r.get("skipped"):
            continue
        by_type[r["type"]][1] += 1
        by_type[r["type"]][0] += r["retrieval"] is not False and r["answer_ok"] is not False
    for kind, (good, total) in by_type.items():
        print(f"  {kind:<13} {good}/{total} passed")
    retrieval = [r["retrieval"] for r in results if r["retrieval"] is not None]
    answers = [r["answer_ok"] for r in results if r["answer_ok"] is not None]
    print(f"  retrieval checks: {sum(retrieval)}/{len(retrieval)}")
    if answers:
        print(f"  answer checks:    {sum(answers)}/{len(answers)}")

    RESULTS_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nDetails saved to {RESULTS_FILE}")
    sys.exit(0 if all(not r["problems"] for r in results) else 1)


if __name__ == "__main__":
    main()

"""Runs the test questions in eval_questions.json against the RAG pipeline.

Run from the project folder with the venv active, after `python rag.py ingest`:
    python run_eval.py                    retrieval + answers (slow: uses the chat model)
    python run_eval.py --retrieval-only   retrieval checks only (fast: no chat model)
    python run_eval.py --id vacation      only the question(s) with these ids
    python run_eval.py --questions eval_questions_samples.json
                                          use a different question file (the default,
                                          eval_questions.json, is for the documents in docs/)

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
    """Whole-word match, so '6' doesn't match '16' and '$8' doesn't match '$80'.
    A plural 's' and a trailing am/pm are allowed ('8:00' matches '8:00am')."""
    return re.search(r"(?<!\w)" + re.escape(norm(phrase)) + r"s?(?:\s?[ap]m)?(?!\w)", text) is not None


def retrieve(question):
    # Same search answer_stream does for a first question (no chat history).
    collection = rag.client.get_collection("docs")
    results = collection.query(query_embeddings=rag.embed([question]), n_results=rag.TOP_K)
    return results["documents"][0]


def doc_texts():
    """Normalized text of each document in docs/, by file name (markdown and text files)."""
    return {p.name: norm(p.read_text(encoding="utf-8", errors="ignore"))
            for p in rag.DOCS_DIR.rglob("*") if p.suffix.lower() in {".md", ".txt"}}


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


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--id", nargs="+", help="run only these question ids")
    parser.add_argument("--questions", default=str(QUESTIONS_FILE), help="question file to use")
    args = parser.parse_args()

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
            chunks = retrieve(q["question"])
            ok, problems, rank = check_retrieval(q, chunks)
            r["retrieval"], r["retrieval_rank"] = ok, rank
            r["context_chars"] = sum(len(c) for c in chunks)
            r["problems"] += problems

        if not args.retrieval_only:
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

        r["seconds"] = round(time.time() - start, 1)
        passed = r["retrieval"] is not False and r["answer_ok"] is not False
        # A question with a "known_issue" note is still run and reported, but does not fail the run.
        r["known_issue"] = q.get("known_issue") if not passed else None
        tag = "PASS" if passed else ("KNOWN" if r["known_issue"] else "FAIL")
        label = lambda v: "n/a" if v is None else ("ok" if v else "FAIL")
        print(f"[{tag}] {q['id']:<22} "
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
    ranks = [r["retrieval_rank"] for r in results if r.get("retrieval_rank")]
    if ranks:
        print(f"    fact in the top-ranked chunk: {sum(x == 1 for x in ranks)}/{len(retrieval)}, "
              f"average rank {sum(ranks) / len(ranks):.2f}")
    sizes = [r["context_chars"] for r in results if r.get("context_chars")]
    if sizes:
        print(f"    text sent to the model per question: {sum(sizes) // len(sizes)} characters on average")
    if answers:
        print(f"  answer checks:    {sum(answers)}/{len(answers)}")
    graded = [r for r in results if "sources_extra" in r]
    if graded:
        exact = sum(not r["sources_extra"] and not r["sources_missing"] for r in graded)
        print(f"  sources line:     {exact}/{len(graded)} exactly right; "
              f"{sum(len(r['sources_extra']) for r in graded)} extra files listed, "
              f"{sum(len(r['sources_missing']) for r in graded)} needed files missing")

    for r in results:
        if r.get("known_issue"):
            print(f"  known issue: {r['id']}: {r['known_issue']}")

    RESULTS_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nDetails saved to {RESULTS_FILE}")
    sys.exit(0 if all(not r["problems"] or r.get("known_issue") for r in results) else 1)


if __name__ == "__main__":
    main()

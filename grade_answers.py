"""Checks the automatic answer grader in run_eval.py against hand grading.

run_eval.py decides whether an answer is right by looking for expected words. This script measures how
often that agrees with a person reading the same answers:

    python grade_answers.py sample baseline            pick 20 answers from a saved run and write a grading
                                                       sheet, eval_runs/grading_baseline.md
    (open the sheet and fill in "Verdict" under each answer: ok or wrong)
    python grade_answers.py score eval_runs/grading_baseline.md
                                                       how often the word matcher agreed with you

The sheet does not show the matcher's verdicts (they are in a separate .key.json file), so the
grading is blind. Options for `sample`: --count N (default 20), --seed N (default 1).
"""
import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from run_eval import RUNS_DIR, find_run


def sample(args):
    run, run_path = find_run(args.run)
    questions = {q["id"]: q for q in json.loads(Path(run["questions_file"]).read_text(encoding="utf-8"))}
    # The first repeat only: later repeats are the same questions answered again.
    answered = [r for r in run["repeats"][0]["results"] if r.get("answer") and r["answer_ok"] is not None]
    if not answered:
        sys.exit("That run has no answers (was it a --retrieval-only run?).")

    # Spread the sample over the question types, in a fixed random order so --seed reproduces it.
    rng = random.Random(args.seed)
    by_type = defaultdict(list)
    for r in answered:
        by_type[r["type"]].append(r)
    for group in by_type.values():
        rng.shuffle(group)
    chosen = []
    while len(chosen) < min(args.count, len(answered)):
        for kind in sorted(by_type):
            if by_type[kind] and len(chosen) < args.count:
                chosen.append(by_type[kind].pop())
    rng.shuffle(chosen)

    lines = [f"# Grading sheet for run `{run_path.name}`", "",
             "Under each answer, fill in `Verdict` with `ok` (correct and complete according to the "
             "documents) or `wrong`. Add a note if you like. Don't look at run_eval.py's verdicts first.", ""]
    key = {"run": str(run_path), "items": {}}
    for number, r in enumerate(chosen, 1):
        q = questions[r["id"]]
        facts = q.get("retrieval_contains")
        if r["type"] == "unanswerable":
            reference = "The documents do not cover this, so the right answer is that it doesn't know."
        elif facts:
            facts = [facts] if isinstance(facts, str) else facts
            reference = "The documents say: " + " | ".join(facts)
        else:
            reference = "Check the answer against the documents."
        quoted = "\n".join("> " + line for line in r["answer"].splitlines())
        lines += [f"## {number}. {r['id']} ({r['type']})", "", f"Question: {r['question']}", "",
                  f"Reference: {reference}", "", "Answer:", quoted, "", "Verdict (ok / wrong): ", "Note: ", ""]
        key["items"][str(number)] = {"id": r["id"], "matcher_ok": r["answer_ok"]}

    out = RUNS_DIR / f"grading_{run['label']}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    out.with_suffix(".key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    print(f"Wrote {len(chosen)} answers to {out}. Fill in the Verdict lines, then run:\n"
          f"    python grade_answers.py score {out}")


def score(args):
    sheet = Path(args.sheet)
    key = json.loads(sheet.with_suffix(".key.json").read_text(encoding="utf-8"))["items"]
    text = sheet.read_text(encoding="utf-8")
    sections = re.split(r"^## (\d+)\. ", text, flags=re.M)[1:]  # number, body, number, body, ...
    graded, skipped = [], 0
    for number, body in zip(sections[::2], sections[1::2]):
        verdict = re.search(r"^Verdict[^:\n]*:[ \t]*(.*)$", body, flags=re.M)
        said = verdict.group(1).strip().lower() if verdict else ""
        note = re.search(r"^Note:[ \t]*(.*)$", body, flags=re.M)
        if said in {"ok", "right", "correct", "y", "yes"}:
            human = True
        elif said in {"wrong", "no", "n", "incorrect"}:
            human = False
        else:
            skipped += 1
            continue
        graded.append((key[number]["id"], key[number]["matcher_ok"], human, note.group(1).strip() if note else ""))

    if not graded:
        sys.exit("No verdicts filled in yet.")
    agree = sum(m == h for _, m, h, _ in graded)
    print(f"The word matcher agreed with your grading on {agree} of {len(graded)} answers"
          f"{f' ({skipped} left blank)' if skipped else ''}.")
    for title, matcher, human in (("Matcher said right, you said wrong (missed errors)", True, False),
                                  ("Matcher said wrong, you said right (false alarms)", False, True)):
        rows = [(i, n) for i, m, h, n in graded if m == matcher and h == human]
        print(f"  {title}: {len(rows)}")
        for i, n in rows:
            print(f"    - {i}{': ' + n if n else ''}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sample", help="write a grading sheet from a saved run")
    p.add_argument("run", help="a run label or file path")
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--seed", type=int, default=1)
    p.set_defaults(func=sample)
    p = sub.add_parser("score", help="compare your verdicts with the word matcher's")
    p.add_argument("sheet", help="the filled-in grading sheet")
    p.set_defaults(func=score)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

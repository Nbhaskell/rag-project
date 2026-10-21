"""Checks the automatic answer grader in run_eval.py against hand grading.

run_eval.py decides whether an answer is right by looking for expected words. This script measures how
often that agrees with a person reading the same answers:

    python grade_answers.py sample baseline            pick 20 answers from a saved run and write a grading
                                                       sheet, eval_runs/grading_baseline.md
    (open the sheet and fill in "Verdict" under each answer: ok or wrong)
    python grade_answers.py score eval_runs/grading_baseline.md
                                                       how often the word matcher agreed with you

The sheet does not show the matcher's verdicts (they are in a separate .key.json file), so the
grading is blind.

If every sampled answer passes, the check only shows the matcher never calls a wrong answer right. To
test the other direction too, include answers the matcher failed:

    python grade_answers.py sample baseline split-off --failures 10
                                                       10 answers the matcher marked wrong (from any
                                                       repeat of any of the runs) and 10 it marked right

Options for `sample`: --count N (default 20), --failures N (default 0), --seed N (default 1),
--name NAME (the sheet's file name, without .md). Each question appears at most once in a sheet.
An existing sheet is never overwritten.
"""
import argparse
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

from run_eval import RUNS_DIR, find_run


def reference_text(question, kind):
    if kind == "unanswerable":
        return "The documents do not cover this, so the right answer is that it doesn't know."
    facts = question.get("retrieval_contains")
    if facts:
        facts = [facts] if isinstance(facts, str) else facts
        return "The documents say: " + " | ".join(facts)
    return "Check the answer against the documents."


def pick_spread(items, count, rng):
    """Up to `count` items taking turns across the question types, at most one per question."""
    by_type = defaultdict(list)
    for item in items:
        by_type[item["result"]["type"]].append(item)
    for group in by_type.values():
        rng.shuffle(group)
    chosen, seen = [], set()
    while len(chosen) < count and any(by_type.values()):
        for kind in sorted(by_type):
            while by_type[kind] and len(chosen) < count:
                item = by_type[kind].pop()
                if item["uid"] not in seen:
                    seen.add(item["uid"])
                    chosen.append(item)
                    break
    return chosen


def sample(args):
    pool = []  # every answered question in every repeat of every run given
    for ref in args.run:
        run, run_path = find_run(ref)
        questions = {q["id"]: q for q in json.loads(Path(run["questions_file"]).read_text(encoding="utf-8"))}
        for number, repeat in enumerate(run["repeats"], 1):
            for r in repeat["results"]:
                if r.get("answer") and r["answer_ok"] is not None:
                    pool.append({"run": run, "path": run_path, "repeat": number, "result": r,
                                 "question": questions[r["id"]], "uid": (run["questions_file"], r["id"])})
    if not pool:
        sys.exit("Those runs have no answers (were they --retrieval-only runs?).")

    rng = random.Random(args.seed)
    failing = [i for i in pool if i["result"]["answer_ok"] is False]
    passing = [i for i in pool if i["result"]["answer_ok"] is True]
    rng.shuffle(failing)
    chosen, seen = [], set()
    for item in failing:  # the matcher's failures first, one per question
        if len(chosen) < args.failures and item["uid"] not in seen:
            seen.add(item["uid"])
            chosen.append(item)
    if len(chosen) < args.failures:
        print(f"Only {len(chosen)} different questions have a failed answer in these runs "
              f"(asked for {args.failures}).")
    rest = [i for i in passing if i["uid"] not in seen]
    chosen += pick_spread(rest, args.count - len(chosen), rng)
    rng.shuffle(chosen)

    labels = ", ".join(sorted({i["run"]["label"] for i in chosen}))
    name = args.name or (f"grading_{args.run[0]}" + ("-with-failures" if args.failures else ""))
    out = RUNS_DIR / f"{name}.md"
    if out.exists():
        sys.exit(f"{out} already exists and is not overwritten (it may hold your grading). "
                 "Pick another name with --name.")

    lines = [f"# Grading sheet ({labels})", "",
             "Under each answer, fill in `Verdict` with `ok` (correct and complete according to the "
             "documents) or `wrong`. Add a note if you like. Don't look at run_eval.py's verdicts first.", ""]
    key = {"runs": sorted({str(i["path"]) for i in chosen}), "items": {}}
    for number, item in enumerate(chosen, 1):
        r, q = item["result"], item["question"]
        quoted = "\n".join("> " + line for line in r["answer"].splitlines())
        lines += [f"## {number}. {r['id']} ({r['type']})", "", f"Question: {r['question']}", "",
                  f"Reference: {reference_text(q, r['type'])}", "", "Answer:", quoted, "",
                  "Verdict (ok / wrong): ", "Note: ", ""]
        key["items"][str(number)] = {"id": r["id"], "matcher_ok": r["answer_ok"], "run": str(item["path"]),
                                     "repeat": item["repeat"]}

    out.write_text("\n".join(lines), encoding="utf-8")
    out.with_suffix(".key.json").write_text(json.dumps(key, indent=2), encoding="utf-8")
    wrong = sum(not i["result"]["answer_ok"] for i in chosen)
    print(f"Wrote {len(chosen)} answers to {out} ({wrong} the matcher marked wrong, "
          f"{len(chosen) - wrong} right; the sheet does not say which). Fill in the Verdict lines, then run:\n"
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
    for said_by_matcher, title in ((False, "marked wrong"), (True, "marked right")):
        group = [g for g in graded if g[1] == said_by_matcher]
        if group:
            same = sum(g[2] == said_by_matcher for g in group)
            print(f"  Of the {len(group)} answers the matcher {title}, you agreed on {same}.")
    for title, matcher, human in (("Matcher said right, you said wrong (missed errors)", True, False),
                                  ("Matcher said wrong, you said right (false alarms)", False, True)):
        rows = [(i, n) for i, m, h, n in graded if m == matcher and h == human]
        print(f"  {title}: {len(rows)}")
        for i, n in rows:
            print(f"    - {i}{': ' + n if n else ''}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("sample", help="write a grading sheet from one or more saved runs")
    p.add_argument("run", nargs="+", help="run labels or file paths")
    p.add_argument("--count", type=int, default=20)
    p.add_argument("--failures", type=int, default=0, help="how many answers the matcher failed to include")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--name", help="file name for the sheet (without .md)")
    p.set_defaults(func=sample)
    p = sub.add_parser("score", help="compare your verdicts with the word matcher's")
    p.add_argument("sheet", help="the filled-in grading sheet")
    p.set_defaults(func=score)
    args = parser.parse_args()
    if args.command == "sample" and not 0 <= args.failures <= args.count:
        sys.exit("--failures must be between 0 and --count.")
    args.func(args)


if __name__ == "__main__":
    main()

"""Tests for the recorded demo page (tools/capture_demo.py, tools/build_demo_page.py, site/).

Run from the project folder with the venv active:   python test_demo_page.py

No Ollama and no server: the page is built from the recording that is committed in site/recording.json.
These tests pin down what the page promises: it says it is a recording, it loads nothing from other sites,
recorded text can never run as code, and the committed page matches its recording.
"""
import datetime
import json
import re
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "tools"))

import build_demo_page  # noqa: E402
import capture_demo  # noqa: E402

RECORDING = json.loads((ROOT / "site" / "recording.json").read_text(encoding="utf-8"))
TEMPLATE = (ROOT / "tools" / "demo_template.html").read_text(encoding="utf-8")
PAGE = build_demo_page.build(RECORDING, TEMPLATE)


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def test_the_page_says_it_is_a_recording_before_anything_else():
    check("This is a recording, not a live system." in PAGE, "the banner must say it is a recording")
    check("There is no server behind this page" in PAGE, "it must say that nothing is live")
    check(PAGE.index("This is a recording") < PAGE.index('id="questions"'), "the banner must come before the questions")
    for fact in (RECORDING["system"]["chat_model"], RECORDING["system"]["embed_model"]):
        check(fact in PAGE, f"the page must name the model that was used: {fact}")


def test_the_page_loads_nothing_from_other_sites():
    check("<script src" not in PAGE and "<script  src" not in PAGE, "no external scripts")
    check('rel="stylesheet"' not in PAGE and "@import" not in PAGE, "no external stylesheets")
    check(not re.search(r"url\(\s*['\"]?https?:", PAGE), "no external images or fonts in the styles")
    check("<img" not in PAGE and "<iframe" not in PAGE, "no images or frames")
    check("fetch(" not in PAGE and "XMLHttpRequest" not in PAGE and "sendBeacon" not in PAGE, "the page makes no requests")
    icon = re.search(r'<link rel="icon" href="([^"]+)"', PAGE)
    check(icon and icon.group(1).startswith("data:"), "the icon must be embedded, not fetched")
    check("localStorage" not in PAGE and "document.cookie" not in PAGE, "no cookies or stored data")


def test_recorded_text_is_never_inserted_as_html():
    script = PAGE[PAGE.rindex("<script>"):]
    check("insertAdjacentHTML" not in script and "document.write" not in script and "eval(" not in script,
          "no way to turn text into code")
    uses = [m.start() for m in re.finditer("innerHTML", script)]
    check(len(uses) == 1 and 'log.innerHTML = ""' in script, "innerHTML may only be used to empty the conversation")
    check("textContent" in script and "createTextNode" in script, "recorded text must go in as plain text")


def test_recorded_text_cannot_close_the_script_tag_or_start_a_comment():
    hostile = "</script><script>alert('x')</script><!-- --> <b>bold</b>"
    recording = json.loads(json.dumps(RECORDING))
    recording["items"][0]["answer"] = hostile
    recording["items"][0]["passages"][0]["text"] = hostile
    page = build_demo_page.build(recording, TEMPLATE)
    check(page.count("</script>") == page.count("<script"), "recorded text must not add or close script tags")
    block = page[page.index('<script id="recording" type="application/json">') + len('<script id="recording" type="application/json">'):]
    block = block[:block.index("</script>")]
    check("<" not in block, "no raw < may appear inside the embedded data")
    check(json.loads(block)["items"][0]["answer"] == hostile, "the data must come back exactly as recorded")


def test_the_recording_has_every_question_with_what_the_page_needs():
    ids = [q[0] for q in capture_demo.QUESTIONS]
    check([item["id"] for item in RECORDING["items"]] == ids, "the recording must hold the questions in order")
    for item, (qid, group, question, why) in zip(RECORDING["items"], capture_demo.QUESTIONS):
        check((item["group"], item["question"], item["why"]) == (group, question, why),
              f"{qid}: the captions in the recording are out of date (run capture_demo.py --refresh-text)")
        check(item["answer"].strip() and isinstance(item["sources"], list) and item["passages"], f"{qid} is incomplete")
        for passage in item["passages"]:
            check({"source", "section", "page", "text", "distance", "best", "listed"} <= set(passage), f"{qid}: passage fields")
    datetime.datetime.fromisoformat(RECORDING["recorded_at"])
    system = RECORDING["system"]
    check(system["chat_model"] and system["embed_model"] and len(system["documents"]) >= 7, "the system facts must be recorded")


def test_the_examples_show_what_their_group_claims():
    by_id = {item["id"]: item for item in RECORDING["items"]}
    cats = by_id["cats"]
    check(cats["sources"] == [] and "know" in cats["answer"].lower(), "the 'does not know' example must be a refusal with no sources")
    for qid in ("pdf-two", "pdf-photo"):
        item = by_id[qid]
        check(any(s.endswith(".pdf") for s in item["sources"]) and any(p["page"] for p in item["passages"]),
              f"{qid} must cite a PDF with page numbers")
    check(any(item["group"] == "Where it goes wrong" for item in RECORDING["items"]), "one example must show a failure")


def test_the_committed_page_matches_its_recording_and_template():
    committed = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
    check(committed.replace("\r\n", "\n") == PAGE.replace("\r\n", "\n"),
          "site/index.html is out of date: run python tools/build_demo_page.py")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {test.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)

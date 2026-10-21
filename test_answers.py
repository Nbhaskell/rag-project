"""Tests for how an answer is judged and shown: gives_no_answer (is it a refusal?) and passages.

Run from the project folder with the venv active:   python test_answers.py

The example answers are real ones the model gave during the evals. No Ollama, no files.
"""
import sys
import traceback

import rag


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def test_plain_refusals_stay_refusals():
    for answer in [
        "I don't know.",
        "I don't know. The context does not mention an indoor play area for rainy days.",
        # an opener plus a description of what the documents do cover is still a refusal
        "I don't know. The context does not mention full grooming or haircuts specifically. "
        'It only lists "Nail trim" as an add-on service, but does not confirm or deny full grooming.',
        "No, the context does not mention offering a senior citizen discount. The available discounts "
        "are for multi-dog, military, rescue, or referral cases only.",
        # a number inside a "don't know" sentence does not make it an answer
        "I don't know. The Add-Ons section lists baths for $25 but does not mention grooming.",
    ]:
        check(rag.gives_no_answer(answer), f"should be a refusal: {answer!r}")


def test_partial_answers_are_not_refusals():
    for answer in [
        # one part unknown, the other answered
        "I don't know. The rabies vaccination is valid for 3 years, depending on the vaccine given.",
        "The context does not mention the maximum weight for a dog. The rabies vaccination is valid for 3 years.",
        # a false premise that the documents correct
        "I don't know. The context states that Barks n Woofs is open on Sundays from 8:00am to 6:00pm, "
        "with no mention of closures on that day.",
        # a caveat added to a real answer
        "Saturday hours are 8 to 6. The context doesn't say what a bath costs.",
    ]:
        check(not rag.gives_no_answer(answer), f"should count as an answer: {answer!r}")


def test_real_answers_are_not_refusals():
    check(not rag.gives_no_answer("Yes, your dog can bring a blanket or toy."), "plain answer")
    check(not rag.gives_no_answer(""), "an empty answer is not a refusal")


def test_passages_describe_each_chunk():
    chunks = [
        {"source": "a.md", "distance": 0.31234, "text": "Pet Rules > Hours\nOpen 8am.\nClosed Sundays.",
         "group": 0, "section": "Hours", "page": None},
        {"source": "guide.pdf", "distance": 0.4, "text": "guide\nA bath costs $50.", "group": 0,
         "section": "", "page": 2},
        {"source": "old.md", "distance": 0.5, "text": "old\nText from an index without sections.", "group": 0},
    ]
    got = rag.passages(chunks, ["a.md"])
    check([p["source"] for p in got] == ["a.md", "guide.pdf", "old.md"], f"order should be kept: {got}")
    check(got[0] == {"source": "a.md", "section": "Hours", "page": None, "text": "Open 8am.\nClosed Sundays.",
                     "distance": 0.312, "best": True, "listed": True}, f"unexpected: {got[0]}")
    check(got[1]["page"] == 2 and not got[1]["best"] and not got[1]["listed"], f"unexpected: {got[1]}")
    check(got[2]["section"] == "" and got[2]["page"] is None, f"missing fields should default: {got[2]}")


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

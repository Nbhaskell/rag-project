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


class FakeLlm:
    """Stands in for the model client: each call to chat() returns the next prepared stream."""

    def __init__(self, streams):
        self.streams, self.calls = list(streams), []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.streams.pop(0))


def piece(content="", thinking="", done_reason=None):
    return {"message": {"content": content, "thinking": thinking}, "done_reason": done_reason}


class FakeCollection:
    def __init__(self, count):
        self._count = count

    def count(self):
        return self._count


def ask_with(streams, think=True, indexed=1, fake=None):
    """Runs answer_stream against prepared model streams. Returns (answer text, the fake client)."""
    saved = rag.llm, rag.retrieve, rag.THINK, rag.get_collection
    fake = fake or FakeLlm(streams)
    rag.llm, rag.THINK = fake, think
    rag.get_collection = lambda: FakeCollection(indexed)
    rag.retrieve = lambda question, history=(): [
        {"source": "a.md", "distance": 0.3, "text": "Feeding\nTreats are only given with owner permission.",
         "group": 0, "section": "Feeding", "page": None}]
    try:
        _, pieces = rag.answer_stream("Will you give my dog treats?", [])
        return "".join(pieces).strip(), fake
    finally:
        rag.llm, rag.retrieve, rag.THINK, rag.get_collection = saved


def test_answers_are_capped_in_length():
    answer, fake = ask_with([[piece(thinking="ok"), piece("Fine.", done_reason="stop")]])
    check(answer == "Fine." and len(fake.calls) == 1, f"unexpected: {answer!r}, {len(fake.calls)} calls")
    check(fake.calls[0]["options"] == {"num_predict": rag.MAX_ANSWER_TOKENS} and fake.calls[0]["think"] is True,
          f"the first call should carry the token cap and thinking: {fake.calls[0]}")


def test_a_thinking_loop_is_asked_again_without_thinking():
    loop = [piece(thinking="But the user's question is a direct yes/no.") for _ in range(5)] + [
        piece(done_reason="length")]
    answer, fake = ask_with([loop, [piece("Only with the owner's permission.", done_reason="stop")]])
    check(answer == "Only with the owner's permission.", f"the second ask should give the answer: {answer!r}")
    check(len(fake.calls) == 2 and fake.calls[1]["think"] is False
          and fake.calls[1]["options"] == {"num_predict": rag.MAX_ANSWER_TOKENS},
          f"the second call should have thinking off and the same cap: {fake.calls}")


def test_a_long_answer_that_did_speak_is_not_asked_again():
    answer, fake = ask_with([[piece("The first half of a long answer", done_reason="length")]])
    check(answer.startswith("The first half") and len(fake.calls) == 1, f"unexpected: {answer!r}, {fake.calls}")


def test_no_second_ask_when_thinking_is_already_off():
    answer, fake = ask_with([[piece(done_reason="length")]], think=False)
    check(answer == "" and len(fake.calls) == 1, f"nothing to fall back to: {answer!r}, {len(fake.calls)} calls")


def test_the_prompt_lets_an_answer_state_a_condition():
    _, fake = ask_with([[piece("Only with the owner's permission.", done_reason="stop")]])
    prompt = fake.calls[0]["messages"][-1]["content"]
    check('begin with "Yes" or "No"' in prompt and "does not say whether this case meets it" in prompt,
          "the prompt should still ask for Yes/No, with the exception for a bare condition")


def test_errors_become_plain_messages_without_internals():
    import httpx
    import ollama
    cases = [
        (ConnectionError("Failed to connect to Ollama at C:/secret/path"), 503, "model_unavailable"),
        (httpx.ConnectError("refused"), 503, "model_unavailable"),
        (ollama.ResponseError("llama runner process has terminated", 500), 503, "model_unavailable"),
        (ollama.ResponseError("model 'qwen3:8b' not found", 404), 503, "model_missing"),
        (TimeoutError("the model took longer than 180 seconds to answer"), 504, "model_timeout"),
        (httpx.ReadTimeout("slow"), 504, "model_timeout"),
        (ValueError("secret detail /home/someone/file.py line 12"), 500, "internal"),
    ]
    for error, status, code in cases:
        got = rag.classify_error(error)
        check((got.status, got.code) == (status, code), f"{error!r} should be {status} {code}, got {got.status} {got.code}")
        check("secret" not in got.message and "C:/" not in got.message and "/home" not in got.message,
              f"the message must not repeat internal details: {got.message!r}")
    check("ollama pull" in rag.classify_error(ollama.ResponseError("model 'x' not found", 404)).message,
          "a missing model should say how to install it")
    own = rag.ServiceError(503, "index_empty", "No documents.")
    check(rag.classify_error(own) is own, "an error that is already plain passes through")


def test_empty_index_is_reported_before_the_model_is_asked():
    fake = FakeLlm([[piece("this should never be asked for", done_reason="stop")]])
    try:
        ask_with([], indexed=0, fake=fake)
    except rag.ServiceError as e:
        check((e.status, e.code) == (503, "index_empty") and "docs folder" in e.message,
              f"unexpected: {e.code} {e.message}")
    else:
        raise AssertionError("an empty index should raise a ServiceError")
    check(fake.calls == [], "the model must not be called when there is nothing to answer from")


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

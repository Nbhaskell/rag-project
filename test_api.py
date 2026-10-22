"""Tests for the JSON API in chat.py (/api/status, /api/ask, /api/reindex).

Run from the project folder with the venv active:   python test_api.py

Like test_indexing.py, this needs no Ollama: it starts the real server code on a spare port, with a
fake embedding function, a stand-in for the AI's answer and temporary folders.
"""
import http.client
import json
import os
import sys
import threading
import time
import traceback

import tempfile
from pathlib import Path

import ollama
import uvicorn

import chat
import guard
import rag
from test_indexing import DOC, Env, check

TOKEN = "test-token-123"
REAL_ANSWER_STREAM = rag.answer_stream  # kept: some tests need the real one, with a broken model behind it


def fake_answer_stream(question, history=()):
    chunks = [{"source": "a.md", "distance": 0.3, "text": "Hours\nOpen 8am to 6pm.", "group": 0,
               "section": "Hours", "page": None},
              {"source": "guide.pdf", "distance": 0.5, "text": "Guide\nA bath costs $50.", "group": 0,
               "section": "", "page": 3}]
    return chunks, iter(["We are open ", f"8am to 6pm. (you asked: {question})"])


rag.answer_stream = fake_answer_stream
chat.answer_stream = fake_answer_stream


class Api(Env):
    """An Env (temp docs + database) plus a running server."""

    def __init__(self):
        super().__init__()
        os.environ.pop("RAG_API_TOKEN", None)
        # Every test starts with no limits (the limits are shared, module-level state); the tests about
        # limits set their own.
        chat.guards = guard.Guards(rate_per_min=0, daily_limit=0, max_concurrent=0)
        # the real app under uvicorn on a free port
        self.server = uvicorn.Server(uvicorn.Config(chat.app, host="127.0.0.1", port=0, log_level="warning",
                                                    proxy_headers=False))  # as chat.main() runs it
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        end = time.time() + 15
        while not self.server.started and time.time() < end:
            time.sleep(0.02)
        check(self.server.started, "the test server did not start")
        self.port = self.server.servers[0].sockets[0].getsockname()[1]

    def call_full(self, method, path, body=None, headers=None, content_type="application/json"):
        """Returns (status, response headers in lower case, the body as JSON if it is JSON)."""
        headers = dict(headers or {})
        data = None
        if body is not None:
            data = body if isinstance(body, (bytes, str)) else json.dumps(body)
            headers.setdefault("Content-Type", content_type)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        sent = {name.lower(): value for name, value in response.getheaders()}
        conn.close()
        try:
            return response.status, sent, json.loads(raw)
        except ValueError:
            return response.status, sent, raw

    def call(self, method, path, body=None, headers=None, content_type="application/json"):
        status, _, body = self.call_full(method, path, body, headers, content_type)
        return status, body

    def close(self):
        os.environ.pop("RAG_API_TOKEN", None)
        self.server.should_exit = True
        self.thread.join(timeout=10)
        super().close()


def make(test):
    def run():
        env = Api()
        try:
            test(env)
        finally:
            env.close()
    run.__name__ = test.__name__
    return run


@make
def test_status_lists_the_index(env):
    env.write("a.md", DOC)
    env.sync()
    status, body = env.call("GET", "/api/status")
    check(status == 200, f"status should be 200, got {status}")
    check(body["files"] == 1 and body["documents"] == ["a.md"] and body["chunks"] == 2, f"unexpected: {body}")
    check(body["last_sync"] and body["auth_required"] is False, f"unexpected: {body}")
    check({"thinking", "split_search", "watching"} <= set(body), f"missing fields: {body}")


@make
def test_ask_returns_answer_and_sources(env):
    status, body = env.call("POST", "/api/ask", {"question": "When do you open?"})
    check(status == 200, f"expected 200, got {status}: {body}")
    check("8am to 6pm" in body["answer"] and "When do you open?" in body["answer"], f"unexpected: {body}")
    check(body["sources"] == ["a.md"] and isinstance(body["seconds"], (int, float)), f"unexpected: {body}")


@make
def test_ask_returns_passages(env):
    status, body = env.call("POST", "/api/ask", {"question": "When do you open?"})
    check(status == 200, f"expected 200, got {status}: {body}")
    first, second = body["passages"]
    check(first == {"source": "a.md", "section": "Hours", "page": None, "text": "Open 8am to 6pm.",
                    "distance": 0.3, "best": True, "listed": True}, f"unexpected first passage: {first}")
    check(second["source"] == "guide.pdf" and second["page"] == 3 and second["text"] == "A bath costs $50."
          and second["best"] is False and second["listed"] is False, f"unexpected second passage: {second}")
    check(body["sources"] == ["a.md"], f"sources must stay as before for existing callers: {body}")


@make
def test_ask_accepts_history(env):
    history = [{"role": "user", "content": "Hi"}, {"role": "assistant", "content": "Hello"}]
    status, body = env.call("POST", "/api/ask", {"question": "And Sundays?", "history": history})
    check(status == 200, f"expected 200, got {status}: {body}")


@make
def test_ask_rejects_bad_input(env):
    for bad, label in [({}, "no question"), ({"question": "   "}, "blank question"),
                       ({"question": 5}, "question is a number"), ({"question": "x" * 2001}, "too long"),
                       ({"question": "hi", "history": "nope"}, "history is not a list"),
                       ({"question": "hi", "history": [{"role": "robot", "content": "x"}]}, "bad role")]:
        status, body = env.call("POST", "/api/ask", bad)
        check(status == 400 and "error" in body, f"{label}: expected 400 with an error, got {status} {body}")


@make
def test_ask_needs_json(env):
    status, _ = env.call("POST", "/api/ask", "question=hi", content_type="application/x-www-form-urlencoded")
    check(status == 415, f"a form post should be refused with 415, got {status}")
    status, _ = env.call("POST", "/api/ask", "question=hi", content_type="text/plain")
    check(status == 415, f"a plain-text post should be refused with 415, got {status}")
    status, _ = env.call("POST", "/api/ask", "{not json")
    check(status == 400, f"broken JSON should be 400, got {status}")
    status, _ = env.call("POST", "/api/ask", "[1, 2]")
    check(status == 400, f"a JSON list should be 400, got {status}")


@make
def test_too_large_body_is_refused(env):
    status, _ = env.call("POST", "/api/ask", json.dumps({"question": "x" * (chat.MAX_BODY + 10)}))
    check(status == 413, f"expected 413, got {status}")


@make
def test_reindex_updates_what_changed(env):
    env.write("a.md", DOC)
    status, body = env.call("POST", "/api/reindex")  # no body at all is fine
    check(status == 200 and body["mode"] == "sync" and body["added"] == ["a.md"], f"unexpected: {status} {body}")
    status, body = env.call("POST", "/api/reindex", {})
    check(body["added"] == [] and body["unchanged"] == 1, f"a second sync should find nothing: {body}")
    env.write("b.md", "# B\n\n## T\nNew.\n")
    status, body = env.call("POST", "/api/reindex", {})
    check(body["added"] == ["b.md"], f"expected b.md added: {body}")


@make
def test_reindex_full_rebuild(env):
    env.write("a.md", DOC)
    status, body = env.call("POST", "/api/reindex", {"full": True})
    check(status == 200 and body["mode"] == "full" and body["files"] == 1 and body["chunks"] == 2, f"unexpected: {body}")


@make
def test_token_protects_the_api(env):
    os.environ["RAG_API_TOKEN"] = TOKEN
    check(env.call("GET", "/api/status")[0] == 401, "no token should be 401")
    check(env.call("GET", "/api/status", headers={"Authorization": "Bearer nope"})[0] == 401, "wrong token should be 401")
    check(env.call("POST", "/api/ask", {"question": "hi"})[0] == 401, "ask without a token should be 401")
    check(env.call("POST", "/api/reindex", {})[0] == 401, "reindex without a token should be 401")
    status, body = env.call("GET", "/api/status", headers={"Authorization": f"Bearer {TOKEN}"})
    check(status == 200 and body["auth_required"] is True, f"Bearer token should work: {status} {body}")
    check(env.call("GET", "/api/status", headers={"X-API-Key": TOKEN})[0] == 200, "X-API-Key should work too")
    check(env.call("POST", "/api/ask", {"question": "hi"}, headers={"Authorization": f"Bearer {TOKEN}"})[0] == 200,
          "ask with the token should work")


@make
def test_unknown_host_is_refused(env):
    status, _ = env.call("GET", "/api/status", headers={"Host": "evil.example.com"})
    check(status == 403, f"a made-up Host name should be 403, got {status}")
    status, _ = env.call("POST", "/api/ask", {"question": "hi"}, headers={"Host": "evil.example.com"})
    check(status == 403, f"a made-up Host name should be 403, got {status}")
    check(env.call("GET", "/api/status", headers={"Host": "localhost:8000"})[0] == 200, "localhost should work")
    check(env.call("GET", "/api/status", headers={"Host": "127.0.0.1"})[0] == 200, "127.0.0.1 should work")


@make
def test_unknown_addresses(env):
    check(env.call("GET", "/api/nope")[0] == 404, "unknown GET address should be 404")
    check(env.call("POST", "/api/nope", {})[0] == 404, "unknown POST address should be 404")


@make
def test_chat_window_still_works(env):
    status, page = env.call("GET", "/")
    check(status == 200 and "Document Chat" in page, "the chat page should still load")
    conn = http.client.HTTPConnection("127.0.0.1", env.port, timeout=30)
    conn.request("POST", "/", body=json.dumps({"question": "hi", "history": []}),
                 headers={"Content-Type": "application/json"})
    lines = [json.loads(line) for line in conn.getresponse().read().decode().splitlines() if line]
    conn.close()
    text = "".join(line.get("text", "") for line in lines)
    check("8am to 6pm" in text and {"sources": ["a.md"]} in lines, f"streaming answer changed: {lines}")
    passages = [line["passages"] for line in lines if "passages" in line]
    check(len(passages) == 1 and lines[-1] == {"passages": passages[0]} and len(passages[0]) == 2,
          f"the passages should arrive once, after the answer and sources: {lines}")


def test_chat_page_shows_passages_as_text_not_html():
    page = chat.PAGE
    function = page[page.index("function passageList"):page.index('form.addEventListener("submit"')]
    check("textContent" in function and "createTextNode" in function, "passages should be set as plain text")
    check("innerHTML" not in function and "insertAdjacentHTML" not in function,
          "text from a document must never be inserted as HTML")


@make
def test_unexpected_errors_come_back_as_json_without_the_details(env):
    def broken(question, history=()):
        raise RuntimeError("secret detail: the database is at C:/private/place")
    original = rag.answer_stream
    rag.answer_stream = broken
    try:
        status, headers, body = env.call_full("POST", "/api/ask", {"question": "hi"})
    finally:
        rag.answer_stream = original
    check(status == 500 and body["code"] == "internal" and "error" in body, f"expected a JSON 500, got {status} {body}")
    check("secret" not in json.dumps(body) and "private" not in json.dumps(body),
          f"the details of an unexpected error must stay out of the response: {body}")
    check(body["request_id"] == headers["x-request-id"], "the error should carry the request id, to find it in the log")


def stream(env, path, body, content_type="application/json"):
    """POST to the chat window's address. Returns (status, the lines of JSON it sent)."""
    conn = http.client.HTTPConnection("127.0.0.1", env.port, timeout=30)
    conn.request("POST", path, body=body if isinstance(body, str) else json.dumps(body),
                 headers={"Content-Type": content_type})
    response = conn.getresponse()
    lines = [json.loads(line) for line in response.read().decode().splitlines() if line]
    conn.close()
    return response.status, lines


@make
def test_chat_page_posts_to_an_address_that_exists(env):
    check('fetch("/ask"' in chat.PAGE, "the page is expected to post to /ask")
    status, lines = stream(env, "/ask", {"question": "hi", "history": []})
    check(status == 200 and {"sources": ["a.md"]} in lines and lines[-1].keys() == {"passages"},
          f"/ask should stream like /: {status} {lines}")


@make
def test_chat_stream_checks_its_input(env):
    status, lines = stream(env, "/ask", "question=hi", content_type="text/plain")
    check(status == 415 and "error" in lines[0], f"a plain-text post should be 415 with an error line: {status} {lines}")
    status, lines = stream(env, "/ask", {"question": "   "})
    check(status == 400 and "error" in lines[0], f"a blank question should be 400 with an error line: {status} {lines}")
    status, lines = stream(env, "/ask", "{not json")
    check(status == 400 and "error" in lines[0], f"broken JSON should be 400: {status} {lines}")
    status, lines = stream(env, "/ask", json.dumps({"question": "x" * (chat.MAX_BODY + 10)}))
    check(status == 413 and "error" in lines[0], f"a huge body should be 413: {status} {lines}")


@make
def test_docs_page_is_served_and_host_checked(env):
    status, page = env.call("GET", "/docs")
    check(status == 200 and "swagger" in page.lower(), f"/docs should show the API page: {status}")
    status, spec = env.call("GET", "/openapi.json")
    check(status == 200 and {"/api/ask", "/api/status", "/api/reindex"} <= set(spec["paths"]), f"unexpected: {spec}")
    ask = spec["paths"]["/api/ask"]["post"]
    properties = ask["requestBody"]["content"]["application/json"]["schema"]["properties"]
    check({"question", "history"} <= set(properties), f"the docs should describe the request body: {properties}")
    check("/ask" not in spec["paths"] and "/" not in spec["paths"], "the chat window's own addresses stay out of the docs")
    check(env.call("GET", "/docs", headers={"Host": "evil.example.com"})[0] == 403, "/docs must be host-checked too")
    check(env.call("GET", "/openapi.json", headers={"Host": "evil.example.com"})[0] == 403, "so must the spec")


@make
def test_checks_run_in_a_safe_order(env):
    os.environ["RAG_API_TOKEN"] = TOKEN
    # the host is checked first, then the token, then anything about the body
    status, _ = env.call("POST", "/api/ask", "{not json", headers={"Host": "evil.example.com"})
    check(status == 403, f"a bad Host comes first: {status}")
    status, _ = env.call("POST", "/api/ask", "{not json")
    check(status == 401, f"a missing token comes before the body is looked at: {status}")
    status, _ = env.call("POST", "/api/ask", "question=hi", content_type="text/plain")
    check(status == 401, f"so does the content type: {status}")
    status, _ = env.call("POST", "/api/ask", "{not json", headers={"Authorization": f"Bearer {TOKEN}"})
    check(status == 400, f"with the token, the broken JSON is reported: {status}")


@make
def test_a_body_without_content_length_is_still_limited(env):
    conn = http.client.HTTPConnection("127.0.0.1", env.port, timeout=30)
    big = json.dumps({"question": "x" * (chat.MAX_BODY + 10)}).encode()
    conn.putrequest("POST", "/api/ask")
    conn.putheader("Content-Type", "application/json")
    conn.putheader("Transfer-Encoding", "chunked")
    conn.endheaders()
    for i in range(0, len(big), 8192):
        piece = big[i:i + 8192]
        conn.send(f"{len(piece):x}\r\n".encode() + piece + b"\r\n")
    conn.send(b"0\r\n\r\n")
    status = conn.getresponse().status
    conn.close()
    check(status == 413, f"a chunked body over the limit should be 413, got {status}")


class Failing:
    """A model client whose every call fails with the error it was given."""

    def __init__(self, error):
        self.error = error

    def chat(self, **kwargs):
        raise self.error


class RealAnswer:
    """Puts the real answer_stream back (the other tests use a stand-in), with a model behind it that may be broken."""

    def __init__(self, llm=None):
        self.llm = llm

    def __enter__(self):
        self.saved = rag.answer_stream, chat.answer_stream, rag.llm
        rag.answer_stream = chat.answer_stream = REAL_ANSWER_STREAM
        if self.llm is not None:
            rag.llm = self.llm

    def __exit__(self, *exc):
        rag.answer_stream, chat.answer_stream, rag.llm = self.saved


def read_events(folder):
    return [json.loads(line) for line in (Path(folder) / "events.jsonl").read_text(encoding="utf-8").splitlines()]


@make
def test_every_failure_has_a_plain_message_and_a_code(env):
    env.write("a.md", DOC)
    env.sync()
    cases = [(ConnectionError("Failed to connect to Ollama"), 503, "model_unavailable"),
             (ollama.ResponseError("model 'qwen3:8b' not found", 404), 503, "model_missing"),
             (TimeoutError("the model took longer than 180 seconds to answer"), 504, "model_timeout")]
    for error, status, code in cases:
        with RealAnswer(Failing(error)):
            got, headers, body = env.call_full("POST", "/api/ask", {"question": "hi"})
            check(got == status and body["code"] == code and body["request_id"] == headers["x-request-id"],
                  f"{code}: expected {status}, got {got} {body}")
            check("Failed to connect" not in body["error"] and "180 seconds" not in body["error"],
                  f"the message should not repeat the raw error: {body['error']!r}")
            got, lines = stream(env, "/ask", {"question": "hi"})  # the chat window gets it as a line of JSON
            check(got == 200 and lines[-1]["code"] == code and lines[-1]["error"] == body["error"],
                  f"{code}: the chat window should get the same message: {got} {lines}")


@make
def test_an_empty_index_is_a_plain_error_not_a_made_up_answer(env):
    with RealAnswer():
        status, body = env.call("POST", "/api/ask", {"question": "hi"})
        check(status == 503 and body["code"] == "index_empty" and "docs folder" in body["error"],
              f"expected a plain 503, got {status} {body}")
        status, lines = stream(env, "/ask", {"question": "hi"})
        check(lines[-1]["code"] == "index_empty", f"the chat window should get it too: {lines}")
    status, body = env.call("GET", "/health")
    check(status == 200 and body == {"status": "ok", "index_ready": False}, f"unexpected: {status} {body}")
    env.write("a.md", DOC)
    env.sync()
    check(env.call("GET", "/health")[1]["index_ready"] is True, "the health check should notice the index")


@make
def test_health_check_needs_no_token_but_is_host_checked(env):
    os.environ["RAG_API_TOKEN"] = TOKEN
    check(env.call("GET", "/health")[0] == 200, "a host's health check has no token")
    check(env.call("GET", "/health", headers={"Host": "evil.example.com"})[0] == 403, "but the Host is still checked")


@make
def test_every_response_has_a_request_id_and_safe_headers(env):
    status, first, _ = env.call_full("GET", "/")
    check(status == 200 and len(first["x-request-id"]) == 12 and first["x-content-type-options"] == "nosniff"
          and first["x-frame-options"] == "DENY" and first["referrer-policy"] == "no-referrer", f"unexpected: {first}")
    _, second, _ = env.call_full("GET", "/api/status")
    check(second["x-request-id"] != first["x-request-id"], "each request has its own id")
    status, refused, _ = env.call_full("GET", "/api/status", headers={"Host": "evil.example.com"})
    check(status == 403 and "x-request-id" in refused and refused["x-frame-options"] == "DENY",
          "even a refused request gets them")


@make
def test_rate_limit_turns_back_a_fast_visitor_and_says_how_long_to_wait(env):
    now = [1000.0]
    chat.guards = guard.Guards(rate_per_min=3, max_concurrent=0, clock=lambda: now[0])
    for i in range(3):
        check(env.call("POST", "/api/ask", {"question": f"q{i}"})[0] == 200, "the first three are allowed")
    status, headers, body = env.call_full("POST", "/api/ask", {"question": "one too many"})
    check(status == 429 and body["code"] == "rate_limited" and headers["retry-after"] == "60"
          and "60 seconds" in body["error"], f"unexpected: {status} {headers.get('retry-after')} {body}")
    status, lines = stream(env, "/ask", {"question": "hi"})  # the chat window shares the allowance
    check(status == 429 and lines[0]["code"] == "rate_limited" and "60 seconds" in lines[0]["error"],
          f"the chat window should be turned back too, as a line of JSON: {status} {lines}")
    check(env.call("GET", "/api/status")[0] == 200 and env.call("GET", "/health")[0] == 200, "status is not counted")
    now[0] += 61
    check(env.call("POST", "/api/ask", {"question": "again"})[0] == 200, "after the wait it works again")


@make
def test_visitors_are_told_apart_only_by_what_the_proxy_vouches_for(env):
    now = [1000.0]

    def ask(forwarded):
        return env.call("POST", "/api/ask", {"question": "hi"}, headers={"X-Forwarded-For": forwarded})[0]

    chat.guards = guard.Guards(rate_per_min=1, max_concurrent=0, proxy_hops=1, clock=lambda: now[0])
    check(ask("9.9.9.1") == 200 and ask("9.9.9.2") == 200, "behind a proxy, different visitors have their own allowance")
    check(ask("9.9.9.1") == 429, "the same visitor runs out")
    check(ask("1.1.1.1, 9.9.9.1") == 429 and ask("2.2.2.2, 9.9.9.1") == 429,
          "entries a visitor writes to the left of the proxy's must not buy a fresh allowance")
    chat.guards = guard.Guards(rate_per_min=1, max_concurrent=0, proxy_hops=0, clock=lambda: now[0])
    check(ask("9.9.9.1") == 200 and ask("9.9.9.2") == 429, "with no proxy the header is ignored")


@make
def test_a_busy_server_says_so_and_recovers(env):
    chat.guards = guard.Guards(rate_per_min=0, max_concurrent=1)
    release, started = threading.Event(), threading.Event()

    def slow(question, history=()):
        started.set()
        release.wait(15)
        return fake_answer_stream(question, history)

    rag.answer_stream = chat.answer_stream = slow
    result = {}
    thread = threading.Thread(target=lambda: result.update(first=env.call("POST", "/api/ask", {"question": "one"})))
    thread.start()
    try:
        check(started.wait(10), "the first answer should have started")
        status, headers, body = env.call_full("POST", "/api/ask", {"question": "two"})
        check(status == 503 and body["code"] == "busy" and headers["retry-after"] == "5",
              f"a second answer should be turned away as busy: {status} {body}")
        status, lines = stream(env, "/ask", {"question": "three"})
        check(status == 503 and lines[0]["code"] == "busy", f"and so should the chat window: {status} {lines}")
        check(chat.guards.gate.active == 1, "only the running answer holds a place")
    finally:
        release.set()
        thread.join(20)
        rag.answer_stream = chat.answer_stream = fake_answer_stream
    check(result["first"][0] == 200, f"the running answer should finish normally: {result}")
    check(chat.guards.gate.active == 0, "its place should be given back")
    check(env.call("POST", "/api/ask", {"question": "four"})[0] == 200, "and the next question is answered")


@make
def test_a_daily_limit_for_the_whole_server(env):
    chat.guards = guard.Guards(rate_per_min=0, daily_limit=2, max_concurrent=1)
    check(env.call("POST", "/api/ask", {"question": "one"})[0] == 200, "first")
    check(stream(env, "/ask", {"question": "two"})[0] == 200, "second (the chat window counts too)")
    status, headers, body = env.call_full("POST", "/api/ask", {"question": "three"})
    check(status == 503 and body["code"] == "daily_limit" and 0 < int(headers["retry-after"]) <= 86400,
          f"the third should be refused for today: {status} {headers.get('retry-after')} {body}")
    check(chat.guards.gate.active == 0, "a question refused for the day must not keep a place")


@make
def test_reindexing_can_be_switched_off(env):
    chat.guards = guard.Guards(rate_per_min=0, max_concurrent=0, allow_reindex=False)
    status, body = env.call("POST", "/api/reindex", {})
    check(status == 403 and body["code"] == "reindex_disabled", f"unexpected: {status} {body}")
    check(env.call("GET", "/api/status")[0] == 200 and env.call("POST", "/api/ask", {"question": "hi"})[0] == 200,
          "everything else still works")
    os.environ["RAG_API_TOKEN"] = TOKEN
    check(env.call("POST", "/api/reindex", {})[0] == 401, "without the token it is still 401 first")


@make
def test_the_log_records_what_happened_and_no_secrets(env):
    os.environ["RAG_API_TOKEN"] = TOKEN
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        handler = guard.setup_logging(Path(tmp) / "logs", days=5)
        try:
            _, headers, _ = env.call_full("POST", "/api/ask", {"question": "When do you open?", "history": []},
                                          headers={"Authorization": f"Bearer {TOKEN}"})
            env.call("GET", "/api/status")  # no token: refused
            stream(env, "/ask", {"question": "A chat window question"})
        finally:
            guard.close_logging(handler)
        raw = (Path(tmp) / "logs" / "events.jsonl").read_text(encoding="utf-8")
        events = read_events(Path(tmp) / "logs")
    answers = [e for e in events if e["event"] == "answer"]
    check([a["route"] for a in answers] == ["api", "chat"], f"both answers should be logged: {answers}")
    first = answers[0]
    check(first["request_id"] == headers["x-request-id"] and first["question"] == "When do you open?"
          and first["sources"] == ["a.md"] and first["history"] == 0 and first["answer_chars"] > 10
          and first["dont_know"] is False and isinstance(first["seconds"], float), f"unexpected: {first}")
    check([p["source"] for p in first["passages"]] == ["a.md", "guide.pdf"]
          and all({"source", "section", "page", "distance"} == set(p) for p in first["passages"]),
          f"the retrieved passages should be logged without their text: {first['passages']}")
    check(first["visitor"] == guard.visitor_hash("127.0.0.1") and len(first["visitor"]) == 12, "the visitor is a code")
    refused = [e for e in events if e["event"] == "http_error"]
    check(len(refused) == 1 and refused[0]["status"] == 401 and refused[0]["code"] == "bad_token"
          and refused[0]["path"] == "/api/status", f"the refused request should be logged: {refused}")
    for secret in (TOKEN, "Bearer", "127.0.0.1", "Authorization"):
        check(secret not in raw, f"the log must not contain {secret!r}")


@make
def test_the_log_keeps_the_details_of_failures_and_can_leave_questions_out(env):
    saved = os.environ.get("RAG_LOG_QUESTIONS")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        handler = guard.setup_logging(Path(tmp) / "logs")
        try:
            def broken(question, history=()):
                raise RuntimeError("secret detail: the database is at C:/private/place")
            rag.answer_stream = chat.answer_stream = broken
            try:
                env.call("POST", "/api/ask", {"question": "why does this fail?"})
                os.environ["RAG_LOG_QUESTIONS"] = "0"
                env.call("POST", "/api/ask", {"question": "a private question"})
            finally:
                rag.answer_stream = chat.answer_stream = fake_answer_stream
        finally:
            guard.close_logging(handler)
            os.environ.pop("RAG_LOG_QUESTIONS", None)
            if saved is not None:
                os.environ["RAG_LOG_QUESTIONS"] = saved
        events = read_events(Path(tmp) / "logs")
    first, second = [e for e in events if e["event"] == "answer_failed"]
    check(first["code"] == "internal" and first["status"] == 500 and first["error_type"] == "RuntimeError"
          and "private/place" in first["detail"] and first["question"] == "why does this fail?",
          f"the log, unlike the response, should keep the details: {first}")
    check("question" not in second, f"RAG_LOG_QUESTIONS=0 should keep the question out: {second}")


def test_the_page_reads_a_last_line_without_a_newline():
    # an error such as a refused Host ends without a newline; the page must still show it
    check('buffer = done ? "" : lines.pop()' in chat.PAGE and "if (done) break;" in chat.PAGE,
          "the page should read the last line of a reply even when it has no newline")


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

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

import uvicorn

import chat
import rag
from test_indexing import DOC, Env, check

TOKEN = "test-token-123"


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
        # the real app under uvicorn on a free port
        self.server = uvicorn.Server(uvicorn.Config(chat.app, host="127.0.0.1", port=0, log_level="warning"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        end = time.time() + 15
        while not self.server.started and time.time() < end:
            time.sleep(0.02)
        check(self.server.started, "the test server did not start")
        self.port = self.server.servers[0].sockets[0].getsockname()[1]

    def call(self, method, path, body=None, headers=None, content_type="application/json"):
        headers = dict(headers or {})
        data = None
        if body is not None:
            data = body if isinstance(body, (bytes, str)) else json.dumps(body)
            headers.setdefault("Content-Type", content_type)
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.request(method, path, body=data, headers=headers)
        response = conn.getresponse()
        raw = response.read().decode("utf-8")
        conn.close()
        try:
            return response.status, json.loads(raw)
        except ValueError:
            return response.status, raw

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
def test_errors_come_back_as_json(env):
    def broken(question, history=()):
        raise RuntimeError("model is down")
    original = rag.answer_stream
    rag.answer_stream = broken
    try:
        status, body = env.call("POST", "/api/ask", {"question": "hi"})
    finally:
        rag.answer_stream = original
    check(status == 500 and "model is down" in body["error"], f"expected a JSON 500, got {status} {body}")


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

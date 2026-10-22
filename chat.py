import hmac
import json
import os
import sys
import threading
import time
import uuid
import webbrowser
from typing import Annotated, Literal

import uvicorn
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, StringConstraints, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

import guard
from rag import (MODEL_TIMEOUT, SPLIT_QUESTIONS, THINK, answer, answer_stream, classify_error, get_collection,
                 gives_no_answer, index_status, ingest, passages, sources_to_show, sync_docs, watch)

PAGE = """<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Document Chat</title>
<style>
  body { font-family: system-ui, sans-serif; background: #f4f4f6; margin: 0;
         display: flex; flex-direction: column; height: 100vh; }
  header { background: #2b4a6f; color: white; padding: 12px 20px; font-size: 18px;
           display: flex; justify-content: space-between; align-items: center; }
  #new { padding: 6px 12px; font-size: 14px; background: #4a6d96; }
  #log { flex: 1; overflow-y: auto; padding: 20px; max-width: 800px;
         width: 100%; box-sizing: border-box; margin: 0 auto; }
  .msg { padding: 10px 14px; margin: 10px 0; border-radius: 10px;
         white-space: pre-wrap; line-height: 1.5; max-width: 85%; }
  .user { background: #2b4a6f; color: white; margin-left: auto; }
  .bot { background: white; border: 1px solid #ddd; }
  .src { font-size: 13px; color: #666; margin-top: 8px; }
  details.passages { margin-top: 8px; font-size: 13px; color: #444; }
  details.passages summary { cursor: pointer; color: #2b4a6f; }
  .passage { border-left: 3px solid #ccd5e0; padding: 4px 10px; margin: 6px 0; background: #fafafa; }
  .passage.best { border-left-color: #2b4a6f; }
  .passage.unlisted { opacity: 0.7; }  /* read by the model, but its file is not in the Sources line */
  .phead { font-weight: 600; }
  .tag { font-weight: 400; font-size: 11px; background: #e6edf5; border-radius: 8px;
         padding: 1px 7px; margin-left: 6px; white-space: nowrap; }
  .ptext { margin-top: 3px; }
  form { display: flex; gap: 8px; padding: 12px 20px; background: white;
         border-top: 1px solid #ddd; max-width: 800px; width: 100%;
         box-sizing: border-box; margin: 0 auto; }
  input { flex: 1; padding: 10px; font-size: 16px; border: 1px solid #bbb; border-radius: 6px; }
  button { padding: 10px 20px; font-size: 16px; border: 0; border-radius: 6px;
           background: #2b4a6f; color: white; cursor: pointer; }
  button:disabled { background: #999; cursor: wait; }
</style>
</head>
<body>
<header>
  Document Chat (running locally)
  <button id="new" type="button">New chat</button>
</header>
<div id="log"></div>
<form id="form">
  <input id="q" placeholder="Ask a question about your documents..." autocomplete="off" autofocus>
  <button id="send">Send</button>
</form>
<script>
const log = document.getElementById("log");
const form = document.getElementById("form");
const input = document.getElementById("q");
const btn = document.getElementById("send");
let history = [];

document.getElementById("new").addEventListener("click", () => {
  history = [];
  log.innerHTML = "";
  input.focus();
});

function add(cls, text) {
  const div = document.createElement("div");
  div.className = "msg " + cls;
  div.textContent = text;
  log.appendChild(div);
  log.scrollTop = log.scrollHeight;
  return div;
}

// The passages the model read, as a collapsed list. Everything goes in with textContent, never as
// HTML, so text from a document can't change the page.
function passageList(items) {
  const details = document.createElement("details");
  details.className = "passages";
  const summary = document.createElement("summary");
  summary.textContent = "Passages the model read (" + items.length + ")";
  details.appendChild(summary);
  for (const p of items) {
    const box = document.createElement("div");
    box.className = "passage" + (p.best ? " best" : "") + (p.listed ? "" : " unlisted");
    const head = document.createElement("div");
    head.className = "phead";
    let where = p.source;
    if (p.section) where += " > " + p.section;
    if (p.page) where += ", page " + p.page;
    head.appendChild(document.createTextNode(where));
    if (p.best) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "best match";
      head.appendChild(tag);
    }
    const body = document.createElement("div");
    body.className = "ptext";
    body.textContent = p.text;
    box.appendChild(head);
    box.appendChild(body);
    details.appendChild(box);
  }
  return details;
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = input.value.trim();
  if (!question) return;
  input.value = "";
  btn.disabled = true;
  add("user", question);
  const bot = add("bot", "Thinking... (the first answer can take a minute)");
  let text = "";
  try {
    const res = await fetch("/ask", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({question, history}),
    });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const {done, value} = await reader.read();
      if (!done) buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split("\\n");
      buffer = done ? "" : lines.pop();  // at the end, also read a last line that has no newline (an error)
      for (const line of lines) {
        if (!line) continue;
        const data = JSON.parse(line);
        if (data.text) { text += data.text; bot.textContent = text; }
        if (data.sources) {
          const s = document.createElement("div");
          s.className = "src";
          s.textContent = "Sources: " + data.sources.join(", ");
          bot.appendChild(s);
        }
        if (data.passages && data.passages.length) bot.appendChild(passageList(data.passages));
        if (data.error) bot.textContent = "Error: " + data.error;
        log.scrollTop = log.scrollHeight;
      }
      if (done) break;
    }
    if (text) {
      history.push({role: "user", content: question});
      history.push({role: "assistant", content: text});
    }
  } catch (err) {
    bot.textContent = "Error: " + err;
  }
  btn.disabled = false;
  input.focus();
});
</script>
</body>
</html>
"""


MAX_BODY = 100_000    # bytes; a bigger request is refused
MAX_QUESTION = 2000   # characters
# Names this server answers to. Anything else (for example a web page trying a "DNS rebinding"
# trick to reach this server through another name) is refused. Add more with RAG_ALLOWED_HOSTS.
ALLOWED_HOSTS = {"localhost", "127.0.0.1", "[::1]"} | {
    h.strip().lower() for h in os.environ.get("RAG_ALLOWED_HOSTS", "").split(",") if h.strip()}
watching = False     # set to True by the main program when the folder watcher is running
# The limits on how much can be asked and how many answers run at once (see guard.py for the settings).
# A place for an answer is given back after at most two model timeouts plus a minute, even if it was never released.
guards = guard.Guards.from_env(lease_seconds=2 * MODEL_TIMEOUT + 60)
CHAT_PATHS = {"/", "/ask"}  # the chat window's own addresses; they reply in lines of JSON


def hostname(host):
    """'localhost:8000' -> 'localhost', '[::1]:8000' -> '[::1]'."""
    host = host.strip().lower()
    return host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]


# ---- what the API sends and receives (also what the /docs page shows) --------------------------
class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AskRequest(BaseModel):
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION)] = Field(
        description=f"The question, at most {MAX_QUESTION} characters.")
    history: list[Message] = Field(default=[], description="Earlier messages, for follow-up questions.")


class ReindexRequest(BaseModel):
    full: bool = Field(default=False, description="True throws the index away and rebuilds everything.")


class Passage(BaseModel):
    source: str = Field(description="The file the passage came from.")
    section: str = Field(description="The heading path inside the file, empty if it has none.")
    page: int | None = Field(description="The page number for a PDF, otherwise null.")
    text: str
    distance: float = Field(description="How far the passage is from the question: smaller is closer.")
    best: bool = Field(description="True for the closest passage.")
    listed: bool = Field(description="True if the passage's file is in `sources`.")


class AskResponse(BaseModel):
    answer: str
    sources: list[str] = Field(description="The files listed under the answer.")
    passages: list[Passage] = Field(description="Every passage the model was given, best match first.")
    seconds: float


def inline_schema(model):
    """A model's JSON schema with its nested models written in place, for the /docs page."""
    schema = model.model_json_schema()
    defs = schema.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if str(node.get("$ref", "")).startswith("#/$defs/"):
                return walk(defs[node["$ref"].split("/")[-1]])
            return {key: walk(value) for key, value in node.items()}
        if isinstance(node, list):
            return [walk(value) for value in node]
        return node
    return walk(schema)


def json_body(model):
    return {"requestBody": {"required": True, "content": {"application/json": {"schema": inline_schema(model)}}}}


app = FastAPI(
    title="Document Chat",
    description="Ask questions about the documents in the docs folder. Answers come only from those documents "
                "and come with the passages they were based on.",
    redoc_url=None,
)


class HostCheck:
    """Refuses any request whose Host header is not an allowed name (checked before anything else)."""

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            host = dict(scope["headers"]).get(b"host", b"").decode("latin-1")
            if hostname(host) not in ALLOWED_HOSTS:
                body = {"error": "Unknown Host header.", "code": "bad_host"}
                await JSONResponse(body, status_code=403)(scope, receive, send)
                return
        await self.asgi_app(scope, receive, send)


class RequestInfo:
    """Gives every request an id, sent back in the X-Request-ID header and used in the log and in error
    messages, and adds a few headers that tell browsers not to guess types or put the page in a frame."""

    def __init__(self, asgi_app):
        self.asgi_app = asgi_app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.asgi_app(scope, receive, send)
            return
        rid = uuid.uuid4().hex[:12]
        scope.setdefault("state", {})["request_id"] = rid
        extra = [(b"x-request-id", rid.encode()), (b"x-content-type-options", b"nosniff"),
                 (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer")]

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": list(message.get("headers", [])) + extra}
            await send(message)

        await self.asgi_app(scope, receive, send_with_headers)


app.add_middleware(HostCheck)
app.add_middleware(RequestInfo)  # added last, so it is the outermost: even a refused Host gets the headers


def request_id(request):
    return getattr(request.state, "request_id", None)


def visitor_of(request):
    """The visitor's address, as far as the proxies in front of this server can vouch for it."""
    return guards.visitor(request.client.host if request.client else None, request.headers.get("x-forwarded-for", ""))


def refuse(status, code, message, headers=None):
    """An HTTP error with a plain message and a short code for programs."""
    return HTTPException(status, detail={"error": message, "code": code}, headers=headers)


@app.exception_handler(StarletteHTTPException)
async def error_as_json(request, exc):
    """Every error is JSON with an "error" message (and usually a "code" and the request id), and a line in
    the log. The chat window's addresses reply in lines of JSON, so their errors do too."""
    detail = exc.detail if isinstance(exc.detail, dict) else {"error": str(exc.detail)}
    if exc.status_code == 404 and detail["error"] == "Not Found":
        detail = {"error": f"No such address: {request.url.path}"}
    else:
        guard.log_event("http_error", request_id=request_id(request), status=exc.status_code, code=detail.get("code"),
                        method=request.method, path=request.url.path, visitor=guard.visitor_hash(visitor_of(request)))
    body = {**detail, "request_id": request_id(request)}
    if request.method == "POST" and request.url.path in CHAT_PATHS:
        return Response(json.dumps(body) + "\n", status_code=exc.status_code, headers=exc.headers,
                        media_type="application/x-ndjson")
    return JSONResponse(body, status_code=exc.status_code, headers=exc.headers)


def require_token(request: Request):
    """Passes if no RAG_API_TOKEN is set, or the request carries it (Authorization: Bearer ... or
    X-API-Key: ...)."""
    token = os.environ.get("RAG_API_TOKEN", "")
    if not token:
        return
    given = request.headers.get("x-api-key", "")
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        given = auth[7:].strip()
    if not hmac.compare_digest(given.encode(), token.encode()):
        raise refuse(401, "bad_token", "Missing or wrong API token.")


def limit_rate(request: Request):
    """Each visitor may ask a limited number of questions a minute."""
    wait = guards.rate.check(visitor_of(request))
    if wait:
        raise refuse(429, "rate_limited", f"You are asking questions too quickly. Please wait {wait} "
                                          f"second{'s' if wait != 1 else ''} and try again.",
                     {"Retry-After": str(wait)})


def admit():
    """A place for one answer, or an error: every place may be taken, or the day's questions used up."""
    lease = guards.gate.acquire()
    if lease is None:
        raise refuse(503, "busy", "The server is busy answering other questions. Please try again in a few seconds.",
                     {"Retry-After": "5"})
    wait = guards.daily.take()
    if wait:
        guards.gate.release(lease)
        raise refuse(503, "daily_limit", "This server has reached its limit of questions for today. "
                                         "Please come back tomorrow.", {"Retry-After": str(wait)})
    return lease


async def read_json(request, required):
    """The JSON object in the request body. The checks run in this order, so a bad request is refused
    as early as possible: size, then content type, then JSON, then that it is an object."""
    try:
        length = int(request.headers.get("content-length", 0))
    except ValueError:
        raise refuse(400, "bad_request", "Bad Content-Length header.")
    too_large = refuse(413, "too_large", f"Request body too large (limit {MAX_BODY} bytes).")
    if length > MAX_BODY:
        raise too_large
    chunks, size = [], 0
    async for chunk in request.stream():  # also stops a body that arrives without a Content-Length
        size += len(chunk)
        if size > MAX_BODY:
            raise too_large
        chunks.append(chunk)
    body = b"".join(chunks)
    if not body and not required:
        return {}
    # Insisting on JSON also stops a web page from sending a "simple" cross-site form post.
    if not request.headers.get("content-type", "").lower().startswith("application/json"):
        raise refuse(415, "not_json", 'Send the body as JSON with the header "Content-Type: application/json".')
    try:
        data = json.loads(body or b"{}")
    except ValueError:
        raise refuse(400, "bad_request", "The body is not valid JSON.")
    if not isinstance(data, dict):
        raise refuse(400, "bad_request", 'The JSON body must be an object, like {"question": "..."}.')
    return data


def explain(error: ValidationError):
    """A short message for what is wrong with a request body."""
    first = error.errors()[0]
    field = first["loc"][0] if first["loc"] else ""
    if field == "question":
        if first["type"] == "string_too_long":
            return f"Question too long (limit {MAX_QUESTION} characters)."
        return 'Send {"question": "your question"}.'
    if field == "history":
        return '"history" must be a list of {"role", "content"} items.'
    return "The request body is not valid."


def read_question(data):
    try:
        request = AskRequest.model_validate(data)
    except ValidationError as error:
        raise refuse(400, "bad_request", explain(error))
    return request.question, [message.model_dump() for message in request.history][-20:]


def log_answer(request, route, question, history, shown, found, text, seconds):
    """One line in the log for an answered question: what was asked, what was retrieved, how it went."""
    guard.log_event(
        "answer", request_id=request_id(request), route=route, visitor=guard.visitor_hash(visitor_of(request)),
        question=guard.question_text(question), history=len(history), sources=shown,
        passages=[{"source": p["source"], "section": p["section"], "page": p["page"], "distance": p["distance"]}
                  for p in found],
        answer_chars=len(text), dont_know=gives_no_answer(text), seconds=round(seconds, 2))


def failure(request, error, route, question):
    """What went wrong while answering, as a ServiceError (a message that is safe to show, a status and a
    code); the details of the real error only go to the log."""
    problem = classify_error(error)
    guard.log_event("answer_failed", request_id=request_id(request), route=route,
                    visitor=guard.visitor_hash(visitor_of(request)), question=guard.question_text(question),
                    status=problem.status, code=problem.code, error_type=type(error).__name__,
                    detail=str(error)[:300])
    return problem


# ---- the JSON API (used by n8n and other programs) -------------------------------------------
api = APIRouter(prefix="/api", dependencies=[Depends(require_token)])


@api.get("/status", summary="What is indexed")
def api_status():
    """What is indexed (files, chunks, last update) and which options are on."""
    return {
        **index_status(),
        "watching": watching,
        "thinking": THINK,
        "split_search": SPLIT_QUESTIONS,
        "auth_required": bool(os.environ.get("RAG_API_TOKEN")),
    }


@api.post("/ask", summary="Ask a question", response_model=AskResponse, openapi_extra=json_body(AskRequest),
          dependencies=[Depends(limit_rate)])
async def api_ask(request: Request):
    """Answer a question from the documents."""
    question, history = read_question(await read_json(request, required=True))
    lease = admit()
    started = time.time()
    try:
        result = await run_in_threadpool(answer, question, history)
    except Exception as e:  # tell the caller in plain words, and keep the details for the log
        problem = failure(request, e, "api", question)
        return JSONResponse({"error": problem.message, "code": problem.code, "request_id": request_id(request)},
                            status_code=problem.status)
    finally:
        guards.gate.release(lease)
    seconds = time.time() - started
    log_answer(request, "api", question, history, result["sources"], result["passages"], result["answer"], seconds)
    return {**result, "seconds": round(seconds, 1)}


@api.post("/reindex", summary="Update the index", openapi_extra=json_body(ReindexRequest))
async def api_reindex(request: Request):
    """Update the index with what changed, or rebuild it all with {"full": true}. Can be switched off with
    RAG_ALLOW_REINDEX=0, which a public server should do."""
    if not guards.allow_reindex:
        raise refuse(403, "reindex_disabled", "Re-indexing is switched off on this server.")
    full = bool((await read_json(request, required=False)).get("full"))

    def reindex():
        if full:
            ingest()
            return {"mode": "full", **index_status()}
        return {"mode": "sync", **sync_docs()}

    try:
        result = await run_in_threadpool(reindex)
    except Exception as e:
        problem = failure(request, e, "reindex", None)
        return JSONResponse({"error": problem.message, "code": problem.code, "request_id": request_id(request)},
                            status_code=problem.status)
    guard.log_event("reindex", request_id=request_id(request), mode=result["mode"],
                    visitor=guard.visitor_hash(visitor_of(request)))
    return result


app.include_router(api)


# ---- the chat page, its own streaming address, and a health check -----------------------------
@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def chat_page():
    return PAGE


@app.get("/health", include_in_schema=False)
def health():
    """For a host's health check: is the server up, and is there an index to answer from?"""
    try:
        return {"status": "ok", "index_ready": get_collection().count() > 0}
    except Exception:
        return JSONResponse({"status": "error"}, status_code=503)


def ndjson(obj):
    return json.dumps(obj) + "\n"


@app.post("/ask", include_in_schema=False, dependencies=[Depends(limit_rate)])
@app.post("/", include_in_schema=False, dependencies=[Depends(limit_rate)])
async def chat_stream(request: Request):
    """The chat window's address: the answer arrives as lines of JSON, a piece at a time. It is not
    protected by the API token, but takes only JSON of a sensible size, like the API."""
    question, history = read_question(await read_json(request, required=True))
    lease = admit()
    started, rid = time.time(), request_id(request)

    def stream():
        text = ""
        try:
            chunks, pieces = answer_stream(question, history)
            for piece in pieces:
                text += piece
                yield ndjson({"text": piece})
            shown = sources_to_show(text, chunks)
            found = passages(chunks, shown)
            if shown:
                yield ndjson({"sources": shown})
            yield ndjson({"passages": found})
            log_answer(request, "chat", question, history, shown, found, text, time.time() - started)
        except Exception as e:
            problem = failure(request, e, "chat", question)
            yield ndjson({"error": problem.message, "code": problem.code, "request_id": rid})
        finally:
            guards.gate.release(lease)  # also when the visitor leaves in the middle (GeneratorExit)

    return StreamingResponse(stream(), media_type="application/x-ndjson")


def listen_address():
    """(host, port) to listen on: 127.0.0.1 and 8000 unless RAG_HOST and PORT say otherwise. Only a container
    needs RAG_HOST=0.0.0.0 (and then publishes the port on the host's own loopback address only)."""
    host = os.environ.get("RAG_HOST", "").strip() or "127.0.0.1"
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        port = 8000
    return host, port


def exposure_warning(allowed_hosts, has_token, reindex_on):
    """A warning for a server that is set up to be reached by others (it answers to a name other than
    localhost) while anyone who can reach it may make it re-process every document; None otherwise."""
    public_names = sorted(set(allowed_hosts) - {"localhost", "127.0.0.1", "[::1]"})
    if public_names and not has_token and reindex_on:
        return (f"RAG_ALLOWED_HOSTS names {', '.join(public_names)}, but there is no RAG_API_TOKEN and /api/reindex is "
                "on: anyone who can reach this server can make it re-process every document. Set "
                "RAG_ALLOW_REINDEX=0 (and RAG_WATCH=0), or a token.")
    return None


def main():
    global watching
    host, port = listen_address()
    url = f"http://localhost:{port}"
    if host in ("127.0.0.1", "localhost", "::1"):
        print(f"Chat is running at {url}  (press Ctrl+C to stop)")
    else:  # in a container this is the container's own port, not necessarily the one it is published on
        print(f"Chat is listening on {host}:{port}  (press Ctrl+C to stop)")
    warning = exposure_warning(ALLOWED_HOSTS, bool(os.environ.get("RAG_API_TOKEN")), guards.allow_reindex)
    if warning:
        print(f"WARNING: {warning}")
    log = guard.setup_logging()
    if log is not None:
        print(f"Logging questions and events to {log.baseFilename} (RAG_LOG=0 turns it off)")
    if os.environ.get("RAG_WATCH", "1") != "0":
        # Index new, changed and deleted documents in the background while the chat runs.
        # A daemon thread stops by itself when the program exits.
        threading.Thread(target=watch, daemon=True).start()
        watching = True
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    # proxy_headers=False: who the visitor is behind a proxy is decided only by RAG_PROXY_HOPS (guard.client_ip);
    # by default uvicorn would silently trust X-Forwarded-For from 127.0.0.1.
    uvicorn.run(app, host=host, port=port, log_level="warning", proxy_headers=False)
    print("\nStopped.")


if __name__ == "__main__":
    main()

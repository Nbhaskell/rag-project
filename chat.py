import hmac
import json
import os
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rag import (SPLIT_QUESTIONS, THINK, answer, answer_stream, index_status, ingest,
                 passages, sources_to_show, sync_docs, watch)

PORT = 8000

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
      if (done) break;
      buffer += decoder.decode(value, {stream: true});
      const lines = buffer.split("\\n");
      buffer = lines.pop();
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


def hostname(host):
    """'localhost:8000' -> 'localhost', '[::1]:8000' -> '[::1]'."""
    host = host.strip().lower()
    return host.split("]")[0] + "]" if host.startswith("[") else host.split(":")[0]


class Handler(BaseHTTPRequestHandler):
    # ---- helpers ---------------------------------------------------------------------------
    def send_json(self, status, obj):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def host_ok(self):
        return hostname(self.headers.get("Host", "")) in ALLOWED_HOSTS

    def authorized(self):
        """True if no RAG_API_TOKEN is set, or the request carries it (Authorization: Bearer ...
        or X-API-Key: ...)."""
        token = os.environ.get("RAG_API_TOKEN", "")
        if not token:
            return True
        given = self.headers.get("X-API-Key", "")
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            given = auth[7:].strip()
        return hmac.compare_digest(given.encode(), token.encode())

    def read_json(self, required):
        """Returns (data, error). error is None or a (status, message) pair."""
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return None, (400, "Bad Content-Length header.")
        if length > MAX_BODY:
            return None, (413, f"Request body too large (limit {MAX_BODY} bytes).")
        if length == 0 and not required:
            return {}, None
        # Insisting on JSON also stops a web page from sending a "simple" cross-site form post.
        if not self.headers.get("Content-Type", "").lower().startswith("application/json"):
            return None, (415, 'Send the body as JSON with the header "Content-Type: application/json".')
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None, (400, "The body is not valid JSON.")
        if not isinstance(data, dict):
            return None, (400, "The JSON body must be an object, like {\"question\": \"...\"}.")
        return data, None

    # ---- the JSON API (used by n8n and other programs) -------------------------------------
    def api_get(self, path):
        if path == "/api/status":
            return self.send_json(200, {
                **index_status(),
                "watching": watching,
                "thinking": THINK,
                "split_search": SPLIT_QUESTIONS,
                "auth_required": bool(os.environ.get("RAG_API_TOKEN")),
            })
        self.send_json(404, {"error": f"No such address: {path}"})

    def api_post(self, path):
        if path not in ("/api/ask", "/api/reindex"):
            return self.send_json(404, {"error": f"No such address: {path}"})
        data, error = self.read_json(required=(path == "/api/ask"))
        if error:
            return self.send_json(error[0], {"error": error[1]})
        try:
            if path == "/api/ask":
                question, history = data.get("question"), data.get("history", [])
                if not isinstance(question, str) or not question.strip():
                    return self.send_json(400, {"error": 'Send {"question": "your question"}.'})
                if len(question) > MAX_QUESTION:
                    return self.send_json(400, {"error": f"Question too long (limit {MAX_QUESTION} characters)."})
                if not isinstance(history, list) or not all(
                        isinstance(m, dict) and m.get("role") in ("user", "assistant")
                        and isinstance(m.get("content"), str) for m in history):
                    return self.send_json(400, {"error": '"history" must be a list of {"role", "content"} items.'})
                started = time.time()
                result = answer(question.strip(), history[-20:])
                return self.send_json(200, {**result, "seconds": round(time.time() - started, 1)})
            # /api/reindex: update what changed, or rebuild everything with {"full": true}
            if data.get("full"):
                ingest()
                return self.send_json(200, {"mode": "full", **index_status()})
            return self.send_json(200, {"mode": "sync", **sync_docs()})
        except Exception as e:  # report it to the caller instead of dropping the connection
            return self.send_json(500, {"error": str(e)})

    # ---- web page and the chat window's own streaming address -------------------------------
    def do_GET(self):
        if not self.host_ok():
            return self.send_json(403, {"error": "Unknown Host header."})
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            if not self.authorized():
                return self.send_json(401, {"error": "Missing or wrong API token."})
            return self.api_get(path)
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.host_ok():
            return self.send_json(403, {"error": "Unknown Host header."})
        path = self.path.split("?")[0]
        if path.startswith("/api/"):
            if not self.authorized():
                return self.send_json(401, {"error": "Missing or wrong API token."})
            return self.api_post(path)
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length))
        question = data.get("question", "")
        history = data.get("history", [])
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        def send(obj):
            self.wfile.write((json.dumps(obj) + "\n").encode("utf-8"))
            self.wfile.flush()

        try:
            chunks, pieces = answer_stream(question, history)
            answer = ""
            for piece in pieces:
                answer += piece
                send({"text": piece})
            shown = sources_to_show(answer, chunks)
            if shown:
                send({"sources": shown})
            send({"passages": passages(chunks, shown)})
        except Exception as e:
            send({"error": str(e)})

    def log_message(self, *args):
        pass  # keep the Command Prompt quiet


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Chat is running at {url}  (press Ctrl+C to stop)")
    if os.environ.get("RAG_WATCH", "1") != "0":
        # Index new, changed and deleted documents in the background while the chat runs.
        # A daemon thread stops by itself when the program exits.
        threading.Thread(target=watch, daemon=True).start()
        watching = True
    if "--no-browser" not in sys.argv:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from rag import answer_stream, says_dont_know

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


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = PAGE.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
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
            sources, pieces = answer_stream(question, history)
            answer = ""
            for piece in pieces:
                answer += piece
                send({"text": piece})
            # No sources for "I don't know": the searched files didn't back the answer.
            if not says_dont_know(answer):
                send({"sources": sources})
        except Exception as e:
            send({"error": str(e)})

    def log_message(self, *args):
        pass  # keep the Command Prompt quiet


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Chat is running at {url}  (press Ctrl+C to stop)")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")

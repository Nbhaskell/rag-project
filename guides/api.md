# Using it from other programs (the API)

Back to the [README](../README.md). The server also publishes this as an interactive page at `/docs` while it runs.

While `python chat.py` is running, other programs on the same computer, such as an
[n8n](https://n8n.io) workflow or a script, can use it through three web addresses. They exchange
JSON, a plain-text format for structured data.

| Address | What it does |
|---|---|
| `GET /api/status` | Shows what is indexed: files, chunks, last update, and whether the folder watcher and thinking mode are on |
| `POST /api/ask` | Send `{"question": "..."}` (and optionally `"history"`, a list of `{"role": "user" or "assistant", "content": "..."}`) and get back `{"answer": "...", "sources": ["file.md"], "passages": [...], "seconds": 3.2}` |
| `POST /api/reindex` | Update the index now. Send `{"full": true}` to rebuild everything instead |

While the chat is running, http://127.0.0.1:8000/docs shows these addresses as an interactive page:
what to send, what comes back, and a "Try it out" button. (The page loads its styling from the
internet, so it needs a connection; the API itself does not.)

`passages` lists what the model was given, best match first. Each item has `source` (the file),
`section` (the heading path, empty if there is none), `page` (a number for PDFs, otherwise `null`),
`text` (the passage), `distance` (smaller is closer), `best` (true for the closest) and `listed` (true
if its file is in `sources`). `sources` is unchanged, so existing callers keep working.

Try it in PowerShell (use `127.0.0.1` rather than `localhost`; on Windows `localhost` can pause for a
couple of seconds while it tries the IPv6 address first):

```
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/status
Invoke-RestMethod -Uri http://127.0.0.1:8000/api/ask -Method Post -ContentType "application/json" -Body '{"question": "How much is a full day?"}'
```

or in Command Prompt:

```
curl http://127.0.0.1:8000/api/status
curl -X POST http://127.0.0.1:8000/api/ask -H "Content-Type: application/json" -d "{\"question\": \"How much is a full day?\"}"
```

(In PowerShell, `curl` is not the real curl and quote handling differs, so use `Invoke-RestMethod` there.)

Problems come back as JSON with an `error` message and a status code: 400 for a bad request, 401
for a missing or wrong token, 403 for an unknown `Host`, 413 for a body over 100 KB, 415 if the body
is not sent as JSON, and 500 if something fails while answering.

**Keeping it private.** The server only listens on your own computer (`127.0.0.1`), refuses
requests whose `Host` is not `localhost` or `127.0.0.1` (add others with `RAG_ALLOWED_HOSTS`, a
comma-separated list), and only accepts JSON bodies. To also require a password, set
`RAG_API_TOKEN` before starting the chat; every `/api` request must then send it as
`Authorization: Bearer <token>` (or `X-API-Key: <token>`). The chat window itself does not need the
token. Generate a long random token with:

```
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

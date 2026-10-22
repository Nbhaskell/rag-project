# Running it for other people (a public demo)

Back to the [README](../README.md).

By default this is made for one person on one computer. If you put it on the internet, these settings
keep it safe and affordable. Set them as environment variables before starting `python chat.py` (or in
your host's settings). A limit set to `0` is switched off.

| Setting | What it does | Default |
|---|---|---|
| `RAG_RATE_PER_MIN` | Questions one visitor may ask per minute | 30 |
| `RAG_DAILY_LIMIT` | Questions the whole server answers per day (UTC) | no limit |
| `RAG_MAX_CONCURRENT` | Answers worked on at the same time; more are told the server is busy | 2 |
| `RAG_PROXY_HOPS` | How many proxies sit between the internet and the server (hosting services usually add 1) | 0 |
| `RAG_ALLOW_REINDEX` | `0` switches off `/api/reindex`, which anyone who can reach the server could use to make it re-process every document | on |
| `RAG_WATCH` | `0` stops the folder watcher | on |
| `RAG_ALLOWED_HOSTS` | Extra host names the server answers to, such as your domain | none |
| `RAG_API_TOKEN` | A password for the `/api` addresses | none |

Behind a proxy, set `RAG_PROXY_HOPS`, or every visitor looks like the proxy and they all share one
limit. The visitor is then read from the right-hand end of `X-Forwarded-For` (what your own proxy
added), never from what a visitor wrote themselves. The chat window's own address is not covered by
the token, so a public server relies on these limits. The limits live in memory: they apply to one
running copy of the server, and the daily count starts again when it restarts. If you use a hosted
model, also set a spending limit with the provider.

**When something goes wrong** the reply is a plain message, a short `code` and a `request_id`, and
the details go to the log, not to the visitor. The codes:

| `code` | Status | Meaning |
|---|---|---|
| `index_empty` | 503 | No documents have been indexed yet |
| `model_unavailable` | 503 | The language model can't be reached (is Ollama running?) |
| `model_missing` | 503 | A model is not installed (the message says how to install it) |
| `model_timeout` | 504 | The model took too long (see `RAG_MODEL_TIMEOUT`) |
| `busy` | 503 | All places for answers are taken; try again in a few seconds (`Retry-After`) |
| `daily_limit` | 503 | The day's questions are used up (`Retry-After` is the seconds to UTC midnight) |
| `rate_limited` | 429 | One visitor is asking too fast (`Retry-After` is how long to wait) |
| `reindex_disabled` | 403 | `/api/reindex` is switched off |
| `bad_token`, `bad_host` | 401, 403 | Missing or wrong token; a Host name that is not allowed |
| `too_large`, `not_json`, `bad_request` | 413, 415, 400 | Something wrong with the request body |
| `internal` | 500 | Anything unexpected; the request id finds the details in the log |

Every response also carries an `X-Request-ID` header (the same id), and `GET /health` answers
`{"status": "ok", "index_ready": true}` with no token, for a host's health check.

**The log.** `python chat.py` writes one line of JSON per event to `logs/events.jsonl` (folder:
`RAG_LOG_DIR`; `RAG_LOG=0` turns it off): a new file each UTC day, 14 days kept (`RAG_LOG_DAYS`).
For each answered question it records the time, the request id, the question (cut at 500 characters;
`RAG_LOG_QUESTIONS=0` leaves it out), the files, sections, pages and distances of the passages found,
whether the answer was "I don't know", and how long it took. Refused and failed requests are logged
too. Visitors appear only as a short code that changes when the server restarts (`RAG_LOG_SALT` makes
it stable). Never logged: tokens, headers, addresses, the answer text or the passage text. Questions
can contain personal details, so on a public demo say that they are logged and keep the retention short.

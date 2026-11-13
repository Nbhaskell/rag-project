# Security policy

This is a demonstration project. It runs on one computer, uses invented documents only, and is not offered as a hosted service. The chat server listens on `127.0.0.1` only. Putting it on a network needs the settings in [Running it for other people](guides/public-server.md), and the README lists what is still unsolved.

## Reporting a vulnerability

Report a suspected vulnerability privately through GitHub: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for it.

Please include what was found, how to reproduce it, and what it lets someone do. Reports are read and answered as time allows; there is no bug bounty.

## In scope

- Bypassing the server's guards: the API token, the allowed-`Host` check, the request size limit, the per-visitor rate limit, the daily limit or the concurrency limit.
- Reaching `/api/reindex` or the folder watcher when they are switched off.
- Answer text, passage text, tokens, headers or addresses appearing in the event log, which is meant to keep none of them.
- Path traversal or unsafe file handling through the documents folder or the n8n "Add a document" workflow.
- A secret or personal data committed to the repository.

## Known limits

Prompt injection is measured and not solved: in the injection question set the model followed a hidden formatting order and sometimes an injected claim (32 of 45 runs passed). The Sources line is chosen by a rule and is sometimes wrong, and the documents are treated as trusted. These limits are listed in the README; a new example of a listed limit is still welcome.

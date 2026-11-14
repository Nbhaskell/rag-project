# Decisions

## Repository settings (2026-11-13)

The repository is public. These GitHub settings were chosen for it:

- Secret scanning with push protection is on, so a pushed secret is blocked.
- Dependabot alerts are on. Dependabot security update pull requests are off: alerts are enough for a finished project.
- CodeQL default setup is on.
- Private vulnerability reporting is on; [SECURITY.md](SECURITY.md) states the policy.
- The ruleset "Protect main history" applies to the default branch and blocks force pushes and deletion. It requires no pull request and no status check, because the project is finished and later small changes may go directly to `main`; CI still runs on every push to `main` and on every pull request.
- The Projects tab is off.
- Merged branches are deleted automatically.

## Dependency alerts (2026-11-13)

- `pypdf` is pinned to 6.21.4 (was 6.20.0), the first 6.x release that fixes all 16 open Dependabot alerts (infinite loops and memory use on malformed PDFs). Untrusted PDFs can be indexed, so these apply. The unit and API tests pass with the new pin, including the PDF indexing tests. `requirements.txt` is the only place the pin appears.
- `chromadb` stays at 1.5.9. Four alerts have no patched version: GHSA-f4j7-r4q5-qw2c and GHSA-36p7-vc44-83pf (code injection through `trust_remote_code` in the Chroma HTTP server's collections endpoint), and GHSA-xph7-9rjv-w5fr and GHSA-2wm9-hf6c-p5cr (missing tenant checks for authenticated users of the Chroma server). All four concern the Chroma HTTP server. This project uses only the embedded `chromadb.PersistentClient` (`rag.py`), starts no Chroma server, opens no Chroma port (`compose.yaml` publishes only the app on 8000) and configures no Chroma authentication or tenants. The vulnerable components are not reachable. No newer chromadb release exists (1.5.9 is the latest on PyPI); upgrading would also change stored indexes and evaluation numbers.

## Personal-information guard (2026-11-14)

`tools/check_personal_info.py` checks the staged files before each commit (`.githooks/pre-commit`), the commit message (`.githooks/commit-msg`) and every tracked file in CI. The hooks are turned on once per clone with `git config core.hooksPath .githooks`. The checker is an adjusted copy of the one in the citebook project and uses only the standard library. Before it, the check for personal information was a manual search, which a public repository cannot rely on for every commit.

- **Personal-information findings block the commit:** a local user path, an email address or phone number that is not invented, a note about the author, an assistant-instruction file, an attribution line in a commit message, and a commit email that is not a GitHub noreply address. A finding prints the file, the line and a label, never the matched text.
- **Doc-wording findings are warnings:** a named role where a decision should be described, or first person, in Markdown files and commit messages. They are printed under "Doc wording warnings" and the commit continues; CI prints the same warnings and passes. A pattern cannot tell the voice of the docs from a quoted visitor or model message, so a wrong match costs a line of output and not a rewrite of correct text. The first-person pattern does not match present-tense verbs that end in "ed" ("I need", "I proceed"); their past-tense forms still match.
- **Invented contact details are permitted:** the placeholder address `email@address.com` (that exact address only) and the placeholder number `111-111-1111` (any number made of one repeated digit) from the made-up daycare documents, which the evaluation files and the demo page quote; addresses in the reserved top-level domains `.test`, `.example`, `.invalid` and `.localhost`; `example.com`, `example.org` and `example.net`; and 555-01xx phone numbers.
- **The made-up business documents keep their own voice:** the wording rules do not apply in `demo_docs/` and `samples/`. Every other check applies there.
- `eval_runs/published/` and `site/` are scanned in full, with no exclusion: they repeat only the permitted placeholders, and a real address in a new run must be found.
- When the guard was added, all tracked files had no personal-information finding. The 10 wording warnings at that time (in `README.md`, `IMPROVE-NOTES.md`, `PORTFOLIO-TODO.md` and `n8n/README.md`) were left as they are.

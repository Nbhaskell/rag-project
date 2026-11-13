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

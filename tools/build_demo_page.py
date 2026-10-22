"""Builds site/index.html, the recorded demo page, from tools/demo_template.html and site/recording.json.

    python tools/build_demo_page.py

The recording comes from tools/capture_demo.py. The page is one self-contained file: the recording is embedded
in it, it loads nothing from other sites, and it works when opened straight from the disk. Standard library only.
"""
import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "tools" / "demo_template.html"
RECORDING = ROOT / "site" / "recording.json"
OUT = ROOT / "site" / "index.html"


def build(recording, template):
    """The page as text: the template with the recording and its facts filled in."""
    recorded = datetime.datetime.fromisoformat(recording["recorded_at"])
    system = recording["system"]
    # Embedded in a script tag: "<" is written as < (still valid JSON) so recorded text can never close the tag.
    data = json.dumps(recording, ensure_ascii=False, separators=(",", ":")).replace("<", "\\u003c")
    values = {
        "RECORDING_JSON": data,
        "DATE": f"{recorded.day} {recorded.strftime('%B %Y')}",
        "CHAT_MODEL": system["chat_model"],
        "EMBED_MODEL": system["embed_model"],
        "DOC_COUNT": str(len(system["documents"])),
        "COMMIT": recording.get("commit") or "unknown",
    }
    page = template
    for key, value in values.items():
        page = page.replace("{{" + key + "}}", value)
    left = re.findall(r"\{\{[A-Z_]+\}\}", page)
    if left:
        raise ValueError(f"placeholders left in the page: {sorted(set(left))}")
    return page


def main():
    if not RECORDING.exists():
        sys.exit(f"{RECORDING} does not exist yet. Run tools/capture_demo.py first.")
    recording = json.loads(RECORDING.read_text(encoding="utf-8"))
    page = build(recording, TEMPLATE.read_text(encoding="utf-8"))
    OUT.write_text(page, encoding="utf-8", newline="\n")
    print(f"Wrote {OUT} ({len(page) // 1024} KB, {len(recording['items'])} recorded questions)")


if __name__ == "__main__":
    main()

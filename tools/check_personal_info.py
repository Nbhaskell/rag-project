"""Block personal information from being committed.

  python tools/check_personal_info.py --staged   what the git pre-commit hook runs
  python tools/check_personal_info.py --all      every tracked file (CI runs this)
  python tools/check_personal_info.py --message FILE   a commit message (the commit-msg hook)

Flags local user-profile paths, email addresses and phone numbers that are not invented ones,
notes that describe the author (experience, budget), assistant-instruction files, and (with
--staged) a commit email that is not a GitHub noreply address, and in commit messages an
assistant attribution line. These findings block the commit.

In Markdown files and commit messages it also reports wording about a person where a decision
or action should be described ("the owner", first person). These findings are warnings: they
are printed and the commit continues, because a pattern cannot tell the voice of the docs from
a quoted visitor or model message.

Findings print the file, the line and a label, never the matched text, so CI logs do not repeat
what was found.

Standard library only. Turn the hooks on once per clone: git config core.hooksPath .githooks
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

# User-profile folders. Placeholders such as <you> or {id} do not start with a letter or digit,
# so they never match. The names below are generic folders, not people.
_GENERIC_NAMES = {"public", "default", "user", "username", "you", "name", "runner", "example", "someone"}
_LOCAL_PATH = re.compile(
    r"(?:(?i:[a-z]:[\\/]+users[\\/]+)|(?<![\w.])/Users/|(?<![\w.])/home/)([A-Za-z0-9][\w.-]*)"
)
_EMAIL = re.compile(r"[\w.+-]+@((?:[\w-]+\.)+[A-Za-z]{2,})")
_PHONE = re.compile(r"(?<!\d)(?:\(\d{3}\)\s?|\d{3}[-. ])(\d{3})[-. ](\d{4})(?!\d)")
_OWNER_NOTE = re.compile(
    r"\bnew to (?:the )?(?:terminal|command line|coding|programming|python|git)\b"
    r"|\bnot a (?:professional )?(?:developer|programmer|engineer)\b"
    r"|\bcost-worried\b|\bbeginner\b|\bnovice\b"
    r"|\bmy (?:budget|salary|income|experience level)\b"
    r"|\bno (?:paid )?api account\b",
    re.IGNORECASE,
)

# Wording about a person, in Markdown and commit messages. Docs describe the action or the
# decision, in one neutral voice: "accepted", not "the owner accepted"; "measured", not "I
# measured". These findings are warnings (Finding.warning). Present-tense verbs that end in "ed"
# ("I need") are not first-person past tense and are not matched.
_PERSON_WORDING = re.compile(r"\bthe owner\b|\bowner['\u2019]s\b", re.IGNORECASE)
_FIRST_PERSON = re.compile(
    r"(?-i:\bI (?:(?!(?:need|feed|speed|heed|seed|proceed|succeed|exceed)\b)[a-z]+ed"
    r"|do|did|will|would|think|know|chose|decided|have|am|can|could|should"
    r"|believe|recommend|found|looked|ran|wrote|made)\b)"
    r"|\bmy\b|\bmine\b|\bwe (?:chose|decided|will|should|did)\b",
    re.IGNORECASE,
)
# A user story keeps its first person: "As a visitor, I ..." is the persona speaking.
_USER_STORY = re.compile(r"^\s*(?:[-*]|\d+\.)?\s*As an? [^,]+, I ")
# A Markdown quotation ("> ...") is another speaker's words, for example a model answer quoted in
# an evaluation note; the wording rules do not apply to it.
_QUOTATION = re.compile(r"^\s*>")
_ATTRIBUTION = re.compile(r"co-authored-by:|generated with|claude code", re.IGNORECASE)

# Invented contact details. The domains and top-level domains below are reserved for examples
# (RFC 2606), so no real mailbox can have them. The made-up daycare documents, and every
# evaluation file that quotes them, use one placeholder address and one placeholder number.
_FAKE_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
_RESERVED_TLDS = (".test", ".example", ".invalid", ".localhost")
_PLACEHOLDER_EMAILS = {"email@address.com"}
_NOREPLY_DOMAIN = "users.noreply.github.com"
_ASSISTANT_FILES = {"claude.md", "claude.local.md"}
_EXCLUDED_SUFFIXES = ("tools/check_personal_info.py", "test_check_personal_info.py")

# The documents of the made-up businesses, written in their own voice ("We do allow a grace
# period", "the owner will be notified"). The wording rules do not apply there; every other
# check does.
_BUSINESS_COPY_DIRS = ("demo_docs/", "samples/")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    label: str
    warning: bool = False  # doc wording: printed, does not block


def is_excluded(path: str) -> bool:
    """This checker and its tests, whose patterns look like what the checker flags."""
    return path.replace("\\", "/").endswith(_EXCLUDED_SUFFIXES)


def _email_is_invented(address: str, domain: str) -> bool:
    address, domain = address.lower(), domain.lower()
    if address in _PLACEHOLDER_EMAILS or address == "noreply@github.com":
        return True
    if domain == _NOREPLY_DOMAIN or domain.endswith("." + _NOREPLY_DOMAIN):
        return True
    if domain.endswith(_RESERVED_TLDS):
        return True
    return any(domain == d or domain.endswith("." + d) for d in _FAKE_EMAIL_DOMAINS)


def _phone_is_invented(match: re.Match[str]) -> bool:
    """555-01xx is reserved for fiction; one digit repeated ten times is a placeholder."""
    if match.group(1) == "555" and match.group(2).startswith("01"):
        return True
    return len(set(re.sub(r"\D", "", match.group(0)))) == 1


def scan_text(path: str, text: str) -> list[Finding]:
    findings: list[Finding] = []
    posix = path.replace("\\", "/")
    if PurePosixPath(posix).name.lower() in _ASSISTANT_FILES:
        findings.append(Finding(path, 1, "assistant-instruction file"))
    check_wording = posix.lower().endswith(".md") and not posix.startswith(_BUSINESS_COPY_DIRS)
    for number, line in enumerate(text.splitlines(), start=1):
        labels: list[str] = []
        wording: list[str] = []
        if any(m.group(1).lower() not in _GENERIC_NAMES for m in _LOCAL_PATH.finditer(line)):
            labels.append("local user path")
        if any(not _email_is_invented(m.group(0), m.group(1)) for m in _EMAIL.finditer(line)):
            labels.append("email address")
        if any(not _phone_is_invented(m) for m in _PHONE.finditer(line)):
            labels.append("phone number")
        if _OWNER_NOTE.search(line):
            labels.append("note about the author")
        if check_wording:
            if _PERSON_WORDING.search(line):
                wording.append("wording about a person (describe the decision instead)")
            quoted = _USER_STORY.match(line) or _QUOTATION.match(line)
            if _FIRST_PERSON.search(line) and not quoted:
                wording.append("first person (describe the action instead)")
        findings.extend(Finding(path, number, label) for label in labels)
        findings.extend(Finding(path, number, label, warning=True) for label in wording)
    return findings


def scan_message(text: str) -> list[Finding]:
    """A commit message: attribution and notes about the author block; wording warns."""
    findings: list[Finding] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.startswith("#"):  # git's own comment lines
            continue
        if _ATTRIBUTION.search(line):
            findings.append(Finding("commit message", number, "assistant attribution line"))
        if _OWNER_NOTE.search(line):
            findings.append(Finding("commit message", number, "note about the author"))
        if _PERSON_WORDING.search(line):
            label = "wording about a person (describe the decision)"
            findings.append(Finding("commit message", number, label, warning=True))
        if _FIRST_PERSON.search(line):
            label = "first person (describe the action)"
            findings.append(Finding("commit message", number, label, warning=True))
    return findings


def check_author(email: str) -> str | None:
    """None if commits would carry a GitHub noreply address, else what to do about it."""
    if email.lower().endswith("@" + _NOREPLY_DOMAIN):
        return None
    return (
        "The commit email is not a GitHub noreply address, so it would be published with the "
        "commit. Set it with: git config user.email <id>+<username>@users.noreply.github.com"
    )


def _git(*args: str) -> bytes:
    return subprocess.run(["git", *args], capture_output=True, check=True).stdout


def _decode(data: bytes) -> str | None:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return None  # binary file


def _staged_files() -> dict[str, str]:
    names = _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z").split(b"\0")
    files: dict[str, str] = {}
    for raw in filter(None, names):
        name = raw.decode("utf-8")
        text = _decode(_git("show", f":{name}"))
        if text is not None:
            files[name] = text
    return files


def _tracked_files() -> dict[str, str]:
    files: dict[str, str] = {}
    for raw in filter(None, _git("ls-files", "-z").split(b"\0")):
        name = raw.decode("utf-8")
        try:
            text = _decode(Path(name).read_bytes())
        except OSError:
            continue
        if text is not None:
            files[name] = text
    return files


def _author_email() -> str:
    ident = _git("var", "GIT_AUTHOR_IDENT").decode("utf-8")
    match = re.search(r"<([^>]*)>", ident)
    return match.group(1) if match else ""


def _print_warnings(lines: Sequence[str], where: str) -> None:
    if lines:
        print(f"Doc wording warnings in the {where} (not blocking):")
        print("\n".join(f"  {line}" for line in lines))
        print("Describe the action or the decision in one neutral voice, or quote a speaker with >.")


def main(
    argv: Sequence[str] | None = None,
    read_files: Callable[[], Mapping[str, str]] | None = None,
    author_email: str | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Block personal information from commits.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--staged", action="store_true", help="check files staged for commit")
    mode.add_argument("--all", action="store_true", help="check every tracked file")
    mode.add_argument("--message", metavar="FILE", help="check a commit message file")
    args = parser.parse_args(argv)

    if args.message:
        found = scan_message(Path(args.message).read_text(encoding="utf-8"))
        _print_warnings([f"line {f.line}: {f.label}" for f in found if f.warning], "commit message")
        blocking = [f for f in found if not f.warning]
        if blocking:
            print("Commit message check failed:")
            print("\n".join(f"  line {f.line}: {f.label}" for f in blocking))
            print("Remove the line and commit again.")
            return 1
        return 0

    files = (read_files or (_staged_files if args.staged else _tracked_files))()
    problems: list[str] = []
    warnings: list[str] = []
    scanned = 0
    for path, text in sorted(files.items()):
        if is_excluded(path):
            continue
        scanned += 1
        for f in scan_text(path, text):
            (warnings if f.warning else problems).append(f"{f.path}:{f.line}: {f.label}")
    if args.staged:
        message = check_author(_author_email() if author_email is None else author_email)
        if message:
            problems.append(message)

    _print_warnings(warnings, "docs")
    if problems:
        print("Personal information check failed:")
        print("\n".join(f"  {p}" for p in problems))
        print("The matched text is not shown. Remove it or replace it with an invented value.")
        return 1
    print(f"No personal information found in {scanned} files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

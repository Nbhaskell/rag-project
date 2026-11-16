"""Tests for tools/check_personal_info.py: what it blocks, what it only warns about, and what it never prints.

Run from the project folder with the venv active:   python tests/test_check_personal_info.py

No Ollama, no index, no git: the file contents and the commit email are passed in.
"""
import contextlib
import io
import sys
import tempfile
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import check_personal_info as checker  # noqa: E402

# Built from parts so this file never contains a real-looking address or path itself.
WINDOWS_HOME = "C:" + "\\Users\\" + "jdoe" + "\\project"
POSIX_HOME = "/home/" + "jdoe" + "/project"
MAC_HOME = "/Users/" + "jdoe" + "/project"
PERSONAL_EMAIL = "jdoe" + "@" + "gmail.com"
PHONE = "(212) " + "867-5309"
NOREPLY = "a@users.noreply.github.com"


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def labels(text, path="guides/notes.md"):
    return [f.label for f in checker.scan_text(path, text)]


def run_main(argv, **kwargs):
    """The exit code and everything main() printed."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = checker.main(argv, **kwargs)
    return code, out.getvalue()


# --- personal information: these findings block ---------------------------------------------------


def test_local_user_paths_are_found():
    for home in (WINDOWS_HOME, POSIX_HOME, MAC_HOME):
        check(labels(f"run it from {home}") == ["local user path"], home)


def test_generic_paths_and_placeholders_are_allowed():
    for text in (
        r"C:\Users\Public\Documents",
        "/home/runner/work/repo",
        r"C:\Users\<you>\rag-project",
        "/Users/<name>/rag-project",
        "secret detail /home/someone/file.py line 12",
    ):
        check(labels(text) == [], text)


def test_a_personal_email_address_is_found():
    check(labels(f"contact {PERSONAL_EMAIL}") == ["email address"], "a real-looking address should be found")


def test_invented_and_noreply_addresses_are_allowed():
    for address in (
        "billing@example.com",
        "16366851+someone@users.noreply.github.com",
        "noreply@github.com",
        "ap@vendor.example.org",
        "email@address.com",  # the placeholder in the made-up daycare documents
        "hr@bluefin-example.test",  # .test can never be a real domain
        "info@daycare.example",
    ):
        check(labels(f"mail {address}") == [], address)


def test_the_placeholder_address_is_allowed_only_as_written():
    check(labels("mail jdoe@" + "address.com") == ["email address"], "another name at that domain is not a placeholder")


def test_a_real_looking_phone_number_is_found_but_invented_ones_are_not():
    check(labels(f"call {PHONE}") == ["phone number"], "a real-looking number should be found")
    check(labels("call 555-0142 or (212) 555-0188") == [], "555-01xx numbers are reserved for fiction")
    check(labels("Contact us at 111-111-1111.") == [], "one digit repeated ten times is a placeholder")
    check(labels("call 111-111-1112") == ["phone number"], "one different digit makes it real-looking")


def test_notes_about_the_author_are_found():
    for text in (
        "The author is new to the terminal.",
        "Not a professional developer, explain gently.",
        "Keep costs low: cost-worried about API spend.",
        "My budget is small.",
        "Written for a beginner.",
    ):
        check("note about the author" in labels(text), text)
    check(labels("Explain steps in plain language. Use only free, local tools.") == [], "an instruction is fine")


def test_assistant_instruction_files_are_found_by_name():
    for path in ("CLAUDE.md", "CLAUDE.local.md", "guides/CLAUDE.md"):
        check(labels("anything", path=path) == ["assistant-instruction file"], path)


def test_findings_carry_line_numbers_and_never_the_matched_text():
    findings = checker.scan_text("README.md", f"fine\nmail {PERSONAL_EMAIL}\nfine")
    check(findings == [checker.Finding("README.md", 2, "email address")], f"got {findings!r}")
    check(PERSONAL_EMAIL not in repr(findings), "the matched text must not be kept")


def test_the_checker_and_its_tests_are_skipped():
    for path in ("tools/check_personal_info.py", "tests/test_check_personal_info.py"):
        check(checker.is_excluded(path), path)
    check(not checker.is_excluded("README.md"), "README.md is scanned")


def test_only_a_noreply_commit_email_is_accepted():
    for email in ("16366851+someone@users.noreply.github.com", "someone@users.noreply.github.com"):
        check(checker.check_author(email) is None, email)
    for email in (PERSONAL_EMAIL, "", "me@" + "work.example"):
        message = checker.check_author(email)
        check(message is not None, f"{email!r} should be refused")
        check(PERSONAL_EMAIL not in message, "the address must not be repeated")


def test_main_reports_findings_without_the_text_and_exits_one():
    files = {"README.md": f"mail {PERSONAL_EMAIL}\n", "ok.md": "nothing here\n"}
    code, out = run_main(["--staged"], read_files=lambda: files, author_email=NOREPLY)
    check(code == 1, "a finding should stop the commit")
    check("README.md:1: email address" in out, out)
    check(PERSONAL_EMAIL not in out, "the matched text must not be printed")


def test_main_exits_zero_when_clean():
    code, out = run_main(["--staged"], read_files=lambda: {"ok.md": "nothing here\n"}, author_email=NOREPLY)
    check(code == 0, out)
    check("No personal information found in 1 files." in out, out)


def test_main_checks_the_commit_email_in_staged_mode_only():
    clean = {"ok.md": "nothing here\n"}
    check(run_main(["--staged"], read_files=lambda: clean, author_email=PERSONAL_EMAIL)[0] == 1, "staged")
    # CI checks files, not who is committing.
    check(run_main(["--all"], read_files=lambda: clean, author_email=PERSONAL_EMAIL)[0] == 0, "all")


# --- doc wording, in Markdown and commit messages: these findings warn ------------------------------


def test_wording_about_a_person_is_found_in_markdown():
    for text in (
        "The owner accepted the tool.",
        "Confirmed by the owner on 3 Nov.",
        "That is the owner's decision.",
        "I measured the run and it took 30 seconds.",
        "As far as I know the wheel is LGPL.",
        "I do not know why the gap exists.",
        "Compared in my check against the key.",
        "We decided to leave it out.",
    ):
        found = labels(text)
        check(found and all("describe the" in label for label in found), f"{text!r} gave {found!r}")


def test_neutral_wording_and_quotations_are_allowed():
    for text in (
        "The tool was accepted.",
        "A dog owner or a staff member asks a question.",
        "- As an owner, I am told when a document cannot be read.",
        "A capital I and a lower-case l look the same.",
        "Part I of the plan; the I/O layer.",
        "Measured at 30 seconds per answer.",
        "> I found two passages about boarding.",
    ):
        check(labels(text) == [], text)


def test_the_wording_rule_applies_to_markdown_only():
    check(labels("I measured it; the owner decided.", "tools/notes.py") == [], "not in code")
    check(labels("I measured it; the owner decided.", "README.md") != [], "in Markdown")


def test_present_tense_verbs_that_end_in_ed_are_not_first_person():
    for verb in ("need", "feed", "speed", "heed", "seed", "proceed", "succeed", "exceed"):
        check(labels(f"I {verb} the report by Friday.") == [], f"I {verb}")
    check(labels("| 1 | Type: `I need a full day for two dogs.` | The price is given. |") == [], "in a table")


def test_past_tense_verbs_after_i_are_still_found():
    for verb in ("needed", "feeded", "speeded", "heeded", "seeded", "proceeded", "succeeded", "exceeded"):
        check(labels(f"I {verb} with the run.") != [], f"I {verb}")


def test_the_made_up_business_keeps_its_own_voice_but_not_real_contact_details():
    text = "## Do I need a reservation?\nWe decided on a 5-day grace period. Treats need the owner's permission.\n"
    for path in ("demo_docs/05-daily-routine.md", "samples/handbook.md"):
        check(checker.scan_text(path, text) == [], path)
    check(checker.scan_text("guides/faq.md", text) != [], "the rule applies outside those folders")
    leak = f"Write to {PERSONAL_EMAIL}\n"
    check([f.label for f in checker.scan_text("demo_docs/faq.md", leak)] == ["email address"], "still blocked")


def test_wording_findings_are_warnings_and_personal_information_is_not():
    found = checker.scan_text("guides/notes.md", f"I measured it.\nThe owner decided.\nmail {PERSONAL_EMAIL}\n")
    check([(f.line, f.warning) for f in found] == [(1, True), (2, True), (3, False)], f"got {found!r}")
    note = checker.scan_text("guides/notes.md", "A beginner wrote this.")
    check([f.warning for f in note] == [False], "a note about the author blocks")


def test_main_prints_wording_warnings_and_exits_zero():
    files = {"guides/notes.md": "I measured the run.\n"}
    code, out = run_main(["--staged"], read_files=lambda: files, author_email=NOREPLY)
    check(code == 0, "wording alone must not stop the commit")
    check("Doc wording warnings" in out, out)
    check("guides/notes.md:1: first person" in out, out)
    check("Personal information check failed" not in out, out)
    check("No personal information found in 1 files." in out, out)


def test_main_blocks_on_personal_information_and_still_prints_the_warnings():
    files = {"guides/notes.md": f"I measured the run.\nmail {PERSONAL_EMAIL}\n"}
    code, out = run_main(["--all"], read_files=lambda: files)
    check(code == 1, "personal information stops the commit")
    before, _, after = out.partition("Personal information check failed")
    check("guides/notes.md:1: first person" in before, out)
    check("guides/notes.md:2: email address" in after, out)
    check("first person" not in after, "a warning must not be listed as a failure")


# --- commit messages --------------------------------------------------------------------------------


def test_a_commit_message_is_checked_for_attribution_and_wording():
    check(checker.scan_message("Add POST /api/search\n\nThe closest passages are returned.") == [], "clean")
    found = checker.scan_message("Fix it\n\nCo-Authored-By: someone\nGenerated with a tool\nI think this is right.")
    check(
        [(f.label, f.warning) for f in found]
        == [
            ("assistant attribution line", False),
            ("assistant attribution line", False),
            ("first person (describe the action)", True),
        ],
        f"got {found!r}",
    )
    check(checker.scan_message("# a comment line from git\nBump pypdf") == [], "git's comment lines are skipped")
    check(checker.scan_message("I need the pin raised.") == [], "present tense is not matched in messages either")


def test_main_checks_a_message_file():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        cases = {
            "clean": ("Add the rule\n", 0),
            "attribution": ("Add the rule\n\nCo-Authored-By: someone\n", 1),
            "note": ("Add the rule\n\nWritten by a beginner.\n", 1),
        }
        for name, (text, expected) in cases.items():
            path = Path(tmp) / f"{name}.txt"
            path.write_text(text, encoding="utf-8")
            check(run_main(["--message", str(path)])[0] == expected, name)


def test_a_commit_message_with_wording_only_warns():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        path = Path(tmp) / "wording.txt"
        path.write_text("Add the rule\n\nI think this is right.\nThe owner decided.\n", encoding="utf-8")
        code, out = run_main(["--message", str(path)])
    check(code == 0, "wording alone must not stop the commit")
    check("Doc wording warnings" in out, out)
    check("line 3: first person" in out and "line 4: wording about a person" in out, out)
    check("Commit message check failed" not in out, out)


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]

if __name__ == "__main__":
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL  {test.__name__}")
            traceback.print_exc()
    print(f"\n{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)

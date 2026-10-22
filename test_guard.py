"""Tests for guard.py: the rate limit, the concurrency limit, the daily cap, the visitor address and the log.

Run from the project folder with the venv active:   python test_guard.py

No Ollama, no index, no server: the limits take a fake clock, and the log writes to a temporary folder.
"""
import json
import os
import sys
import tempfile
import traceback
from pathlib import Path

import guard


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class Clock:
    def __init__(self, now=1000.0):
        self.now = now

    def __call__(self):
        return self.now


def test_rate_limit_allows_a_burst_then_says_how_long_to_wait():
    clock = Clock()
    limiter = guard.RateLimiter(3, 60.0, clock)
    check([limiter.check("a") for _ in range(3)] == [0, 0, 0], "the first three should be allowed")
    check(limiter.check("a") == 60, "the fourth should wait the whole window")
    clock.now += 25
    check(limiter.check("a") == 35, "25 seconds later it should wait 35 more")
    clock.now += 35
    check(limiter.check("a") == 0, "after the wait it should be allowed (refused tries did not count)")


def test_rate_limit_is_per_visitor_and_can_be_off():
    limiter = guard.RateLimiter(1, 60.0, Clock())
    check(limiter.check("a") == 0 and limiter.check("b") == 0, "each visitor has their own allowance")
    check(limiter.check("a") > 0 and limiter.check("b") > 0, "and each runs out separately")
    off = guard.RateLimiter(0, 60.0, Clock())
    check(all(off.check("a") == 0 for _ in range(1000)), "a limit of 0 means no limit")


def test_rate_limit_forgets_visitors_who_went_quiet():
    clock = Clock()
    limiter = guard.RateLimiter(5, 60.0, clock)
    for i in range(300):
        limiter.check(f"visitor-{i}")
    clock.now += 120
    for i in range(300):  # past the 500 calls that trigger the clean-up
        limiter.check("busy")
    check(len(limiter.events) < 50, f"quiet visitors should be forgotten, still holding {len(limiter.events)}")


def test_concurrency_gate_holds_places_and_reclaims_lost_ones():
    clock = Clock()
    gate = guard.ConcurrencyGate(2, lease_seconds=100, clock=clock)
    first, second = gate.acquire(), gate.acquire()
    check(first and second and gate.active == 2, "two places should be given")
    check(gate.acquire() is None, "a third should be refused")
    gate.release(first)
    third = gate.acquire()
    check(third and gate.active == 2, "a released place can be taken again")
    gate.release("never-given")  # harmless
    check(gate.acquire() is None, "full again")
    clock.now += 101  # nobody ever released these (for example the visitor disconnected before the answer started)
    check(gate.acquire() is not None, "places that were never given back must expire")
    check(guard.ConcurrencyGate(0).acquire() is not None, "a limit of 0 means no limit")


def test_daily_cap_counts_per_utc_day():
    clock = Clock(86400 * 10 + 3600)  # one hour into a day
    cap = guard.DailyCap(2, clock)
    check(cap.take() == 0 and cap.take() == 0, "two questions are allowed")
    check(cap.take() == 82800, f"the third waits until midnight (23 hours): {cap.take()}")
    clock.now = 86400 * 11 + 5
    check(cap.take() == 0, "the next day starts again")
    check(guard.DailyCap(0).take() == 0, "a limit of 0 means no limit")


def test_visitor_address_only_trusts_what_the_proxies_added():
    check(guard.client_ip("10.0.0.1", "1.1.1.1", 0) == "10.0.0.1", "with no proxy the header is ignored")
    check(guard.client_ip("10.0.0.1", "9.9.9.9, 1.1.1.1", 1) == "1.1.1.1", "one proxy: the rightmost entry")
    check(guard.client_ip("10.0.0.1", "6.6.6.6, 1.1.1.1, 2.2.2.2", 2) == "1.1.1.1", "two proxies: second from the right")
    check(guard.client_ip("10.0.0.1", "forged", 2) == "10.0.0.1", "too few entries: the connection's address")
    check(guard.client_ip("10.0.0.1", "", 1) == "10.0.0.1", "no header: the connection's address")
    check(guard.client_ip(None, "", 0) == "unknown", "no address at all")
    # a visitor adding their own entries cannot choose the address that is used
    check(guard.client_ip("10.0.0.1", "7.7.7.7, 8.8.8.8, 1.1.1.1", 1) == "1.1.1.1", "forged entries on the left are ignored")


def test_guards_read_their_settings_from_the_environment():
    names = ["RAG_RATE_PER_MIN", "RAG_DAILY_LIMIT", "RAG_MAX_CONCURRENT", "RAG_PROXY_HOPS", "RAG_ALLOW_REINDEX"]
    saved = {n: os.environ.pop(n, None) for n in names}
    try:
        g = guard.Guards.from_env()
        check((g.rate.limit, g.daily.limit, g.gate.limit, g.proxy_hops, g.allow_reindex) == (30, 0, 2, 0, True),
              "the defaults should be generous")
        os.environ.update(RAG_RATE_PER_MIN="5", RAG_DAILY_LIMIT="200", RAG_MAX_CONCURRENT="1", RAG_PROXY_HOPS="1",
                          RAG_ALLOW_REINDEX="0")
        g = guard.Guards.from_env(lease_seconds=42)
        check((g.rate.limit, g.daily.limit, g.gate.limit, g.proxy_hops, g.allow_reindex, g.gate.lease_seconds)
              == (5, 200, 1, 1, False, 42), "the settings should be read")
        os.environ["RAG_RATE_PER_MIN"] = "lots"
        check(guard.Guards.from_env().rate.limit == 30, "a value that is not a number falls back to the default")
    finally:
        for n in names:
            os.environ.pop(n, None)
            if saved[n] is not None:
                os.environ[n] = saved[n]


def test_visitor_code_hides_the_address():
    code = guard.visitor_hash("203.0.113.9")
    check(len(code) == 12 and "203" not in code, f"unexpected code: {code}")
    check(code == guard.visitor_hash("203.0.113.9") and code != guard.visitor_hash("203.0.113.10"),
          "the same visitor gets the same code, another visitor another")


def test_question_text_is_clipped_and_can_be_left_out():
    saved = os.environ.pop("RAG_LOG_QUESTIONS", None)
    try:
        check(guard.question_text("short") == "short", "a short question is kept as it is")
        long = guard.question_text("x" * 900)
        check(len(long) == guard.QUESTION_CHARS + 3 and long.endswith("..."), f"a long one is clipped: {len(long)}")
        os.environ["RAG_LOG_QUESTIONS"] = "0"
        check(guard.question_text("secret") is None, "RAG_LOG_QUESTIONS=0 keeps questions out of the log")
    finally:
        os.environ.pop("RAG_LOG_QUESTIONS", None)
        if saved is not None:
            os.environ["RAG_LOG_QUESTIONS"] = saved


def test_log_writes_json_lines_and_keeps_a_limited_history():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        handler = guard.setup_logging(Path(tmp) / "logs", days=3)
        try:
            check(handler is not None, "logging should start")
            check(handler.backupCount == 3 and handler.when == "MIDNIGHT" and handler.utc,
                  "the log should start a new file each UTC midnight and keep 3 days")
            guard.log_event("answer", question="Wie viel kostet ein Bad? ü", sources=["a.md"], skipped=None, seconds=1.5)
            guard.log_event("odd", thing=object())  # not JSON on its own: still must not raise
        finally:
            guard.close_logging(handler)
        lines = [json.loads(l) for l in (Path(tmp) / "logs" / "events.jsonl").read_text(encoding="utf-8").splitlines()]
        check(len(lines) == 2, f"two events should be logged: {lines}")
        first = lines[0]
        check(first["event"] == "answer" and first["question"] == "Wie viel kostet ein Bad? ü"
              and first["sources"] == ["a.md"] and "skipped" not in first and first["ts"].endswith("+00:00"),
              f"unexpected first line: {first}")


def test_log_can_be_switched_off_and_never_breaks_things():
    saved = os.environ.get("RAG_LOG")
    try:
        os.environ["RAG_LOG"] = "0"
        check(guard.setup_logging() is None, "RAG_LOG=0 should switch it off")
    finally:
        os.environ.pop("RAG_LOG", None)
        if saved is not None:
            os.environ["RAG_LOG"] = saved
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        blocker = Path(tmp) / "a-file"
        blocker.write_text("x")
        check(guard.setup_logging(blocker / "logs") is None, "a log folder that can't be made is not fatal")
    guard.log_event("nobody is listening")  # no handler set up: silently nothing


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

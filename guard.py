"""Keeping a public question-answering server safe and observable.

Limits on how much one visitor (or everyone) can ask, how many answers run at once, and a log in JSON
lines of what happened. Nothing here needs Ollama or the document index, so it is tested on its own
(test_guard.py) with a fake clock.

Everything is set with environment variables (see Guards.from_env and setup_logging). The defaults are
generous enough that using the chat on your own computer never notices them.
"""
import hashlib
import json
import logging
import logging.handlers
import math
import os
import secrets
import sys
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from pathlib import Path


class RateLimiter:
    """At most `limit` events per `window` seconds for each key (a sliding window). A limit of 0 means none."""

    def __init__(self, limit, window=60.0, clock=time.monotonic):
        self.limit, self.window, self.clock = limit, window, clock
        self.events = {}  # key -> times of its recent events
        self.lock = threading.Lock()
        self.calls = 0

    def check(self, key):
        """Counts an event for key. Returns 0 if it is allowed, otherwise the whole seconds to wait.
        A refused event is not counted, so waiting the returned time always works."""
        if self.limit <= 0:
            return 0
        now = self.clock()
        with self.lock:
            self.calls += 1
            if self.calls % 500 == 0:  # forget visitors that have gone quiet, so memory stays small
                self.events = {k: q for k, q in self.events.items() if q and q[-1] > now - self.window}
            recent = self.events.setdefault(key, deque())
            while recent and recent[0] <= now - self.window:
                recent.popleft()
            if len(recent) >= self.limit:
                return max(1, math.ceil(recent[0] + self.window - now))
            recent.append(now)
            return 0


class ConcurrencyGate:
    """At most `limit` answers running at once (0 means no limit).

    A place is a lease that expires after `lease_seconds`, so a place can never be lost for good: if a
    visitor disconnects before an answer starts, nothing would ever give the place back otherwise.
    """

    def __init__(self, limit, lease_seconds=600.0, clock=time.monotonic):
        self.limit, self.lease_seconds, self.clock = limit, lease_seconds, clock
        self.leases = {}  # lease id -> when it was taken
        self.lock = threading.Lock()

    def acquire(self):
        """A lease id, or None when every place is taken."""
        now = self.clock()
        with self.lock:
            self.leases = {k: t for k, t in self.leases.items() if now - t <= self.lease_seconds}
            if self.limit > 0 and len(self.leases) >= self.limit:
                return None
            lease = uuid.uuid4().hex
            self.leases[lease] = now
            return lease

    def release(self, lease):
        with self.lock:
            self.leases.pop(lease, None)

    @property
    def active(self):
        with self.lock:
            return len(self.leases)


class DailyCap:
    """At most `limit` questions per day for the whole server, counted per UTC day (0 means no limit).

    The count is kept in memory, so a restart starts it again; the spending limit at the model provider
    is the real backstop for a hosted model.
    """

    def __init__(self, limit, clock=time.time):
        self.limit, self.clock = limit, clock
        self.day, self.count = None, 0
        self.lock = threading.Lock()

    def take(self):
        """Counts a question. Returns 0 if allowed, otherwise the seconds until the next UTC midnight."""
        if self.limit <= 0:
            return 0
        now = self.clock()
        today = int(now // 86400)
        with self.lock:
            if today != self.day:
                self.day, self.count = today, 0
            if self.count >= self.limit:
                return max(1, int((today + 1) * 86400 - now))
            self.count += 1
            return 0


def client_ip(client_host, forwarded_for, hops):
    """The visitor's address. Behind `hops` proxies the real address is that many entries from the right of
    X-Forwarded-For (each proxy adds the address it saw); entries to its left can be forged by the visitor,
    so they are never used. With no proxies, or too few entries, it is the address the connection came from."""
    if hops > 0 and forwarded_for:
        parts = [p.strip() for p in forwarded_for.split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return client_host or "unknown"


def _number(name, default):
    try:
        return int(os.environ.get(name, default))
    except ValueError:
        return default


class Guards:
    """The limits for one server, in one place."""

    def __init__(self, rate_per_min=30, daily_limit=0, max_concurrent=2, proxy_hops=0, allow_reindex=True,
                 lease_seconds=600.0, clock=time.monotonic, wall_clock=time.time):
        self.rate = RateLimiter(rate_per_min, 60.0, clock)
        self.daily = DailyCap(daily_limit, wall_clock)
        self.gate = ConcurrencyGate(max_concurrent, lease_seconds, clock)
        self.proxy_hops, self.allow_reindex = proxy_hops, allow_reindex

    @classmethod
    def from_env(cls, lease_seconds=600.0):
        """RAG_RATE_PER_MIN (questions per visitor per minute, default 30), RAG_DAILY_LIMIT (questions per day
        for everyone, default none), RAG_MAX_CONCURRENT (answers at once, default 2), RAG_PROXY_HOPS (how many
        proxies sit in front of the server, default 0), RAG_ALLOW_REINDEX (0 switches /api/reindex off).
        0 turns a limit off."""
        return cls(rate_per_min=_number("RAG_RATE_PER_MIN", 30), daily_limit=_number("RAG_DAILY_LIMIT", 0),
                   max_concurrent=_number("RAG_MAX_CONCURRENT", 2), proxy_hops=_number("RAG_PROXY_HOPS", 0),
                   allow_reindex=os.environ.get("RAG_ALLOW_REINDEX", "1") != "0", lease_seconds=lease_seconds)

    def visitor(self, client_host, forwarded_for=""):
        return client_ip(client_host, forwarded_for, self.proxy_hops)


# ---- the event log -------------------------------------------------------------------------------
events = logging.getLogger("rag.events")
events.propagate = False
events.addHandler(logging.NullHandler())  # nothing is written until setup_logging() is called
_salt = os.environ.get("RAG_LOG_SALT") or secrets.token_hex(8)
QUESTION_CHARS = 500  # longest question text kept in the log


def visitor_hash(ip):
    """A short code for a visitor, so the log can show repeat visitors without keeping addresses. It
    changes every time the server starts unless RAG_LOG_SALT is set."""
    return hashlib.sha256(f"{_salt}|{ip}".encode()).hexdigest()[:12]


def question_text(question):
    """The question as it goes in the log (RAG_LOG_QUESTIONS=0 keeps it out entirely)."""
    if os.environ.get("RAG_LOG_QUESTIONS", "1") == "0":
        return None
    return question if len(question) <= QUESTION_CHARS else question[:QUESTION_CHARS] + "..."


def setup_logging(directory=None, days=None):
    """Writes events to <directory>/events.jsonl, one file per UTC day, keeping `days` days (default 14,
    RAG_LOG_DAYS) and deleting older ones. The folder is logs/ unless RAG_LOG_DIR says otherwise.
    RAG_LOG=0 turns it off. Returns the handler (None if logging is off or the folder can't be written)."""
    if os.environ.get("RAG_LOG", "1") == "0":
        return None
    folder = Path(directory or os.environ.get("RAG_LOG_DIR", "logs"))
    keep = days if days is not None else _number("RAG_LOG_DAYS", 14)
    try:
        folder.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.TimedRotatingFileHandler(
            folder / "events.jsonl", when="midnight", backupCount=keep, encoding="utf-8", utc=True)
    except OSError as e:
        print(f"Could not write the log folder {folder} ({e}); nothing will be logged.", file=sys.stderr)
        return None
    handler.setFormatter(logging.Formatter("%(message)s"))
    events.addHandler(handler)
    events.setLevel(logging.INFO)
    return handler


def close_logging(handler):
    if handler is not None:
        events.removeHandler(handler)
        handler.close()


def log_event(event, **fields):
    """One JSON line: the time, the event name and the fields (fields that are None are left out). Never
    raises: a problem with the log must not break an answer."""
    try:
        record = {"ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"), "event": event,
                  **{k: v for k, v in fields.items() if v is not None}}
        events.info(json.dumps(record, ensure_ascii=False, default=str))
    except Exception:
        pass

import hashlib
import os
import re
import sys
import threading
import time
from pathlib import Path

import chromadb
import ollama
from docx import Document
from docx.table import Table
from pypdf import PdfReader

DOCS_DIR = Path("docs")
DB_DIR = "chroma_db"
EMBED_MODEL = "embeddinggemma"
CHAT_MODEL = "qwen3:8b"
CHUNK_SIZE = 800   # most characters in one chunk's text (the heading label is extra)
OVERLAP = 100      # shared characters between neighboring chunks (only for text with no line breaks to cut at)
TOP_K = int(os.environ.get("RAG_TOP_K", "4"))  # chunks retrieved per question (RAG_TOP_K tries other values)
HISTORY_MESSAGES = 6  # recent chat messages remembered (3 question/answer pairs)
# Qwen3 reasons before answering: better answers on tricky questions, but slower. On by default;
# turn it off by setting the environment variable RAG_THINK=0 before starting (e.g. on a slow machine).
THINK = os.environ.get("RAG_THINK", "1") != "0"
# A model call that goes quiet for this many seconds, or an answer that takes longer than this in total,
# is given up on. Ollama has been seen to stall for 36 to 40 minutes on one request, so not waiting
# forever is safer. RAG_MODEL_TIMEOUT changes it (raise it on a slow machine).
MODEL_TIMEOUT = float(os.environ.get("RAG_MODEL_TIMEOUT", "180"))
llm = ollama.Client(timeout=MODEL_TIMEOUT)

# Which files the "Sources:" line lists (see sources_to_show): the best match's file, plus another
# file only if its chunk is within SOURCE_WINDOW of the best chunk's distance and the answer shares
# at least SOURCE_MIN_SHARED meaningful words with it. Tuned on the daycare test questions.
SOURCE_WINDOW = 0.10
SOURCE_MIN_SHARED = 4
SOURCE_MIN_SHARED_BEST = 2  # fewer words needed for the best passage of each separate part of a question

# A question about several things is split and each part searched separately (see split_question).
# Set the environment variable RAG_SPLIT=0 to turn this off.
SPLIT_QUESTIONS = os.environ.get("RAG_SPLIT", "1") != "0"
SUB_TOP_K = 2    # passages kept per search when a question was split
MAX_PARTS = 4    # most parts a question is split into
FILLER_WORDS = set("""a an the and or but if of to in on at for from by with without as is are was were be been it
its this that these those you your we our us they them their he she his her not no yes can may will would should
could do does did have has had than then so such any all each per into out up down over under about after before
between more most other which who whom what when where how why also only just too very there here""".split())

# Phrases that mean the model found nothing in the documents.
DONT_KNOW = ["don't know", "do not know", "not sure", "not provide", "doesn't provide",
             "no information", "not mention", "doesn't mention", "not contain", "doesn't contain",
             "not specified", "not specify", "doesn't specify", "not stated", "doesn't say", "does not say"]

# Template blanks like [Daycare Name] or [$___]; ignores markdown links and checkboxes.
PLACEHOLDER = re.compile(r"\[(?![xX]\])[^\]\n]*[A-Za-z0-9_$][^\]\n]*\](?!\()")

SUPPORTED_SUFFIXES = {".pdf", ".txt", ".md", ".docx"}
SYNC_INTERVAL = 5   # seconds between checks of the docs folder while watching
# Bump this whenever the way files are read or chunked changes, so existing files get indexed again.
INDEX_VERSION = 1

client = chromadb.PersistentClient(path=DB_DIR)

index_lock = threading.RLock()  # only one indexing job runs at a time
index_state = {"last_sync": None, "last_change": None, "last_summary": None}
skipped = {}            # file key -> fingerprint of a version that was unreadable or empty (reported once)
fingerprint_cache = {}  # file key -> ((modified time, size), fingerprint)


def read_docx(path):
    lines = []
    for item in Document(str(path)).iter_inner_content():
        if isinstance(item, Table):
            for row in item.rows:
                lines.append(" | ".join(cell.text.strip() for cell in row.cells))
        elif item.text.strip():
            # keep headings as markdown headings so chunks keep their topic
            heading = item.style is not None and item.style.name.startswith("Heading")
            lines.append(("## " if heading else "") + item.text.strip())
    return "\n".join(lines)


def read_file(path):
    if path.suffix.lower() == ".docx":
        return read_docx(path)
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return path.read_text(encoding="utf-8", errors="ignore")


HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def window_chunks(text):
    """Fixed-size pieces with overlap: the last resort for text with no line breaks to cut at."""
    chunks, start = [], 0
    while start < len(text):
        chunk = text[start:start + CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
        start += CHUNK_SIZE - OVERLAP
    return chunks


def split_body(body):
    """Pieces of at most CHUNK_SIZE characters, cut between lines (the last line is repeated)."""
    if len(body) <= CHUNK_SIZE:
        return [body]
    lines = body.split("\n")
    if any(len(line) > CHUNK_SIZE for line in lines):
        return window_chunks(body)
    pieces, current = [], []
    for line in lines:
        if current and len("\n".join(current + [line])) > CHUNK_SIZE:
            pieces.append("\n".join(current).strip())
            last = current[-1]
            current = [last] if last.strip() and len(last) + len(line) < CHUNK_SIZE else []
        current.append(line)
    pieces.append("\n".join(current).strip())
    return [p for p in pieces if p]


def chunk_text(text, doc_name="document", headings=True):
    """Split text into chunks that each cover one section.

    With headings=True (markdown and Word files) the text is cut at its headings, and every chunk
    starts with a label like "Pricing and Packages > Boarding" so it says what it is about even
    when read alone. The first "# " heading is the document title; otherwise doc_name is used.
    Sections longer than CHUNK_SIZE are cut between lines. Without headings (PDF, txt) the whole
    text is one section, labelled with doc_name.
    """
    title, path, sections, body, have_title = doc_name, [], [], [], False

    def flush():
        section = "\n".join(body).strip()
        if section:
            sections.append((list(path), section))
        body.clear()

    for line in text.splitlines():
        match = HEADING.match(line) if headings else None
        if not match:
            body.append(line)
            continue
        flush()
        level, heading = len(match.group(1)), match.group(2).strip()
        if level == 1 and not have_title:
            title, have_title = heading, True
        else:
            path = path[:max(level - 2, 0)] + [heading]
    flush()

    chunks = []
    for section_path, section in sections:
        label = " > ".join([title] + section_path)
        chunks += [f"{label}\n{piece}" for piece in split_body(section)]
    return chunks


def embed(texts):
    return llm.embed(model=EMBED_MODEL, input=texts)["embeddings"]


def get_collection():
    return client.get_or_create_collection("docs", metadata={"hnsw:space": "cosine"})


def doc_key(path):
    """How a file is named in the index: its path inside docs/, with forward slashes."""
    return path.relative_to(DOCS_DIR).as_posix()


def list_docs():
    """{key: path} for every supported file under docs/ (Word's temporary ~$ lock files are skipped)."""
    return {doc_key(p): p for p in sorted(DOCS_DIR.rglob("*"))
            if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES and not p.name.startswith("~$")}


def file_fingerprint(key, path):
    """A short code for "this file's content, indexed with these settings".

    If the file changes, or CHUNK_SIZE, OVERLAP, the embedding model or INDEX_VERSION change, the
    code changes and the file is indexed again. The fingerprint is cached by size and modified time,
    so an unchanged file is not re-read every time the folder is checked.
    """
    stat = path.stat()
    stamp = (stat.st_mtime_ns, stat.st_size, f"{INDEX_VERSION}|{EMBED_MODEL}|{CHUNK_SIZE}|{OVERLAP}")
    cached = fingerprint_cache.get(key)
    if cached and cached[0] == stamp:
        return cached[1]
    digest = hashlib.sha256(f"{stamp[2]}|".encode())
    digest.update(path.read_bytes())
    fingerprint_cache[key] = (stamp, digest.hexdigest())
    return fingerprint_cache[key][1]


def index_file(collection, key, path, fingerprint):
    """Read one file and add its chunks to the index.

    Returns (number of chunks, warnings, status) where status is "ok", "empty" (no readable text)
    or "unreadable". Nothing is added unless the status is "ok".
    """
    try:
        text = read_file(path)
    except Exception as e:
        return 0, [f"{key}: could not be read and was skipped ({e})"], "unreadable"
    if not text.strip():
        return 0, [f"{key}: no readable text, skipped. "
                   "If it is a scanned PDF, it needs OCR or retyping."], "empty"
    warnings = []
    blanks = PLACEHOLDER.findall(text)
    if blanks:
        examples = ", ".join(blanks[:3])
        warnings.append(
            f"{key}: {len(blanks)} unfilled [bracket] placeholder(s), "
            f"for example {examples}. Indexed anyway; fill them in and it will be updated."
        )
    chunks = chunk_text(text, path.stem, path.suffix.lower() in {".md", ".docx"})
    if not chunks:
        return 0, warnings + [f"{key}: only headings, no text under them, skipped."], "empty"
    for i in range(0, len(chunks), 16):
        batch = chunks[i:i + 16]
        collection.add(
            # the fingerprint in the id means a new version never collides with the old one
            ids=[f"{key}-{fingerprint[:10]}-{i + j}" for j in range(len(batch))],
            documents=batch,
            embeddings=embed(batch),
            metadatas=[{"source": key, "file_hash": fingerprint}] * len(batch),
        )
    return len(chunks), warnings, "ok"


def indexed_files(collection):
    """{file key: set of fingerprints} for what is in the index right now."""
    found = {}
    for meta in collection.get(include=["metadatas"])["metadatas"]:
        found.setdefault(meta["source"], set()).add(meta.get("file_hash"))
    return found


def ingest():
    """Rebuild the whole index from scratch (use sync_docs to update only what changed)."""
    with index_lock:
        try:
            client.delete_collection("docs")
        except Exception:
            pass
        skipped.clear()
        fingerprint_cache.clear()
        collection = get_collection()

        files = list_docs()
        if not files:
            print("No .pdf, .docx, .txt or .md files found in the docs folder.")
            return

        warnings, total_chunks, indexed = [], 0, 0
        for key, path in files.items():
            fingerprint = file_fingerprint(key, path)
            count, file_warnings, status = index_file(collection, key, path, fingerprint)
            warnings += file_warnings
            if status == "ok":
                total_chunks += count
                indexed += 1
                print(f"{key}: {count} chunks")
            else:
                skipped[key] = fingerprint
        index_state["last_sync"] = time.time()
        index_state["last_change"] = time.time()
    print(f"\nDone. {indexed} of {len(files)} files indexed, {total_chunks} chunks.")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")


def sync_docs(settled=None, log=print):
    """Bring the index up to date with docs/: add new files, re-index changed ones, drop deleted ones.

    Only files that changed are re-read and re-embedded, so this is fast when little has changed.
    settled: optional set of file keys that are safe to read; any other file is left for the next
    round because it may still be being saved. Returns a summary dict.
    """
    summary = {"added": [], "updated": [], "removed": [], "unchanged": 0, "waiting": [], "warnings": []}
    with index_lock:
        collection = get_collection()
        files = list_docs()
        stored = indexed_files(collection)

        for key in sorted(set(stored) - set(files)):  # deleted from docs/
            collection.delete(where={"source": key})
            skipped.pop(key, None)
            fingerprint_cache.pop(key, None)
            summary["removed"].append(key)
            log(f"[index] removed {key}")

        for key, path in files.items():
            if settled is not None and key not in settled:
                summary["waiting"].append(key)
                continue
            try:
                fingerprint = file_fingerprint(key, path)
            except OSError:  # locked or vanished while we looked: try again next round
                summary["waiting"].append(key)
                continue
            if stored.get(key) == {fingerprint} or skipped.get(key) == fingerprint:
                summary["unchanged"] += 1  # up to date, or already reported as unreadable/empty
                continue

            # clear half-finished leftovers of this exact version, then add it
            collection.delete(where={"$and": [{"source": key}, {"file_hash": fingerprint}]})
            count, warnings, status = index_file(collection, key, path, fingerprint)
            summary["warnings"] += warnings
            for w in warnings:
                log(f"[index] warning: {w}")
            if status == "ok":
                skipped.pop(key, None)
                # only now remove the old version, so a question asked mid-update still finds something
                collection.delete(where={"$and": [{"source": key}, {"file_hash": {"$ne": fingerprint}}]})
                kind = "updated" if key in stored else "added"
                summary[kind].append(key)
                log(f"[index] {kind} {key}: {count} chunks")
            else:
                skipped[key] = fingerprint  # don't retry (or repeat the warning) until the file changes
                if status == "empty" and key in stored:  # the text is gone, so the old answers should be too
                    collection.delete(where={"source": key})
                    summary["removed"].append(key)
                    log(f"[index] removed {key} (no text left)")

        index_state["last_sync"] = time.time()
        if summary["added"] or summary["updated"] or summary["removed"]:
            index_state["last_change"] = time.time()
        index_state["last_summary"] = summary
    return summary


def stat_snapshot():
    """{file key: (modified time, size)} for every document; used to notice changes cheaply."""
    snapshot = {}
    for key, path in list_docs().items():
        try:
            stat = path.stat()
            snapshot[key] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            pass
    return snapshot


def watch(stop=None, interval=SYNC_INTERVAL, log=print):
    """Keep the index up to date until `stop` (a threading.Event) is set.

    Syncs once straight away, to catch up with changes made while nothing was running, then checks
    the docs folder every `interval` seconds. A changed file is only read once its size and modified
    time have stopped changing between two checks, so a file that is still being saved is not read
    half-written.
    """
    stop = stop or threading.Event()
    try:
        summary = sync_docs(log=log)
        log(f"[index] watching {DOCS_DIR}/ ({sum(map(len, (summary['added'], summary['updated'])))} files "
            f"indexed now, {summary['unchanged']} already up to date)")
    except Exception as e:  # never let the watcher thread die quietly
        log(f"[index] first sync failed: {e}")
    synced = previous = stat_snapshot()
    while not stop.wait(interval):
        try:
            current = stat_snapshot()
            if current != synced:  # something was added, changed or removed since the last full sync
                settled = {key for key, stamp in current.items() if previous.get(key) == stamp}
                summary = sync_docs(settled=settled, log=log)
                if not summary["waiting"]:
                    synced = current
            previous = current
        except Exception as e:
            log(f"[index] sync failed, will retry: {e}")


SPLIT_PROMPT = (
    "If the question below asks about two or more separate things, rewrite it as one short, "
    "complete question per thing, one per line. If it asks about only one thing, repeat it "
    "unchanged on a single line. Reply with the questions only, no numbering and no explanation.\n\n"
    "Question: {question}"
)


def split_question(question):
    """Break a question about several separate things into one question per thing.

    A single embedding of "when do you open, and how much is a bath?" lands between the two topics
    and tends to find only one of them, so each part is searched for separately. Uses a quick call
    to the chat model without thinking (about 0.2 seconds). Returns [question] if it can't split.
    """
    try:
        reply = llm.chat(
            model=CHAT_MODEL,
            messages=[{"role": "user", "content": SPLIT_PROMPT.format(question=question)}],
            think=False, options={"temperature": 0},
        )["message"]["content"]
    except Exception:
        return [question]
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip() for line in reply.splitlines()]
    parts = [line for line in lines if line]
    return parts[:MAX_PARTS] if parts else [question]


def retrieve(question, history=()):
    """Find the passages to answer from. Returns a list of {"source", "distance", "text", "group"},
    in the order they were found; "group" says which search found each one (0 is the question
    itself, 1 and up are its separate parts) so the Sources line can treat each topic fairly.

    A follow-up like "what about the second one?" searches poorly alone, so the previous question
    plus the new one is searched too. A question about several things is also split and each part
    searched on its own.
    """
    searches = [question]
    for m in reversed(history):
        if m["role"] == "user":
            searches.append(m["content"] + "\n" + question)
            break
    parts = split_question(question) if SPLIT_QUESTIONS else [question]
    compound = len(parts) > 1
    queries = searches + parts if compound else searches
    groups = [0] * len(searches) + (list(range(1, len(parts) + 1)) if compound else [])
    per_query = SUB_TOP_K if compound else (TOP_K if len(searches) == 1 else TOP_K // 2)

    results = get_collection().query(query_embeddings=embed(queries), n_results=per_query)
    found = {}  # passage text -> its entry, keeping the closest distance seen
    for group, docs, metas, dists in zip(groups, results["documents"], results["metadatas"], results["distances"]):
        for doc, meta, dist in zip(docs, metas, dists):
            if doc not in found or dist < found[doc]["distance"]:
                found[doc] = {"source": meta["source"], "distance": dist, "text": doc, "group": group}
    return list(found.values())


def answer_stream(question, history=()):
    """Returns (chunks, generator of answer text pieces).

    chunks are the retrieved passages, best match first, each {"source", "distance", "text", "group"};
    pass them with the finished answer to sources_to_show() to get the files to list.
    history is a list of {"role": "user"|"assistant", "content": ...} from earlier turns.
    """
    history = list(history)[-HISTORY_MESSAGES:]
    found = retrieve(question, history)  # in the order the passages were found
    chunks = sorted(found, key=lambda c: c["distance"])  # best match first
    context = "\n\n---\n\n".join(c["text"] for c in found)
    prompt = (
        "Answer using only the context below. "
        "If the context does not say, reply \"I don't know.\" "
        "If the context states a rule or fact that applies to the question, answer from it. "
        "Read all of the context before answering and take exceptions, grace periods and "
        "numeric limits (for example \"up to 4 hours\" versus \"over 4 hours\") into account. "
        "Answer directly and include every condition, alternative and exception the context gives "
        "for the answer, but leave out unrelated details. For a yes/no question that the context answers, begin with "
        "\"Yes\" or \"No\" and check that it agrees with the rest of your sentence "
        "(if the context says something is not allowed, the answer to \"is it allowed?\" is No). "
        "The question may refer back to the earlier conversation (for example \"that trail\" or \"it\"); "
        "work out what it refers to from the earlier messages, then look for the answer in the context.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )

    stream = llm.chat(
        model=CHAT_MODEL,
        messages=history + [{"role": "user", "content": prompt}],
        stream=True,
        think=THINK,  # False skips Qwen3's "thinking" step: much faster on CPU, less accurate
    )

    def pieces():
        # Thinking text arrives as pieces too (with no answer text), so a model stuck in a thinking
        # loop keeps the connection busy: the total time has to be checked as well as the silence.
        deadline = time.time() + MODEL_TIMEOUT
        for part in stream:
            if time.time() > deadline:
                raise TimeoutError(f"the model took longer than {MODEL_TIMEOUT:.0f} seconds to answer")
            yield part["message"]["content"]

    return chunks, pieces()


def says_dont_know(answer):
    text = answer.lower().replace("’", "'")
    return any(phrase in text for phrase in DONT_KNOW)


def gives_no_answer(answer):
    """True for a refusal like "I don't know". False for an answer that merely adds a caveat,
    such as "Saturday hours are 8 to 6. The context doesn't say what a bath costs."
    """
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", answer.strip()) if s.strip()]
    return bool(sentences) and (says_dont_know(sentences[0]) or all(says_dont_know(s) for s in sentences))


def content_words(text):
    """The meaningful words and numbers in a text (lower case, without common filler words)."""
    words = re.findall(r"[a-z0-9$%:.,'-]*[a-z0-9]", text.lower().replace("’", "'"))
    return {w for w in words if w not in FILLER_WORDS}


def sources_to_show(answer, chunks):
    """The files to list under an answer.

    None when the answer is a refusal ("I don't know"). Otherwise the file of the best-matching chunk,
    plus any other file whose chunk is nearly as close (SOURCE_WINDOW) and whose words the answer
    clearly reuses (SOURCE_MIN_SHARED words), which catches questions that need two documents.
    When a question was split into parts, each part's best match is also listed if the answer
    shares even a couple of words with it (SOURCE_MIN_SHARED_BEST), since that part was asked about.
    """
    if not chunks or gives_no_answer(answer):
        return []
    shown = [chunks[0]["source"]]
    answer_words = content_words(answer)
    groups = {}  # a split question has one group per part; each is judged against its own best match
    for chunk in chunks:  # best match first
        groups.setdefault(chunk.get("group", 0), []).append(chunk)
    for group_chunks in groups.values():
        group_best = group_chunks[0]
        for chunk in group_chunks:
            if chunk["source"] in shown or chunk["distance"] > group_best["distance"] + SOURCE_WINDOW:
                continue
            body = chunk["text"].split("\n", 1)[-1]  # skip the "Title > Section" label line
            needed = SOURCE_MIN_SHARED_BEST if chunk is group_best else SOURCE_MIN_SHARED
            if len(answer_words & content_words(body)) >= needed:
                shown.append(chunk["source"])
    return shown


def answer(question, history=()):
    """Answer a question in one go (no streaming) as {"answer": text, "sources": [files]}."""
    chunks, pieces = answer_stream(question, history)
    text = "".join(pieces).strip()
    return {"answer": text, "sources": sources_to_show(text, chunks)}


def when(timestamp):
    """A timestamp as local ISO time like 2026-10-20T14:05:09, or None."""
    return None if timestamp is None else time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(timestamp))


def index_status():
    """What is in the search index right now, as plain data."""
    with index_lock:
        collection = get_collection()
        files = indexed_files(collection)
        return {
            "files": len(files),
            "chunks": collection.count(),
            "documents": sorted(files),
            "last_sync": when(index_state["last_sync"]),
            "last_change": when(index_state["last_change"]),
        }


def ask(question, history=()):
    chunks, pieces = answer_stream(question, history)
    answer = ""
    for piece in pieces:
        print(piece, end="", flush=True)
        answer += piece
    print("\n\nSources:", ", ".join(sources_to_show(answer, chunks)) or "none")
    return answer


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else ""
    if command == "ingest":
        ingest()
    elif command == "sync":
        result = sync_docs()
        print(f"Done: {len(result['added'])} added, {len(result['updated'])} updated, "
              f"{len(result['removed'])} removed, {result['unchanged']} unchanged.")
    elif command == "watch":
        print(f"Watching {DOCS_DIR}/ for changes (press Ctrl+C to stop).")
        try:
            watch()
        except KeyboardInterrupt:
            print("\nStopped.")
    else:
        print("Ask a question (type 'quit' to exit).")
        history = []
        while True:
            q = input("\nYou: ").strip()
            if q.lower() in {"quit", "exit"}:
                break
            if q:
                print("\nAnswer: ", end="")
                a = ask(q, history)
                history += [{"role": "user", "content": q},
                            {"role": "assistant", "content": a}]

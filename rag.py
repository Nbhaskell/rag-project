import os
import re
import sys
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
TOP_K = 4          # chunks retrieved per question
HISTORY_MESSAGES = 6  # recent chat messages remembered (3 question/answer pairs)
# Qwen3 reasons before answering: better answers on tricky questions, but slower. On by default;
# turn it off by setting the environment variable RAG_THINK=0 before starting (e.g. on a slow machine).
THINK = os.environ.get("RAG_THINK", "1") != "0"

# Which files the "Sources:" line lists (see sources_to_show): the best match's file, plus another
# file only if its chunk is within SOURCE_WINDOW of the best chunk's distance and the answer shares
# at least SOURCE_MIN_SHARED meaningful words with it. Tuned on the daycare test questions.
SOURCE_WINDOW = 0.10
SOURCE_MIN_SHARED = 4
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

client = chromadb.PersistentClient(path=DB_DIR)


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
    return ollama.embed(model=EMBED_MODEL, input=texts)["embeddings"]


def ingest():
    try:
        client.delete_collection("docs")
    except Exception:
        pass
    collection = client.create_collection("docs", metadata={"hnsw:space": "cosine"})

    files = [
        p for p in DOCS_DIR.rglob("*")
        if p.suffix.lower() in {".pdf", ".txt", ".md", ".docx"}
        and not p.name.startswith("~$")  # Word's temporary lock files
    ]
    if not files:
        print("No .pdf, .docx, .txt or .md files found in the docs folder.")
        return

    warnings, total_chunks, indexed = [], 0, 0
    for file in files:
        try:
            text = read_file(file)
        except Exception as e:
            warnings.append(f"{file.name}: could not be read and was skipped ({e})")
            continue
        if not text.strip():
            warnings.append(
                f"{file.name}: no readable text, skipped. "
                "If it is a scanned PDF, it needs OCR or retyping."
            )
            continue
        blanks = PLACEHOLDER.findall(text)
        if blanks:
            examples = ", ".join(blanks[:3])
            warnings.append(
                f"{file.name}: {len(blanks)} unfilled [bracket] placeholder(s), "
                f"for example {examples}. Indexed anyway; fill them in and re-ingest."
            )

        chunks = chunk_text(text, file.stem, file.suffix.lower() in {".md", ".docx"})
        total_chunks += len(chunks)
        indexed += 1
        print(f"{file.name}: {len(chunks)} chunks")
        for i in range(0, len(chunks), 16):
            batch = chunks[i:i + 16]
            collection.add(
                ids=[f"{file.name}-{i + j}" for j in range(len(batch))],
                documents=batch,
                embeddings=embed(batch),
                metadatas=[{"source": file.name}] * len(batch),
            )
    print(f"\nDone. {indexed} of {len(files)} files indexed, {total_chunks} chunks.")
    if warnings:
        print(f"\n{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")


def answer_stream(question, history=()):
    """Returns (chunks, generator of answer text pieces).

    chunks are the retrieved passages, best match first, each {"source", "distance", "text"};
    pass them with the finished answer to sources_to_show() to get the files to list.
    history is a list of {"role": "user"|"assistant", "content": ...} from earlier turns.
    """
    history = list(history)[-HISTORY_MESSAGES:]
    # A follow-up like "what about the second one?" searches poorly alone, so
    # also search with the previous question, and merge both sets of chunks.
    searches = [question]
    for m in reversed(history):
        if m["role"] == "user":
            searches.append(m["content"] + "\n" + question)
            break

    collection = client.get_collection("docs")
    per_search = TOP_K if len(searches) == 1 else TOP_K // 2
    results = collection.query(query_embeddings=embed(searches), n_results=per_search)
    found = {}  # chunk text -> {"source", "distance", "text"}, in the order the chunks were found
    for docs, metas, dists in zip(results["documents"], results["metadatas"], results["distances"]):
        for doc, meta, dist in zip(docs, metas, dists):
            if doc not in found or dist < found[doc]["distance"]:
                found[doc] = {"source": meta["source"], "distance": dist, "text": doc}
    chunks = sorted(found.values(), key=lambda c: c["distance"])  # best match first

    context = "\n\n---\n\n".join(found)
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

    stream = ollama.chat(
        model=CHAT_MODEL,
        messages=history + [{"role": "user", "content": prompt}],
        stream=True,
        think=THINK,  # False skips Qwen3's "thinking" step: much faster on CPU, less accurate
    )
    return chunks, (part["message"]["content"] for part in stream)


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
    """
    if not chunks or gives_no_answer(answer):
        return []
    best = chunks[0]
    shown = [best["source"]]
    answer_words = content_words(answer)
    for chunk in chunks[1:]:
        if chunk["source"] in shown or chunk["distance"] > best["distance"] + SOURCE_WINDOW:
            continue
        body = chunk["text"].split("\n", 1)[-1]  # skip the "Title > Section" label line
        if len(answer_words & content_words(body)) >= SOURCE_MIN_SHARED:
            shown.append(chunk["source"])
    return shown


def ask(question, history=()):
    chunks, pieces = answer_stream(question, history)
    answer = ""
    for piece in pieces:
        print(piece, end="", flush=True)
        answer += piece
    print("\n\nSources:", ", ".join(sources_to_show(answer, chunks)) or "none")
    return answer


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "ingest":
        ingest()
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

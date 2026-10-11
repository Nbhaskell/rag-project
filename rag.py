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
CHUNK_SIZE = 800   # characters per chunk
OVERLAP = 100      # shared characters between neighboring chunks
TOP_K = 4          # chunks retrieved per question
HISTORY_MESSAGES = 6  # recent chat messages remembered (3 question/answer pairs)

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


def chunk_text(text):
    chunks, start = [], 0
    while start < len(text):
        chunk = text[start:start + CHUNK_SIZE].strip()
        if chunk:
            chunks.append(chunk)
        start += CHUNK_SIZE - OVERLAP
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

        chunks = chunk_text(text)
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
    """Returns (sources, generator of answer text pieces).

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
    seen, chunks, sources = set(), [], set()
    for docs, metas in zip(results["documents"], results["metadatas"]):
        for doc, meta in zip(docs, metas):
            if doc not in seen:
                seen.add(doc)
                chunks.append(doc)
                sources.add(meta["source"])
    sources = sorted(sources)

    context = "\n\n---\n\n".join(chunks)
    prompt = (
        "Answer using only the context below. "
        "If the answer isn't in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )

    stream = ollama.chat(
        model=CHAT_MODEL,
        messages=history + [{"role": "user", "content": prompt}],
        stream=True,
        think=False,  # skips Qwen3's long "thinking" step, much faster on CPU
    )
    return sources, (part["message"]["content"] for part in stream)


def ask(question, history=()):
    sources, pieces = answer_stream(question, history)
    answer = ""
    for piece in pieces:
        print(piece, end="", flush=True)
        answer += piece
    print("\n\nSources:", ", ".join(sources))
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

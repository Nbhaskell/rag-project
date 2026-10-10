import sys
from pathlib import Path

import chromadb
import ollama
from pypdf import PdfReader

DOCS_DIR = Path("docs")
DB_DIR = "chroma_db"
EMBED_MODEL = "embeddinggemma"
CHAT_MODEL = "qwen3:8b"
CHUNK_SIZE = 800   # characters per chunk
OVERLAP = 100      # shared characters between neighboring chunks
TOP_K = 4          # chunks retrieved per question

client = chromadb.PersistentClient(path=DB_DIR)


def read_file(path):
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

    files = [p for p in DOCS_DIR.rglob("*") if p.suffix.lower() in {".pdf", ".txt", ".md"}]
    if not files:
        print("No .pdf, .txt or .md files found in the docs folder.")
        return

    for file in files:
        chunks = chunk_text(read_file(file))
        print(f"{file.name}: {len(chunks)} chunks")
        for i in range(0, len(chunks), 16):
            batch = chunks[i:i + 16]
            collection.add(
                ids=[f"{file.name}-{i + j}" for j in range(len(batch))],
                documents=batch,
                embeddings=embed(batch),
                metadatas=[{"source": file.name}] * len(batch),
            )
    print("Done. Your documents are ready.")


def answer_stream(question):
    """Returns (sources, generator of answer text pieces)."""
    collection = client.get_collection("docs")
    results = collection.query(query_embeddings=embed([question]), n_results=TOP_K)
    chunks = results["documents"][0]
    sources = sorted({m["source"] for m in results["metadatas"][0]})

    context = "\n\n---\n\n".join(chunks)
    prompt = (
        "Answer using only the context below. "
        "If the answer isn't in the context, say you don't know.\n\n"
        f"Context:\n{context}\n\nQuestion: {question}"
    )

    stream = ollama.chat(
        model=CHAT_MODEL,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
        think=False,  # skips Qwen3's long "thinking" step, much faster on CPU
    )
    return sources, (part["message"]["content"] for part in stream)


def ask(question):
    sources, pieces = answer_stream(question)
    for piece in pieces:
        print(piece, end="", flush=True)
    print("\n\nSources:", ", ".join(sources))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "ingest":
        ingest()
    else:
        print("Ask a question (type 'quit' to exit).")
        while True:
            q = input("\nYou: ").strip()
            if q.lower() in {"quit", "exit"}:
                break
            if q:
                print("\nAnswer: ", end="")
                ask(q)

import os
import json
from pathlib import Path

from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

from config import DOCS_DIR, INDEX_DIR, INDEX_FILE, METADATA_FILE, EMBEDDING_MODEL_NAME


def load_documents(doc_dir: str):
    docs = []
    for root, _, files in os.walk(doc_dir):
        for fname in files:
            if fname.lower().endswith((".txt", ".md")):
                full_path = os.path.join(root, fname)
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    text = f.read()
                docs.append({"path": full_path, "text": text})
    return docs


def simple_chunk(text: str, max_chars: int = 1000, overlap: int = 200):
    """Simple character-based chunker."""
    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end]
        chunks.append(chunk)
        if end == n:
            break
        start = end - overlap
    return chunks


def main():
    os.makedirs(INDEX_DIR, exist_ok=True)

    print("Loading documents...")
    docs = load_documents(DOCS_DIR)
    print(f"Found {len(docs)} docs")

    print("Chunking documents...")
    all_chunks = []
    metadata = []
    for doc in docs:
        chunks = simple_chunk(doc["text"])
        for idx, chunk in enumerate(chunks):
            all_chunks.append(chunk)
            metadata.append({
                "path": doc["path"],
                "chunk_index": idx
            })

    print(f"Total chunks: {len(all_chunks)}")

    print("Loading embedding model...")
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    print("Embedding chunks...")
    embeddings = model.encode(all_chunks, show_progress_bar=True, convert_to_numpy=True)
    d = embeddings.shape[1]

    print("Building FAISS index...")
    index = faiss.IndexFlatL2(d)
    index.add(embeddings)

    index_path = os.path.join(INDEX_DIR, INDEX_FILE)
    faiss.write_index(index, index_path)
    print(f"Index written to {index_path}")

    metadata_path = os.path.join(INDEX_DIR, METADATA_FILE)
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump({
            "chunks": all_chunks,
            "metadata": metadata
        }, f, ensure_ascii=False, indent=2)
    print(f"Metadata written to {metadata_path}")


if __name__ == "__main__":
    main()

import os
import json
from typing import List

import faiss
import numpy as np
import requests
from fastapi import FastAPI
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from config import (
    INDEX_DIR,
    INDEX_FILE,
    METADATA_FILE,
    EMBEDDING_MODEL_NAME,
    OLLAMA_URL,
    OLLAMA_MODEL,
)

app = FastAPI()

# Load index + metadata + embedding model on startup
index = None
chunks: List[str] = []
metadata: List[dict] = []
embed_model: SentenceTransformer = None


class AskRequest(BaseModel):
    query: str
    top_k: int = 5


class AskResponse(BaseModel):
    answer: str
    context_chunks: List[str]


@app.on_event("startup")
def startup_event():
    global index, chunks, metadata, embed_model

    index_path = os.path.join(INDEX_DIR, INDEX_FILE)
    metadata_path = os.path.join(INDEX_DIR, METADATA_FILE)

    if not os.path.exists(index_path):
        raise RuntimeError(f"Index file not found at {index_path}. Run build_index.py first.")
    if not os.path.exists(metadata_path):
        raise RuntimeError(f"Metadata file not found at {metadata_path}. Run build_index.py first.")

    print("Loading FAISS index...")
    index = faiss.read_index(index_path)

    print("Loading metadata...")
    with open(metadata_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        chunks = data["chunks"]
        metadata.extend(data["metadata"])

    print("Loading embedding model...")
    embed_model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    print("Ready!")


def retrieve_relevant_chunks(query: str, top_k: int = 5) -> List[str]:
    query_vec = embed_model.encode([query], convert_to_numpy=True)
    D, I = index.search(query_vec, top_k)
    indices = I[0]
    retrieved = [chunks[i] for i in indices]
    return retrieved


def call_ollama(prompt: str) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False
    }
    resp = requests.post(OLLAMA_URL, json=payload, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    # Ollama returns {..., "response": "..."}
    return data.get("response", "")


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    retrieved_chunks = retrieve_relevant_chunks(req.query, top_k=req.top_k)

    #context_str = "\n\n---\n\n".join(retrieved_chunks)
    context_str = "++".join(retrieved_chunks)

    prompt = f"""You are an assistant that answers questions using ONLY the provided context.
If the answer cannot be found in the context, say you don't know.

Context:
{context_str}

Question:
{req.query}

Answer:"""

    answer = call_ollama(prompt)

    return AskResponse(
        answer=answer.strip(),
        context_chunks=retrieved_chunks
    )

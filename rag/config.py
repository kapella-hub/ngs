# config.py

# Folder where your docs live
DOCS_DIR = "docs"

# Where to store the FAISS index and metadata
INDEX_DIR = "index_store"
INDEX_FILE = "docs.index"
METADATA_FILE = "metadata.json"

# Embedding model (we’ll use a sentence-transformers model that works locally)
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# Ollama model name
OLLAMA_MODEL = "llama3"  # or "llama3.1:8b", etc.
OLLAMA_URL = "http://localhost:11434/api/generate"

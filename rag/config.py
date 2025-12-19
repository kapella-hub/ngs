# config.py

# Folder where your docs live
DOCS_DIR = "docs"

# Where to store the FAISS index and metadata
INDEX_DIR = "index_store"
INDEX_FILE = "docs.index"
METADATA_FILE = "metadata.json"

# Embedding model (we'll use a sentence-transformers model that works locally)
EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

# LLM Model (GGUF format for llama-cpp-python)
LLM_MODEL_NAME = "Phi-4-mini-instruct-Q4_K_M.gguf"
LLM_MODEL_PATH = "./models/Phi-4-mini-instruct-Q4_K_M.gguf"

# Ollama model name (for alternative Ollama-based inference)
OLLAMA_MODEL = "phi4:mini"  # or "llama3.2:3b", etc.
OLLAMA_URL = "http://localhost:11434/api/generate"

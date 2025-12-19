# Multi-stage Dockerfile for Local RAG System
# Includes embedding model and Mistral 7B LLM model

# Base image with Python 3.11
FROM python:3.11-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    tesseract-ocr \
    tesseract-ocr-eng \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
# Note: llama-cpp-python will build from source with CPU support
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/ ./app/
COPY static/ ./static/
COPY main.py .
COPY download_embedding_model.py .
COPY download_llm_model.py .

# Create necessary directories
RUN mkdir -p ./data/uploads ./data/chroma ./data/images ./models ./models/sentence-transformers

# Download embedding model (sentence-transformers/all-MiniLM-L6-v2)
# This will cache the model in ./models/sentence-transformers/
RUN echo "Downloading embedding model..." && \
    python download_embedding_model.py --cache-dir ./models/sentence-transformers

# Download Mistral 7B Instruct v0.2 Q4_K_M (~4.4GB)
# This is the best 8B-class model: high quality, publicly accessible
RUN echo "Downloading Mistral 7B Instruct v0.2 model..." && \
    python download_llm_model.py \
    --model-id TheBloke/Mistral-7B-Instruct-v0.2-GGUF \
    --filename mistral-7b-instruct-v0.2.Q4_K_M.gguf

# Create default .env file for Docker environment
RUN echo "# Docker Environment Configuration\n\
# Server\n\
APP_HOST=0.0.0.0\n\
APP_PORT=8001\n\
\n\
# Paths\n\
DATA_DIR=./data\n\
UPLOAD_DIR=./data/uploads\n\
VECTOR_DB_DIR=./data/chroma\n\
IMAGE_DIR=./data/images\n\
LLM_MODEL_PATH=./models/mistral-7b-instruct-v0.2.Q4_K_M.gguf\n\
\n\
# LLM Configuration\n\
LLM_CONTEXT_SIZE=4096\n\
LLM_N_THREADS=4\n\
LLM_N_GPU_LAYERS=0\n\
LLM_TEMPERATURE=0.1\n\
\n\
# Embeddings\n\
EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2\n\
EMBEDDING_DEVICE=cpu\n\
EMBEDDING_CACHE_DIR=./models/sentence-transformers\n\
\n\
# Network (offline mode for Docker)\n\
HF_OFFLINE=true\n\
HF_SSL_VERIFY=true\n\
\n\
# Chunking & Retrieval\n\
CHUNKING_STRATEGY=smart\n\
CHUNK_SIZE=800\n\
CHUNK_OVERLAP=200\n\
TOP_K=12\n\
\n\
# Logging\n\
LOG_LEVEL=INFO\n\
\n\
# ChromaDB\n\
ANONYMIZED_TELEMETRY=False" > .env

# Expose port
EXPOSE 8001

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# Run the application
CMD ["python", "main.py"]

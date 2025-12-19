# Offline Mode Setup Guide

This guide explains how to run the RAG application completely offline without internet access.

## Overview

The application requires two main components that normally need internet access:
1. **LLM Model** (e.g., Llama-3.2-3B.gguf) - GGUF format model for text generation
2. **Embedding Model** (sentence-transformers/all-MiniLM-L6-v2) - For document embeddings

## Step-by-Step Setup

### Step 1: Download the LLM Model (On a Machine with Internet)

Since your current machine cannot connect to Hugging Face due to SSL/network restrictions, you need to download the model on a different machine that has internet access.

#### Option A: Use the Download Script (Recommended)

On a machine **with internet access**:

```bash
cd /Users/P2799106/Projects/custom_llm01

# List available models
python download_llm_model.py --list-models

# Download the default model (Llama 3.2 3B Instruct Q4)
python download_llm_model.py

# Or download a different model
python download_llm_model.py --model-id bartowski/Llama-3.2-1B-Instruct-GGUF \
                              --filename Llama-3.2-1B-Instruct-Q4_K_M.gguf

# Or with proxy if needed
python download_llm_model.py --proxy http://proxy.example.com:8080
```

This will download the model to: `./models/`

#### Option B: Manual Download

Visit [Hugging Face](https://huggingface.co/models?search=gguf) and download a GGUF model:
- [bartowski/Llama-3.2-3B-Instruct-GGUF](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-GGUF) (Recommended)
- [bartowski/Llama-3.2-1B-Instruct-GGUF](https://huggingface.co/bartowski/Llama-3.2-1B-Instruct-GGUF) (Fastest)
- [TheBloke/Mistral-7B-Instruct-v0.2-GGUF](https://huggingface.co/TheBloke/Mistral-7B-Instruct-v0.2-GGUF)

Download the `.gguf` file and save it to the `models/` directory.

**Transfer the LLM Model:**

Copy the `.gguf` file from the machine with internet to your offline machine:
```
/Users/P2799106/Projects/custom_llm01/models/your-model.gguf
```

You can use:
- USB drive
- Shared network drive
- SCP/SFTP
- Any file transfer method available

### Step 2: Download the Embedding Model (On a Machine with Internet)

Since your current machine cannot connect to Hugging Face due to SSL/network restrictions, you need to download the model on a different machine that has internet access.

#### Option A: Use the Download Script (Recommended)

On a machine **with internet access**:

```bash
cd /Users/P2799106/Projects/custom_llm01

# Download the model
python download_embedding_model.py

# Or specify custom cache directory:
python download_embedding_model.py --cache-dir ./models/sentence-transformers
```

This will download the model to: `./models/sentence-transformers/`

#### Option B: Manual Download Using Python

On a machine **with internet access**, create a script:

```python
from sentence_transformers import SentenceTransformer
from pathlib import Path

# Set the cache directory
cache_dir = "./models/sentence-transformers"
Path(cache_dir).mkdir(parents=True, exist_ok=True)

# Download the model
model = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2",
    cache_folder=cache_dir
)

print(f"Model downloaded to: {cache_dir}")
```

Save as `download.py` and run:
```bash
python download.py
```

### Step 2: Transfer the Model Files

After downloading, you'll have a directory structure like:
```
models/
└── sentence-transformers/
    └── sentence-transformers_all-MiniLM-L6-v2/
        ├── config.json
        ├── config_sentence_transformers.json
        ├── model.safetensors (or pytorch_model.bin)
        ├── modules.json
        ├── sentence_bert_config.json
        ├── special_tokens_map.json
        ├── tokenizer_config.json
        ├── tokenizer.json
        └── vocab.txt
```

**Copy the entire `models/sentence-transformers/` directory** from the machine with internet to your offline machine at:
```
/Users/P2799106/Projects/custom_llm01/models/sentence-transformers/
```

You can use:
- USB drive
- Shared network drive
- SCP/SFTP
- Any file transfer method available

### Step 3: Configure for Offline Mode

On your **offline machine**, update your `.env` file:

```env
# LLM configuration (adjust to match your downloaded model)
LLM_MODEL_PATH=./models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
LLM_N_GPU_LAYERS=0
LLM_N_THREADS=4

# Embedding configuration
EMBEDDING_DEVICE=cpu
EMBEDDING_CACHE_DIR=./models/sentence-transformers

# Enable offline mode - IMPORTANT!
HF_OFFLINE=true

# Disable ChromaDB telemetry to prevent errors in offline mode
ANONYMIZED_TELEMETRY=False
```

**For Apple Silicon (M1/M2/M3) with GPU acceleration:**

If you want to use GPU acceleration on your M1/M2/M3 Mac, configure for Metal and MPS:

```env
# LLM configuration with Metal/GPU acceleration
LLM_MODEL_PATH=./models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
LLM_N_GPU_LAYERS=99  # Use all available GPU layers (Metal)
LLM_N_THREADS=4

# Embedding configuration with MPS (Metal Performance Shaders)
EMBEDDING_DEVICE=mps  # Changed from 'cpu' to 'mps'
EMBEDDING_CACHE_DIR=./models/sentence-transformers

# Enable offline mode - IMPORTANT!
HF_OFFLINE=true

# Disable ChromaDB telemetry to prevent errors in offline mode
ANONYMIZED_TELEMETRY=False
```

**Note:** GPU acceleration requires rebuilding llama-cpp-python with Metal support:
```bash
CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python --no-cache-dir --force-reinstall
```

This provides 2-4x faster inference on M1/M2/M3 Macs.

### Step 4: Verify the Setup

Check that the model files exist:

```bash
ls -la /Users/P2799106/Projects/custom_llm01/models/sentence-transformers/
```

You should see a subdirectory like `sentence-transformers_all-MiniLM-L6-v2` with model files inside.

### Step 5: Test the Application

Start the application:

```bash
python main.py
```

You should see logs like:
```
INFO - Loading embedding model: sentence-transformers/all-MiniLM-L6-v2
INFO - Device: cpu
INFO - Using offline mode - models must be pre-downloaded
INFO - Using cache directory: /Users/P2799106/Projects/custom_llm01/models/sentence-transformers
INFO - Embedding model loaded successfully
```

**If you see SSL/network errors**, the offline mode is not properly configured.

## Troubleshooting

### Error: "Failed to load embedding model"

**Cause**: Model files are not in the correct location or offline mode is not enabled.

**Solution**:
1. Verify `HF_OFFLINE=true` is in your `.env` file
2. Check that model files exist in the cache directory
3. Ensure the directory path in `EMBEDDING_CACHE_DIR` matches the actual location

### Error: Still seeing Hugging Face connection attempts

**Cause**: The `HF_OFFLINE` environment variable is not being set.

**Solution**:
1. Make sure your `.env` file contains `HF_OFFLINE=true` (not `HF_OFFLINE=True`)
2. Restart the application completely
3. Check that the app is reading from the correct `.env` file

### Model not found in cache

**Cause**: The model wasn't fully downloaded or transferred.

**Solution**:
1. Re-download the model on the internet-connected machine
2. Verify all files were copied (especially `modules.json` and `config.json`)
3. Check file permissions on the offline machine

### Different Model Name

If you want to use a different embedding model:

1. Download it on the internet-connected machine:
   ```bash
   python download_embedding_model.py --model "model-name-here"
   ```

2. Update your `.env`:
   ```env
   EMBEDDING_MODEL_NAME=model-name-here
   ```

## Quick Reference

### Required Directory Structure
```
/Users/P2799106/Projects/custom_llm01/
├── .env (contains HF_OFFLINE=true)
├── models/
│   ├── Llama-3.2-3B-Instruct-Q4_K_M.gguf (your LLM model)
│   └── sentence-transformers/
│       └── sentence-transformers_all-MiniLM-L6-v2/
│           ├── config.json
│           ├── modules.json
│           ├── model.safetensors
│           └── ... (other model files)
└── ... (rest of application)
```

### Minimal .env for Offline Mode
```env
# Enable offline mode
HF_OFFLINE=true
EMBEDDING_CACHE_DIR=./models/sentence-transformers

# LLM settings (adjust to match your downloaded model)
LLM_MODEL_PATH=./models/Llama-3.2-3B-Instruct-Q4_K_M.gguf

# Device settings
EMBEDDING_DEVICE=cpu
LLM_N_GPU_LAYERS=0

# Chunking & Retrieval (optional - defaults shown)
CHUNKING_STRATEGY=smart
CHUNK_SIZE=800
CHUNK_OVERLAP=200
TOP_K=8

# Disable ChromaDB telemetry
ANONYMIZED_TELEMETRY=False
```

## Summary

To run completely offline:
1. ✅ Download LLM model (GGUF format) on a machine with internet using `python download_llm_model.py`
2. ✅ Download embedding model on a machine with internet using `python download_embedding_model.py`
3. ✅ Transfer both models to offline machine (LLM: `models/*.gguf`, Embeddings: `models/sentence-transformers/`)
4. ✅ Set `HF_OFFLINE=true` in `.env`
5. ✅ Set `LLM_MODEL_PATH` and `EMBEDDING_CACHE_DIR` in `.env`
6. ✅ Start the application with `python main.py`

The application will now run without any internet connection required.

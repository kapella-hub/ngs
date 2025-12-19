# Local RAG System

A complete local RAG (Retrieval-Augmented Generation) system using llama-cpp-python, ChromaDB, and FastAPI. This system runs entirely locally without requiring external API services.

## Features

- **Local LLM**: Uses llama-cpp-python to run .gguf models locally
- **Local Embeddings**: sentence-transformers for document embeddings
- **Persistent Vector Store**: ChromaDB for document storage and retrieval
- **Multi-format Support**: PDF, Word, PowerPoint, Excel, CSV, HTML, Text, Markdown, and Images (OCR)
- **CPU/GPU Switching**: Configure via .env file without code changes
- **Cross-platform**: Works on Windows, macOS, and Linux
- **RESTful API**: FastAPI-based endpoints for document upload and question answering

## Prerequisites

### System Requirements

- Python 3.11+
- At least 8GB RAM (16GB+ recommended for larger models)
- For GPU acceleration:
  - NVIDIA GPU with CUDA support (for CUDA)
  - Apple Silicon (for Metal/MPS)

### Required Software

**Tesseract OCR** (for image text extraction):

- **Windows**: Download installer from [https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)
- **Linux**: `sudo apt-get install tesseract-ocr`
- **macOS**: `brew install tesseract`

## Docker Deployment (Recommended)

The easiest way to run the Local RAG System is using Docker, which automatically handles all dependencies, downloads models, and sets up the environment.

### Prerequisites

- **Docker**: Install [Docker Desktop](https://www.docker.com/products/docker-desktop) (Windows/macOS) or Docker Engine (Linux)
- **Docker Compose**: Included with Docker Desktop, or install separately on Linux
- **8GB+ RAM**: Required for the Mistral 7B model
- **10GB+ disk space**: For Docker image, models, and data

### Quick Start

**1. Build the Docker image** (this will download models during build):

```bash
docker-compose build
```

**Note**: The build process will:
- Install all system dependencies (Python, Tesseract OCR, build tools)
- Install all Python packages
- Download the embedding model (~90MB)
- Download Mistral 7B Instruct v0.2 Q4_K_M model (~4.4GB)
- This may take 15-30 minutes depending on your internet connection

**2. Start the container**:

```bash
docker-compose up -d
```

**3. Access the application**:

- **Web UI**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs
- **Health Check**: http://localhost:8000/health

**4. View logs**:

```bash
docker-compose logs -f
```

**5. Stop the container**:

```bash
docker-compose down
```

### Docker Configuration

#### Volume Mounts

The following directories are mounted as volumes for data persistence:

- `./data/chroma`: Vector database (persistent storage)
- `./data/uploads`: Uploaded documents
- `./data/images`: Extracted images from documents

Your data persists across container restarts and rebuilds.

#### Resource Limits

Default resource allocation (adjust in `docker-compose.yml` if needed):

- **CPU**: 2-4 cores
- **Memory**: 4-8GB
- **Recommended**: 16GB+ system RAM for comfortable operation

#### Environment Variables

The Docker container uses these default settings:

```bash
# LLM Model
LLM_MODEL_PATH=./models/mistral-7b-instruct-v0.2.Q4_K_M.gguf
LLM_CONTEXT_SIZE=4096
LLM_MAX_TOKENS=512
LLM_N_THREADS=4
LLM_N_GPU_LAYERS=0  # CPU-only by default

# Embeddings
EMBEDDING_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
EMBEDDING_DEVICE=cpu

# Chunking
CHUNKING_STRATEGY=smart
CHUNK_SIZE=800
CHUNK_OVERLAP=200
TOP_K=8
```

To override settings, edit `docker-compose.yml` or mount a custom `.env` file:

```yaml
volumes:
  - ./custom.env:/app/.env
```

### Alternative Docker Commands

**Build without docker-compose**:

```bash
docker build -t local-rag-system .
```

**Run without docker-compose**:

```bash
docker run -d \
  --name local-rag-system \
  -p 8000:8000 \
  -v $(pwd)/data/chroma:/app/data/chroma \
  -v $(pwd)/data/uploads:/app/data/uploads \
  -v $(pwd)/data/images:/app/data/images \
  local-rag-system
```

### GPU Support in Docker

To enable GPU acceleration in Docker, you need:

1. **NVIDIA GPU**: Install [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html)
2. **Rebuild with GPU support**: Modify Dockerfile to install llama-cpp-python with CUDA support
3. **Update docker-compose.yml**: Add GPU configuration

Example GPU configuration for docker-compose.yml:

```yaml
services:
  rag-system:
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

Then set in environment: `LLM_N_GPU_LAYERS=99`

### Troubleshooting Docker

**Build fails due to network issues**:
```bash
# Use proxy during build
docker build --build-arg HTTP_PROXY=http://proxy:8080 -t local-rag-system .
```

**Container exits immediately**:
```bash
# Check logs
docker-compose logs
```

**Out of memory**:
- Increase Docker Desktop memory allocation (Settings > Resources)
- Reduce `LLM_N_THREADS` or use a smaller model

**Port 8000 already in use**:
```bash
# Change port mapping in docker-compose.yml
ports:
  - "8080:8000"  # Access at http://localhost:8080
```

---

## Manual Installation

### 1. Clone or Navigate to Project Directory

```bash
cd llama_chat01
```

### 2. Create Virtual Environment

```bash
python -m venv venv

# Activate virtual environment
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate
```

### 3. Install Dependencies

**For CPU-only:**
```bash
pip install -r requirements.txt
```

**For GPU (CUDA) on Linux/macOS:**
```bash
CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python==0.2.32
pip install -r requirements.txt
```

**For GPU (CUDA) on Windows:**
```bash
# Use pre-built wheels or follow llama-cpp-python documentation
pip install llama-cpp-python==0.2.32 --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu121
pip install -r requirements.txt
```

**For Apple Silicon (Metal):**
```bash
CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python==0.2.32
pip install -r requirements.txt
```

### 4. Download LLM Model

#### Option A: Use the Download Script (Recommended)

List available models:
```bash
python download_llm_model.py --list-models
```

Download a model (default: Llama 3.2 3B Instruct Q4):
```bash
python download_llm_model.py
```

Or specify a different model:
```bash
# Download Llama 3.2 1B (fastest, smallest)
python download_llm_model.py --model-id bartowski/Llama-3.2-1B-Instruct-GGUF \
                              --filename Llama-3.2-1B-Instruct-Q4_K_M.gguf

# Download Llama 3.2 8B (better quality)
python download_llm_model.py --model-id bartowski/Llama-3.2-8B-Instruct-GGUF \
                              --filename Llama-3.2-8B-Instruct-Q4_K_M.gguf

# Download with proxy
python download_llm_model.py --proxy http://proxy.example.com:8080
```

The model will be saved to `./models/` directory.

#### Option B: Manual Download

Download a .gguf format model file from:
- [Hugging Face](https://huggingface.co/models?search=gguf)
- [TheBloke's quantized models](https://huggingface.co/TheBloke)
- [Bartowski's quantized models](https://huggingface.co/bartowski)

Recommended models:
- **Llama 3.2 3B Instruct**: Best for CPU, good balance of speed and quality
- **Llama 3.2 1B Instruct**: Fastest, smallest
- **Llama 3.2 8B Instruct**: Better quality, requires more resources
- **Mistral 7B Instruct**: Excellent performance

Place the downloaded .gguf file in the `models/` directory

### 5. Configure Environment

Copy the template and edit:
```bash
# Windows
copy .env.template .env

# Linux/macOS
cp .env.template .env
```

Edit `.env` with your settings:

**For CPU-only mode:**
```ini
LLM_MODEL_PATH=./models/llama-model.gguf
LLM_N_GPU_LAYERS=0
LLM_N_THREADS=4
EMBEDDING_DEVICE=cpu
```

**For GPU mode:**
```ini
LLM_MODEL_PATH=./models/llama-model.gguf
LLM_N_GPU_LAYERS=35  # Set to number of layers in your model
LLM_N_THREADS=4
EMBEDDING_DEVICE=cuda  # or 'mps' for Apple Silicon
```

## Running the Application

Start the server:
```bash
python main.py
```

The application will be available at: `http://localhost:8000`

## Data Persistence

### Automatic Data Persistence

All uploaded documents and their vector embeddings are **automatically persisted to disk** and will remain available after restarting the application. You don't need to re-upload your documents after a restart.

**How it works:**
- Documents are stored in ChromaDB's persistent storage at `./data/chroma/`
- When you upload documents, they are:
  1. Processed and split into chunks
  2. Converted to vector embeddings
  3. Saved to disk in the ChromaDB database
- When you restart the application, all previously uploaded documents are automatically loaded from disk

**Storage Location:**
```
./data/
├── chroma/              # Persistent vector database
│   ├── chroma.sqlite3   # Metadata database
│   └── [collection_id]/ # Vector data and indices
└── uploads/             # Original uploaded files (temporary)
```

**Key Points:**
- ✅ Documents persist across restarts
- ✅ No need to re-upload documents
- ✅ Vector embeddings are preserved
- ✅ Automatic backup by copying `./data/chroma/` directory
- ⚠️ Deleting `./data/chroma/` will remove all indexed documents

**To reset the database:**
```bash
# Stop the application first
rm -rf ./data/chroma/
# Restart the application - it will create a fresh database
```

## Web UI

The application provides a modern web interface with two pages: a main chat interface and a dedicated document management page.

### Access the Interface

**Main Chat Page:**
```
http://localhost:8000
```

**Document Management Page:**
```
http://localhost:8000/manage
```

### Main Chat Page Features

**💬 Ask Questions**
- **Clean Chat Interface**: Focus on asking questions and getting answers
- **Instant Answers**: Get AI-generated answers based on your uploaded documents
- **Conversation History**: See your question and answer history in the session
- **Easy Input**: Type your question and press Enter or click Send
- **Real-time Responses**: Visual feedback while the AI processes your question
- **Markdown Formatting**: Answers are beautifully formatted with bold text, lists, and structure

**📊 System Status**
- **Chunks Indexed**: See how many document chunks are currently in the system
- **Health Status**: Real-time system health indicator (🟢 Online / 🔴 Offline)
- **Quick Access**: "Manage Documents" button to navigate to file management

**🗑️ Clear All Data**
- One-click button to clear all documents and start fresh
- Confirmation dialog to prevent accidental deletion

### Manage Documents Page Features

**📤 Upload Documents**
- **Large Upload Area**: Spacious drag-and-drop zone for easy file uploads
- **Drag & Drop**: Simply drag files from your computer and drop them in the upload area
- **Browse Files**: Click "Browse Files" to select files from your system
- **Multiple Files**: Upload multiple documents at once
- **Real-time Feedback**: See upload progress and success/failure status instantly
- **File Preview**: View selected files with their sizes before uploading
- **Supported Formats**: TXT, MD, PDF, DOCX, PPTX, XLS/XLSX, HTML, CSV, and Images (with OCR)

**🌐 Add from URL**
- **Fetch Web Content**: Add content directly from web pages or PDF documents by entering a URL
- **Automatic Text Extraction**: Extracts and cleans text content from HTML pages and PDF documents
- **PDF Support**: Automatically detects and processes PDF files from URLs (same as file upload)
- **Link Crawling**: Optionally follow and ingest links found on HTML pages
  - Enable "Follow and ingest links found on the page" to crawl multiple pages
  - Set maximum crawl depth (1-5): controls how many levels deep to follow links
  - Option to restrict crawling to the same domain only
- **Stop Ingestion**: Cancel long-running crawl operations mid-process
  - "Stop Ingestion" button appears when crawling multiple pages
  - Gracefully stops after processing the current URL
  - Preserves already-processed content
- **Real-time Processing**: Fetches, extracts, chunks, and indexes content automatically
- **Persistent Storage**: URLs are stored with their content and can be refreshed later
- **Last Fetched Timestamp**: Track when content was last retrieved from each URL
- **Crawling Statistics**: See how many URLs were successfully processed and failed

**📋 View Uploaded Files**
- **Complete File List**: See all uploaded files and URLs in a clean table
- **Upload Dates**: View when each file was uploaded (ISO timestamp format)
- **Chunk Counts**: See how many chunks each document was split into
- **File Management**: Each file has its own action buttons
- **URL Identification**: URLs are marked with 🌐 icon, files with 📄 icon
- **Search Functionality**: Quickly find documents by searching filenames or URLs
- **Pagination**: View files 10 at a time with easy page navigation

**🔄 Refresh URLs**
- **Update URL Content**: Re-fetch content from web pages to get latest updates
- **One-Click Refresh**: Click the "🔄 Refresh" button next to any URL
- **Automatic Re-indexing**: Old content is removed and new content is indexed automatically
- **Updated Timestamp**: Track when each URL was last refreshed

**🗑️ Delete Individual Files**
- **Selective Deletion**: Delete specific files or URLs without affecting others
- **Confirmation Dialog**: Prevents accidental deletion
- **Instant Update**: File list refreshes automatically after deletion
- **Preserves Questions**: Deleting a file doesn't affect your chat history

**📊 Statistics**
- **Total Files**: Count of unique files in the system
- **Total Chunks**: Total number of indexed chunks across all files
- **Health Status**: Real-time system health indicator

**🔙 Navigation**
- **Back to Chat**: Quick link to return to the main chat interface

### Using the Web UI

#### 1. Upload and Manage Documents

Navigate to the Manage Documents page (click "Manage Documents" from the main page or go to `http://localhost:8000/manage`):

1. **Upload Files**:
   - Drag files into the large upload area or click "Browse Files"
   - Review the selected files with their sizes
   - Click "Upload Files" to process them
   - Wait for the success confirmation
   - Files will appear in the "Uploaded Files" table below

2. **Add from URL**:
   - Enter a URL in the "Add from URL" section (e.g., https://example.com/page)
   - **Optional**: Enable link crawling to ingest multiple pages:
     - Check "🔗 Follow and ingest links found on the page"
     - Set maximum crawl depth (1-5): higher = more pages
     - Choose whether to stay within the same domain
   - Click "Add URL" to fetch and process the content
   - **Stop if needed**: If crawling takes too long:
     - Click the "⏹️ Stop Ingestion" button that appears during crawling
     - The operation will stop gracefully after the current URL
     - Already-processed content will be saved
   - Wait for the success confirmation with crawling statistics
   - The URL(s) will appear in the "Uploaded Files" table with a 🌐 icon

3. **View Your Files**:
   - See all uploaded files and URLs in the table
   - URLs are marked with 🌐, files with 📄
   - Check upload dates and chunk counts
   - Use the search box to find specific files or URLs
   - Navigate through pages if you have many documents

4. **Refresh URL Content**:
   - Click the "🔄 Refresh" button next to any URL
   - Confirm the refresh operation
   - The system will re-fetch the latest content from the URL
   - Updated timestamp and chunk count will be displayed

5. **Delete Unwanted Files**:
   - Click the "🗑️ Delete" button next to any file or URL
   - Confirm the deletion in the dialog
   - The file/URL and all its chunks will be removed
   - The list updates automatically

#### 2. Ask Questions

Return to the main chat page (click "← Back to Chat" or go to `http://localhost:8000`):

1. **Type Your Question**:
   - Use the input field at the bottom of the chat area
   - Ask anything about your uploaded documents

2. **Get Answers**:
   - Press Enter or click "Send"
   - Wait for the AI to generate an answer
   - Answers include relevant information with markdown formatting
   - Continue with follow-up questions

3. **Monitor System**:
   - Check the "Chunks Indexed" count in the stats bar
   - Verify the system status shows "🟢 Online"

### Benefits of the Web UI

- **No Command Line Required**: User-friendly graphical interface
- **Dedicated File Management**: Separate page for organizing your documents
- **Individual File Control**: Delete specific files without affecting others
- **Upload Date Tracking**: See when each document was added
- **Visual Feedback**: See exactly what's happening with uploads, queries, and deletions
- **Easy Navigation**: Switch between chat and management pages seamlessly
- **Better Organization**: Clean separation between asking questions and managing files
- **No API Knowledge Needed**: Anyone can use it without technical expertise

## API Usage (Advanced)

For developers who want programmatic access, the REST API is available.

Interactive API documentation: `http://localhost:8000/docs`

### 1. Upload Documents

Upload multiple documents at once:

```bash
curl -X POST "http://localhost:8000/documents/upload" \
  -H "accept: application/json" \
  -H "Content-Type: multipart/form-data" \
  -F "files=@document1.pdf" \
  -F "files=@document2.docx" \
  -F "files=@document3.txt"
```

**Response:**
```json
{
  "batch_id": "550e8400-e29b-41d4-a716-446655440000",
  "file_count": 3,
  "success_count": 3,
  "failed_count": 0,
  "total_chunks": 45,
  "failed_files": []
}
```

### 2. Ask Questions

Ask a question about the uploaded documents:

```bash
curl -X POST "http://localhost:8000/ask" \
  -H "accept: application/json" \
  -H "Content-Type: application/json" \
  -d '{"query": "What is the main topic of the documents?", "top_k": 5}'
```

**Response:**
```json
{
  "answer": "The main topic of the documents is...",
  "conversation_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "images": [
    "/images/batch123_0.png",
    "/images/doc456_1.jpg"
  ]
}
```

**Response fields:**
- `answer`: The generated answer text (markdown formatted)
- `conversation_id`: Unique ID for this conversation (use in follow-up questions)
- `images`: Array of image URLs relevant to the answer (empty if no images)

**Note:** When images are present, they are displayed automatically in the Web UI. You can access images directly at the returned URLs.

### 3. View Images

Images associated with answers can be accessed directly:

```bash
curl "http://localhost:8000/images/batch123_0.png" --output image.png
```

Or open in browser: `http://localhost:8000/images/batch123_0.png`

**Features:**
- Images are automatically served when referenced in answers
- Click images in the UI to view full size
- Supports: PNG, JPG, JPEG, TIF, TIFF formats

### 4. Get Statistics

Check how many documents are indexed:

```bash
curl -X GET "http://localhost:8000/stats"
```

**Response:**
```json
{
  "collection_name": "documents",
  "document_count": 150
}
```

### 4. List Uploaded Files

Get a list of all uploaded files with metadata:

```bash
curl -X GET "http://localhost:8000/documents/list"
```

**Response:**
```json
{
  "files": [
    {
      "filename": "document1.pdf",
      "upload_date": "2025-11-16T04:28:26.147707",
      "chunk_count": 45
    },
    {
      "filename": "document2.txt",
      "upload_date": "2025-11-16T04:30:15.234891",
      "chunk_count": 12
    }
  ],
  "total_files": 2
}
```

### 5. Delete a Specific File

Delete a specific file and all its chunks:

```bash
curl -X DELETE "http://localhost:8000/documents/file/document1.pdf"
```

**Response:**
```json
{
  "status": "success",
  "message": "Successfully deleted file: document1.pdf",
  "deleted_count": 45
}
```

**Note:** The filename must be URL-encoded if it contains special characters:
```bash
curl -X DELETE "http://localhost:8000/documents/file/my%20document.pdf"
```

### 6. Upload from URL

Fetch and ingest content from a web page or PDF document:

**Basic usage (single page):**
```bash
curl -X POST "http://localhost:8000/documents/upload-url" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/page"}'
```

**With link crawling enabled:**
```bash
curl -X POST "http://localhost:8000/documents/upload-url" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/page",
    "follow_links": true,
    "max_depth": 1,
    "same_domain_only": true
  }'
```

**Parameters:**
- `url` (required): The starting URL to fetch and ingest
- `follow_links` (optional, default: false): Enable crawling to follow and ingest linked pages
- `max_depth` (optional, default: 1, range: 1-5): Maximum crawl depth. Only applies when follow_links=true
  - `1` = only the start page
  - `2` = start page + pages it links to
  - `3` = start page + linked pages + pages they link to, etc.
- `same_domain_only` (optional, default: true): Restrict crawling to the same domain. Only applies when follow_links=true

**Response:**
```json
{
  "success": true,
  "source_url": "https://example.com/page",
  "total_chunks": 15,
  "urls_processed": 1,
  "urls_failed": 0,
  "last_fetched": "2025-11-16T15:06:46.986680",
  "error": null
}
```

**Response with crawling (multiple URLs):**
```json
{
  "success": true,
  "source_url": "https://example.com/page",
  "total_chunks": 47,
  "urls_processed": 5,
  "urls_failed": 1,
  "cancelled": false,
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "last_fetched": "2025-11-16T15:06:46.986680",
  "error": null
}
```

**Response fields:**
- `success`: Whether the operation completed successfully
- `source_url`: The starting URL that was ingested
- `total_chunks`: Number of text chunks created from all processed URLs
- `urls_processed`: Number of URLs successfully crawled and processed
- `urls_failed`: Number of URLs that failed during crawling
- `cancelled`: True if the operation was cancelled by the user (only present when crawling)
- `job_id`: Unique identifier for the crawling job, used for cancellation (only present when crawling with depth > 1)
- `last_fetched`: ISO timestamp of when the content was fetched
- `error`: Error message if the operation failed

**Features:**
- Automatically extracts text from HTML pages and PDF documents
- **PDF Support**: Downloads and processes PDF files from URLs (application/pdf content type)
- **Link Crawling**: Follow and ingest multiple pages from a website (HTML only)
- **Cancellable Operations**: Long-running crawls can be stopped mid-process
- Stores URL(s) as the source for future reference
- Can be refreshed to get updated content
- Supports http:// and https:// URLs
- Domain filtering to prevent crawling external sites (HTML crawling)
- Duplicate URL detection to avoid re-processing pages

### 7. Refresh URL Content

Re-fetch and update content from a previously added URL:

```bash
curl -X POST "http://localhost:8000/documents/refresh-url/https%3A%2F%2Fexample.com%2Fpage"
```

**Note:** The URL must be URL-encoded in the path.

**Response:**
```json
{
  "success": true,
  "source_url": "https://example.com/page",
  "total_chunks": 16,
  "last_fetched": "2025-11-16T16:30:15.234891",
  "error": null
}
```

**Features:**
- Deletes old content from the URL
- Fetches fresh content from the web
- Re-indexes the updated content
- Updates the last_fetched timestamp

### 8. Cancel URL Ingestion

Stop an ongoing URL crawling operation mid-process:

```bash
curl -X POST "http://localhost:8000/documents/cancel-ingestion/{job_id}"
```

**Parameters:**
- `job_id` (path parameter): The unique job identifier returned when starting a crawl with `follow_links=true` and `max_depth > 1`

**Example:**
```bash
curl -X POST "http://localhost:8000/documents/cancel-ingestion/a1b2c3d4-e5f6-7890-abcd-ef1234567890"
```

**Response (success):**
```json
{
  "success": true,
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Cancellation requested. The operation will stop after processing the current URL."
}
```

**Response (job not found):**
```json
{
  "success": false,
  "job_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "message": "Job not found or already completed"
}
```

**Features:**
- **Graceful Cancellation**: Stops after the current URL is processed, not immediately
- **Preserves Progress**: Already-processed URLs and their chunks remain in the vector store
- **Thread-safe**: Can be called while the crawling operation is in progress
- **Automatic Cleanup**: Job tracking is removed after cancellation or completion

**Use Cases:**
- Stop crawling when you realize a site has too many pages
- Cancel operations that are taking longer than expected
- Interrupt crawling if you entered the wrong URL
- Free up resources when crawling is no longer needed

## Supported File Formats

| Category | Formats | Notes |
|----------|---------|-------|
| Text | `.txt`, `.md` | Direct text extraction |
| PDF | `.pdf` | Text extraction from PDF documents |
| Microsoft Office | `.docx`, `.pptx`, `.xls`, `.xlsx` | Document content extraction |
| Web | `.html`, `.htm` | HTML parsing and text extraction |
| Data | `.csv` | Structured data extraction |
| Images (OCR) | `.png`, `.jpg`, `.jpeg`, `.tif`, `.tiff` | **OCR text extraction + image display** |

### Image Support

The system provides **enhanced image support** with both OCR text extraction and visual display:

**Features:**
- **Text Extraction**: Uses Tesseract OCR to extract text from images
- **Image Display**: Stores original images and displays them alongside answers
- **Contextual Relevance**: Shows images when answering questions related to image content

**Requirements:**
- Tesseract OCR must be installed on your system:
  - **macOS**: `brew install tesseract`
  - **Linux**: `sudo apt-get install tesseract-ocr`
  - **Windows**: Download from [GitHub](https://github.com/UB-Mannheim/tesseract/wiki)

**How it works:**
1. Upload an image (diagram, screenshot, form, etc.)
2. System extracts text via OCR and stores the original image
3. When you ask questions, relevant images are displayed with answers
4. Click on images to view full size in a new tab

## Configuration Options

All settings are in `.env`:

### Server Configuration
- `APP_HOST`: Server host (default: `0.0.0.0`)
- `APP_PORT`: Server port (default: `8000`)

### Paths
- `DATA_DIR`: Base data directory
- `UPLOAD_DIR`: Where uploaded files are stored
- `VECTOR_DB_DIR`: ChromaDB storage location
- `IMAGE_DIR`: Where extracted/uploaded images are stored (default: `./data/images`)
- `LLM_MODEL_PATH`: Path to .gguf model file

### LLM Runtime
- `LLM_CONTEXT_SIZE`: Context window size (default: `4096`)
- `LLM_MAX_TOKENS`: Max tokens to generate (default: `512`)
- `LLM_N_THREADS`: CPU threads (default: `4`)
- `LLM_N_GPU_LAYERS`: GPU layers to offload (default: `0` for CPU)
- `LLM_TEMPERATURE`: Generation temperature (default: `0.1`)

### Embeddings
- `EMBEDDING_MODEL_NAME`: Sentence transformer model
- `EMBEDDING_DEVICE`: `cpu`, `cuda`, or `mps`
- `EMBEDDING_CACHE_DIR`: Local cache directory for models (default: `./models/sentence-transformers`)

### Network Configuration (for Hugging Face model downloads)
- `HF_PROXY`: HTTP/HTTPS proxy server (e.g., `http://proxy.example.com:8080`)
- `HF_SSL_VERIFY`: Verify SSL certificates (default: `true`, set to `false` to disable)
- `HF_OFFLINE`: Use offline mode with pre-downloaded models (default: `false`)

### ChromaDB Configuration
- `ANONYMIZED_TELEMETRY`: Disable ChromaDB telemetry (set to `False` to suppress telemetry errors in offline mode)

### Chunking & Retrieval
- `CHUNK_SIZE`: Characters per chunk (default: `800`)
  - Larger values (1000-1500): More context per chunk, fewer chunks
  - Smaller values (400-600): More granular retrieval, more chunks
- `CHUNK_OVERLAP`: Overlap between chunks (default: `200`)
  - Helps preserve context across chunk boundaries
  - Should be 20-30% of CHUNK_SIZE
  - Smart and paragraph strategies optimize overlap at sentence boundaries
- `CHUNKING_STRATEGY`: Chunking method (default: `smart`)
  - `simple`: Basic character-based chunking (fastest, least precise)
  - `smart`: Sentence-aware chunking with improved boundary detection (recommended)
  - `paragraph`: Preserves document structure with metadata (most precise)
- `TOP_K`: Number of chunks to retrieve for answering questions (default: `8`)
  - Higher values (10-15): More context, better for complex questions, slower
  - Lower values (3-5): Faster, good for simple questions, may miss context

## Example .env Configurations

### Basic Configuration (Default)
```env
LLM_MODEL_PATH=./models/Llama-3.2-8B.gguf
LLM_N_GPU_LAYERS=0
LLM_N_THREADS=4
EMBEDDING_DEVICE=cpu

# Chunking & Retrieval (optional - defaults shown)
CHUNKING_STRATEGY=smart
CHUNK_SIZE=800
CHUNK_OVERLAP=200
TOP_K=8
```

### Corporate Network with Proxy
```env
LLM_MODEL_PATH=./models/Llama-3.2-8B.gguf
LLM_N_GPU_LAYERS=0
LLM_N_THREADS=4
EMBEDDING_DEVICE=cpu

# Network configuration for proxy
HF_PROXY=http://your-proxy.company.com:8080
EMBEDDING_CACHE_DIR=./models/sentence-transformers
```

### Offline Mode (No Internet Required)
```env
LLM_MODEL_PATH=./models/Llama-3.2-8B.gguf
LLM_N_GPU_LAYERS=0
LLM_N_THREADS=4
EMBEDDING_DEVICE=cpu

# Offline mode - models must be pre-downloaded
HF_OFFLINE=true
EMBEDDING_CACHE_DIR=./models/sentence-transformers

# Disable ChromaDB telemetry
ANONYMIZED_TELEMETRY=False
```

### GPU Configuration with CUDA
```env
LLM_MODEL_PATH=./models/Llama-3.2-8B.gguf
LLM_N_GPU_LAYERS=35
LLM_N_THREADS=4
EMBEDDING_DEVICE=cuda

# Cache directory for faster subsequent loads
EMBEDDING_CACHE_DIR=./models/sentence-transformers
```

### Apple Silicon (M1/M2/M3) GPU Configuration
```env
LLM_MODEL_PATH=./models/Llama-3.2-3B-Instruct-Q4_K_M.gguf
LLM_N_GPU_LAYERS=99  # Use all available layers on GPU (Metal)
LLM_N_THREADS=4
EMBEDDING_DEVICE=mps  # Metal Performance Shaders for embeddings

# Offline mode (recommended for M1)
HF_OFFLINE=true
EMBEDDING_CACHE_DIR=./models/sentence-transformers
ANONYMIZED_TELEMETRY=False

# Note: Requires llama-cpp-python rebuilt with Metal support:
# CMAKE_ARGS="-DLLAMA_METAL=on" pip install llama-cpp-python --no-cache-dir --force-reinstall
```

### Fine-tuned for Accuracy (Recommended for Q&A)
```env
LLM_MODEL_PATH=./models/Llama-3.2-8B.gguf
LLM_N_GPU_LAYERS=0
LLM_N_THREADS=4
EMBEDDING_DEVICE=cpu

# Optimized chunking for better accuracy
CHUNKING_STRATEGY=smart
CHUNK_SIZE=1000
CHUNK_OVERLAP=250
TOP_K=10

# Offline mode
HF_OFFLINE=true
EMBEDDING_CACHE_DIR=./models/sentence-transformers
ANONYMIZED_TELEMETRY=False
```

## Performance Tips

### CPU Mode
- Increase `LLM_N_THREADS` to match your CPU cores
- Use smaller quantized models (Q4 or Q5)
- Reduce `LLM_CONTEXT_SIZE` if running out of memory

### GPU Mode
- Set `LLM_N_GPU_LAYERS` to offload more layers to GPU
- Use `EMBEDDING_DEVICE=cuda` or `mps` for faster embeddings
- Larger models will provide better quality

### Chunking

The system offers three chunking strategies with different precision levels:

**Simple Chunking** (`CHUNKING_STRATEGY=simple`):
- Basic character-based splitting
- Fastest processing speed
- May split in the middle of sentences
- Best for: Quick testing or when speed is critical

**Smart Chunking** (`CHUNKING_STRATEGY=smart`) - **Recommended**:
- Respects sentence boundaries
- Handles common abbreviations (Dr., Prof., Inc., etc.)
- Correctly processes decimals (e.g., $1.5 million)
- Implements intelligent overlap using complete sentences
- Best for: Most use cases, provides good balance of speed and precision

**Paragraph Chunking** (`CHUNKING_STRATEGY=paragraph`):
- Preserves document structure (paragraphs)
- Includes metadata about document position
- Maintains natural text flow
- Best for: Documents with clear structure, when maximum precision is needed

**Size and Overlap**:
- Larger `CHUNK_SIZE`: Better context per chunk, but fewer chunks retrieved
- Smaller `CHUNK_SIZE`: More granular retrieval, but less context
- Increase `TOP_K` to retrieve more context for complex questions
- Smart and paragraph strategies automatically optimize overlap at sentence boundaries

## Troubleshooting

### Model Not Found
```
FileNotFoundError: Model file not found at ./models/llama-model.gguf
```
**Solution**: Download a .gguf model and place it in the `models/` directory.

### Out of Memory
```
RuntimeError: Failed to load LLM
```
**Solution**: 
- Use a smaller quantized model (Q4_K_M or Q5_K_M)
- Reduce `LLM_CONTEXT_SIZE`
- Set `LLM_N_GPU_LAYERS=0` to use CPU only

### SSL/Network Errors (Hugging Face Connection Issues)
```
SSL: UNEXPECTED_EOF_WHILE_READING
MaxRetryError: HTTPSConnectionPool(host='huggingface.co'...)
```
**Problem**: Cannot download embedding models due to SSL errors, proxy/firewall restrictions, or network issues.

**Solutions** (choose the one that fits your situation):

#### Option 1: Use Offline Mode (Recommended for corporate networks)
Download the model from a machine with internet access, then use offline:

```bash
# On a machine with internet access:
python download_embedding_model.py

# Copy the ./models/sentence-transformers/ directory to your target machine

# Add to .env:
HF_OFFLINE=true
EMBEDDING_CACHE_DIR=./models/sentence-transformers
```

#### Option 2: Configure Proxy
If you're behind a corporate proxy:

```bash
# Add to .env:
HF_PROXY=http://your-proxy.company.com:8080
```

#### Option 3: Disable SSL Verification (NOT recommended for production)
As a last resort, if SSL certificates are the issue:

```bash
# Add to .env:
HF_SSL_VERIFY=false
```

#### Option 4: Use the Download Script with Options
```bash
# Download with proxy:
python download_embedding_model.py --proxy http://proxy.example.com:8080

# Download without SSL verification (not recommended):
python download_embedding_model.py --no-verify-ssl

# Download to custom directory:
python download_embedding_model.py --cache-dir /path/to/cache
```

### Tesseract Not Found
```
TesseractNotFoundError: Tesseract is not installed
```
**Solution**: Install Tesseract OCR as described in Prerequisites.

### ChromaDB Errors

#### ChromaDB Telemetry Errors
```
chromadb.telemetry.product.posthog - ERROR - Failed to send telemetry event: capture() takes 1 positional argument but 3 were given
```
**Problem**: ChromaDB tries to send usage telemetry but fails, especially in offline mode or due to version compatibility issues.

**Solution**: These errors are non-critical (the application works fine), but you can suppress them by adding to `.env`:
```bash
ANONYMIZED_TELEMETRY=False
```

#### ChromaDB Database Corruption
**Solution**: Delete the `data/chroma` directory and restart. Documents will need to be re-uploaded.

### Slow Response Times
**Solution**:
- Enable GPU acceleration
- Use smaller models
- Reduce `TOP_K` to retrieve fewer chunks
- Reduce `LLM_MAX_TOKENS`

## Project Structure

```
llama_chat01/
├── .env                      # Configuration file
├── .env.template             # Configuration template
├── models/                   # LLM model files (.gguf)
├── data/
│   ├── uploads/              # Uploaded documents
│   └── chroma/               # ChromaDB vector store
├── app/
│   ├── __init__.py
│   ├── config.py             # Settings management
│   ├── llm.py                # LLM wrapper
│   ├── embeddings.py         # Embeddings module
│   ├── vectorstore.py        # ChromaDB operations
│   ├── chunking.py           # Text chunking
│   ├── ingestion.py          # Document processing
│   └── api.py                # FastAPI application
├── main.py                   # Entry point
├── requirements.txt          # Python dependencies
└── README.md                 # This file
```

## Development

### Running with Auto-reload
The server runs with `reload=True` by default, automatically restarting on code changes.

### Testing the API
Use the interactive docs at `http://localhost:8000/docs` to test endpoints.

### Logging
Logs are printed to console. Adjust `LOG_LEVEL` in `.env` (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

## License

This project is provided as-is for educational and development purposes.

## Acknowledgments

- [llama-cpp-python](https://github.com/abetlen/llama-cpp-python)
- [ChromaDB](https://www.trychroma.com/)
- [Sentence Transformers](https://www.sbert.net/)
- [FastAPI](https://fastapi.tiangolo.com/)

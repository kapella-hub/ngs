"""FastAPI application with document upload and question answering endpoints."""
import logging
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
import mimetypes

from app.config import settings
from app.ingestion import ingest_files, ingest_url, refresh_url_content
from app.vectorstore import query_top_k, query_multi_topic, get_collection_stats, clear_collection, list_files, delete_file_by_source
from app.llm import generate_answer
from app.conversations import ConversationStore
from app.token_manager import build_prompt_with_budget

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Local RAG System",
    description="Document ingestion and question answering using local LLM and ChromaDB",
    version="1.0.0"
)

# Mount static files directory
static_dir = Path(__file__).parent.parent / "static"
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# Initialize conversation store
# max_turns could be read from settings in the future: settings.MAX_CONVERSATION_TURNS
conv_store = ConversationStore(max_turns=8)


# Request/Response Models
class UploadResponse(BaseModel):
    """Response model for document upload endpoint."""
    batch_id: str = Field(..., description="Unique batch identifier")
    file_count: int = Field(..., description="Number of files processed")
    success_count: int = Field(..., description="Number of successfully ingested files")
    failed_count: int = Field(..., description="Number of failed files")
    total_chunks: int = Field(..., description="Total number of chunks created")
    failed_files: List[dict] = Field(default_factory=list, description="List of failed files with errors")


class AskRequest(BaseModel):
    """Request model for question answering endpoint."""
    conversation_id: Optional[str] = Field(None, description="Conversation ID for multi-turn interactions (optional)")
    query: str = Field(..., description="Question to answer")
    top_k: Optional[int] = Field(None, description="Number of chunks to retrieve (optional)")


class GenerateRequest(BaseModel):
    """Request model for direct LLM generation (no RAG)."""
    prompt: str = Field(..., description="Prompt to send to the LLM")
    system_prompt: Optional[str] = Field(None, description="Optional system prompt")
    max_tokens: Optional[int] = Field(None, description="Maximum tokens to generate")


class GenerateResponse(BaseModel):
    """Response model for direct LLM generation."""
    response: str = Field(..., description="Generated response from LLM")


class AskResponse(BaseModel):
    """Response model for question answering endpoint."""
    answer: str = Field(..., description="Generated answer")
    conversation_id: str = Field(..., description="Conversation ID for this interaction")
    images: List[str] = Field(default_factory=list, description="List of image URLs relevant to the answer")


class StatsResponse(BaseModel):
    """Response model for collection statistics."""
    collection_name: str
    document_count: int


class ClearResponse(BaseModel):
    """Response model for clear operation."""
    status: str = Field(..., description="Operation status")
    message: str = Field(..., description="Status message")
    collection_name: str = Field(..., description="Name of the cleared collection")


class FileInfo(BaseModel):
    """Model for file information."""
    filename: str = Field(..., description="File name")
    upload_date: str = Field(..., description="Upload timestamp (ISO format)")
    chunk_count: int = Field(..., description="Number of chunks for this file")


class FileListResponse(BaseModel):
    """Response model for file list endpoint."""
    files: List[FileInfo] = Field(..., description="List of files")
    total_files: int = Field(..., description="Total number of files")


class DeleteFileResponse(BaseModel):
    """Response model for file deletion."""
    status: str = Field(..., description="Operation status")
    message: str = Field(..., description="Status message")
    deleted_count: int = Field(..., description="Number of chunks deleted")


class UploadUrlRequest(BaseModel):
    """Request model for URL upload endpoint."""
    url: str = Field(..., description="URL to fetch and ingest")
    follow_links: bool = Field(default=False, description="Whether to follow and ingest links found on the page")
    max_depth: int = Field(default=1, ge=1, le=5, description="Maximum crawl depth (1-5). Only used when follow_links=True")
    same_domain_only: bool = Field(default=True, description="Only follow links within the same domain. Only used when follow_links=True")


class UploadUrlResponse(BaseModel):
    """Response model for URL upload endpoint."""
    success: bool = Field(..., description="Whether ingestion was successful")
    source_url: str = Field(..., description="The source URL")
    total_chunks: int = Field(..., description="Number of chunks created")
    urls_processed: int = Field(default=0, description="Number of URLs successfully processed")
    urls_failed: int = Field(default=0, description="Number of URLs that failed to process")
    cancelled: bool = Field(default=False, description="Whether operation was cancelled by user")
    job_id: Optional[str] = Field(None, description="Job ID for tracking/cancellation (only for crawling operations)")
    last_fetched: Optional[str] = Field(None, description="ISO timestamp of when content was fetched")
    error: Optional[str] = Field(None, description="Error message if failed")


class CancelResponse(BaseModel):
    """Response model for cancellation endpoint."""
    success: bool = Field(..., description="Whether cancellation was successful")
    job_id: str = Field(..., description="The job ID that was cancelled")
    message: str = Field(..., description="Status message")


class RefreshUrlResponse(BaseModel):
    """Response model for URL refresh endpoint."""
    success: bool = Field(..., description="Whether refresh was successful")
    source_url: str = Field(..., description="The source URL")
    total_chunks: int = Field(..., description="Number of chunks created")
    last_fetched: Optional[str] = Field(None, description="ISO timestamp of when content was fetched")
    error: Optional[str] = Field(None, description="Error message if failed")


def extract_topics_from_query(query: str) -> Optional[List[str]]:
    """
    Extract multiple topics from a query if it spans multiple subjects.
    
    Detects queries that ask about multiple distinct topics using patterns like:
    - "compare X and Y"
    - "X and Y"
    - "both X and Y"
    - "X versus Y"
    - "difference between X and Y"
    
    Args:
        query: User query string
        
    Returns:
        List of topic strings if multiple topics detected, None otherwise
    """
    query_lower = query.lower()
    
    # Multi-topic indicator patterns
    multi_topic_patterns = [
        (" and ", " compare ", " versus ", " vs ", " both ", 
         " difference between ", " similarities between ", " contrast ")
    ]
    
    # Check if query contains multi-topic indicators
    has_multi_topic = any(pattern in query_lower for patterns in multi_topic_patterns for pattern in patterns)
    
    if not has_multi_topic:
        return None
    
    # Simple topic extraction based on common patterns
    topics = []
    
    # Pattern: "compare X and Y"
    if "compare" in query_lower:
        # Extract topics after "compare" and split by "and"
        parts = query_lower.split("compare", 1)
        if len(parts) > 1:
            remaining = parts[1].strip()
            # Remove common question words
            for word in [" - ", " what ", " how ", " why ", " where ", " when ", "?"]:
                remaining = remaining.replace(word, " ")
            # Split by "and"
            if " and " in remaining:
                topic_parts = remaining.split(" and ")
                for part in topic_parts[:2]:  # Limit to 2 topics
                    topic = part.strip().rstrip(".,!?")
                    if topic and len(topic) > 2:
                        topics.append(topic)
    
    # Pattern: "X and Y" (general)
    elif " and " in query_lower:
        # Split by "and" and take up to 2 parts
        parts = query_lower.split(" and ")
        if len(parts) >= 2:
            # Extract the last word/phrase before "and" from first part
            first_part = parts[0].strip().split()[-3:]  # Last 3 words
            first_topic = " ".join(first_part).strip()
            
            # Extract the first word/phrase after "and" from second part
            second_part = parts[1].strip().split()[:3]  # First 3 words
            second_topic = " ".join(second_part).strip()
            
            # Clean up
            for topic in [first_topic, second_topic]:
                topic = topic.rstrip(".,!?")
                # Remove question words
                for qword in ["what", "how", "tell", "about", "is", "are", "do"]:
                    topic = topic.replace(qword + " ", "").strip()
                if topic and len(topic) > 2:
                    topics.append(topic)
    
    # Return topics if we found at least 2 distinct ones
    if len(topics) >= 2:
        logger.info(f"Detected multi-topic query. Topics: {topics}")
        return topics[:2]  # Limit to 2 topics for now
    
    return None


# System prompt for the LLM
SYSTEM_PROMPT = """You are a helpful assistant that answers questions based solely on the provided context.

Rules:
1. Answer ONLY using information from the context provided below
2. **CRITICAL: Always include URLs, web addresses, access links, and contact information when present in the context**
   - URLs are extremely important and must be included prominently in your answer
   - If asking about a tool/system, prioritize its URL/access link in the first paragraph
3. If the answer cannot be found in the context, respond with "I don't know based on the provided documents"
4. ALWAYS format your answer using markdown for better readability:
   - Use **bold** for important terms, tool names, URLs, and key concepts
   - Break down information into bullet points (-) when listing features, requirements, or multiple items
   - Use numbered lists (1., 2., 3.) for sequential steps or procedures
   - Add blank lines between different sections or topics
   - Structure your response clearly with proper paragraphs
5. Do not make up information or use external knowledge
6. If the context is insufficient, acknowledge the limitation

Example of good formatting:
**ToolName** is a system for XYZ, accessible at **https://example.com**

**Key Features:**
- Feature 1 with description
- Feature 2 with description
- Feature 3 with description

**Access Requirements:**
- Requirement 1
- Requirement 2"""


@app.get("/")
def root():
    """Serve the web UI."""
    html_file = Path(__file__).parent.parent / "static" / "index.html"
    if html_file.exists():
        return FileResponse(html_file)
    else:
        return {
            "name": "Local RAG System",
            "version": "1.0.0",
            "message": "Web UI not found. API endpoints available at /docs",
            "endpoints": {
                "upload": "/documents/upload",
                "ask": "/ask",
                "stats": "/stats"
            }
        }


@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/stats", response_model=StatsResponse)
def get_stats():
    """Get collection statistics."""
    try:
        stats = get_collection_stats()
        if "error" in stats:
            raise HTTPException(status_code=500, detail=stats["error"])
        return stats
    except Exception as e:
        logger.error(f"Error getting stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/manage")
def serve_manage_page():
    """Serve the document management page."""
    html_file = Path(__file__).parent.parent / "static" / "manage.html"
    if html_file.exists():
        return FileResponse(html_file)
    else:
        raise HTTPException(status_code=404, detail="Manage page not found")


@app.get("/images/{filename}")
def serve_image(filename: str):
    """
    Serve an image file from the images directory.
    
    Args:
        filename: Name of the image file to serve
        
    Returns:
        FileResponse with the image file
        
    Raises:
        HTTPException: If file not found or path is invalid
    """
    try:
        # Security: Validate filename doesn't contain path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        # Build full path
        image_path = Path(settings.image_dir) / filename
        
        # Check if file exists
        if not image_path.exists() or not image_path.is_file():
            raise HTTPException(status_code=404, detail="Image not found")
        
        # Get MIME type
        mime_type, _ = mimetypes.guess_type(str(image_path))
        if mime_type is None:
            mime_type = "application/octet-stream"
        
        # Return image file
        return FileResponse(
            path=str(image_path),
            media_type=mime_type,
            filename=filename
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving image {filename}: {e}")
        raise HTTPException(status_code=500, detail="Failed to serve image")


@app.get("/documents/list", response_model=FileListResponse)
def list_all_files():
    """List all uploaded files with metadata."""
    try:
        logger.info("Listing all files")
        files = list_files()
        return FileListResponse(
            files=files,
            total_files=len(files)
        )
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/documents/file/{filename}", response_model=DeleteFileResponse)
def delete_file(filename: str):
    """Delete a specific file and all its chunks."""
    try:
        logger.info(f"Deleting file: {filename}")
        result = delete_file_by_source(filename)
        
        if result["status"] == "error":
            raise HTTPException(status_code=404, detail=result["message"])
        
        logger.info(f"Successfully deleted file: {filename}")
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file {filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/documents/clear", response_model=ClearResponse)
def clear_all_documents():
    """Clear all documents from the vector store."""
    try:
        logger.info("Clearing all documents from vector store")
        result = clear_collection()
        logger.info(f"Successfully cleared all documents: {result}")
        return result
    except Exception as e:
        logger.error(f"Error clearing documents: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/documents/upload-url", response_model=UploadUrlResponse)
def upload_url(request: UploadUrlRequest):
    """
    Fetch and ingest content from a URL.
    
    This endpoint will:
    1. Fetch content from the provided URL
    2. Extract text from the HTML
    3. Optionally crawl and ingest linked pages (if follow_links=True)
    4. Chunk the text
    5. Add it to the vector store with URL metadata
    
    Parameters:
    - url: The starting URL to ingest
    - follow_links: If True, crawl and ingest linked pages (default: False)
    - max_depth: Maximum crawl depth, 1-5 (default: 2). Only applies when follow_links=True
    - same_domain_only: Only follow links within same domain (default: True). Only applies when follow_links=True
    
    The URL(s) will be stored as sources and can be refreshed later.
    """
    if not request.url or not request.url.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    
    # Validate URL format
    if not request.url.startswith(('http://', 'https://')):
        raise HTTPException(
            status_code=400, 
            detail="URL must start with http:// or https://"
        )
    
    crawl_info = ""
    if request.follow_links:
        crawl_info = f" (crawling with max_depth={request.max_depth}, same_domain_only={request.same_domain_only})"
    
    logger.info(f"Processing URL upload: {request.url}{crawl_info}")
    
    try:
        # Generate unique document ID for this URL
        doc_id = f"url:{uuid.uuid4()}"
        
        # Generate job_id for cancellable operations (crawling with depth > 1)
        job_id = None
        if request.follow_links and request.max_depth > 1:
            job_id = str(uuid.uuid4())
            logger.info(f"Generated job_id {job_id} for crawling operation")
        
        # Ingest the URL with crawling options
        result = ingest_url(
            request.url, 
            doc_id,
            follow_links=request.follow_links,
            max_depth=request.max_depth,
            same_domain_only=request.same_domain_only,
            job_id=job_id
        )
        
        # Add job_id to result for response
        if job_id:
            result["job_id"] = job_id
        
        if result["success"]:
            logger.info(
                f"Successfully ingested URL {request.url}: "
                f"{result.get('urls_processed', 1)} URL(s) processed, "
                f"{result['total_chunks']} chunks"
            )
        elif result.get("cancelled", False):
            logger.info(f"URL ingestion cancelled for {request.url}")
        else:
            logger.warning(f"Failed to ingest URL {request.url}: {result.get('error')}")
        
        return UploadUrlResponse(**result)
        
    except Exception as e:
        logger.error(f"Error during URL ingestion: {e}")
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to ingest URL: {str(e)}"
        )


@app.post("/documents/cancel-ingestion/{job_id}", response_model=CancelResponse)
def cancel_ingestion(job_id: str):
    """
    Cancel an ongoing URL ingestion/crawling operation.
    
    This endpoint allows users to stop a long-running crawl operation
    by its job ID. The operation will stop gracefully after processing
    the current URL.
    
    Args:
        job_id: The unique job identifier returned when starting the ingestion
        
    Returns:
        CancelResponse with success status and message
    """
    logger.info(f"Received cancellation request for job {job_id}")
    
    try:
        from app.cancellation import cancellation_store
        
        success = cancellation_store.cancel_job(job_id)
        
        if success:
            logger.info(f"Successfully requested cancellation for job {job_id}")
            return CancelResponse(
                success=True,
                job_id=job_id,
                message="Cancellation requested. The operation will stop after processing the current URL."
            )
        else:
            logger.warning(f"Job {job_id} not found or already completed")
            return CancelResponse(
                success=False,
                job_id=job_id,
                message="Job not found or already completed"
            )
    except Exception as e:
        logger.error(f"Error cancelling job {job_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel ingestion: {str(e)}"
        )


@app.post("/documents/refresh-url/{filename:path}", response_model=RefreshUrlResponse)
def refresh_url(filename: str):
    """
    Refresh content from a previously ingested URL.
    
    This endpoint will:
    1. Delete existing chunks for the URL
    2. Re-fetch content from the URL
    3. Re-chunk and re-index the new content
    
    Args:
        filename: The URL (as stored in the source field)
    """
    if not filename or not filename.strip():
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    
    logger.info(f"Refreshing URL: {filename}")
    
    try:
        # Generate new document ID for the refresh
        doc_id = f"url:{uuid.uuid4()}"
        
        # Refresh the URL content
        result = refresh_url_content(filename, doc_id)
        
        if result["success"]:
            logger.info(
                f"Successfully refreshed URL {filename}: "
                f"{result['total_chunks']} chunks"
            )
        else:
            logger.warning(f"Failed to refresh URL {filename}: {result.get('error')}")
        
        return RefreshUrlResponse(**result)
        
    except Exception as e:
        logger.error(f"Error refreshing URL {filename}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refresh URL: {str(e)}"
        )


@app.post("/documents/upload", response_model=UploadResponse)
async def upload_documents(files: List[UploadFile] = File(...)):
    """
    Upload and ingest multiple documents.
    
    Accepts multiple files in various formats:
    - Text: .txt, .md
    - PDF: .pdf
    - Office: .docx, .pptx, .xls, .xlsx
    - Web: .html, .htm
    - Data: .csv
    - Images: .png, .jpg, .jpeg, .tif, .tiff (OCR)
    """
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    
    # Generate unique batch ID
    batch_id = str(uuid.uuid4())
    
    # Create batch directory
    batch_dir = Path(settings.upload_dir) / batch_id
    batch_dir.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Processing upload batch {batch_id} with {len(files)} files")
    
    # Save uploaded files
    saved_paths = []
    for file in files:
        try:
            file_path = batch_dir / file.filename
            
            # Save file
            with open(file_path, 'wb') as f:
                content = await file.read()
                f.write(content)
            
            saved_paths.append(file_path)
            logger.info(f"Saved file: {file.filename}")
            
        except Exception as e:
            logger.error(f"Error saving file {file.filename}: {e}")
            # Continue with other files
    
    if not saved_paths:
        raise HTTPException(status_code=500, detail="Failed to save any files")
    
    # Ingest files
    try:
        result = ingest_files(saved_paths, batch_id)
        
        logger.info(
            f"Batch {batch_id} ingestion complete: "
            f"{result['success_count']} success, "
            f"{result['failed_count']} failed, "
            f"{result['total_chunks']} chunks"
        )
        
        return UploadResponse(
            batch_id=batch_id,
            file_count=len(files),
            success_count=result["success_count"],
            failed_count=result["failed_count"],
            total_chunks=result["total_chunks"],
            failed_files=result["failed_files"]
        )
        
    except Exception as e:
        logger.error(f"Error during ingestion: {e}")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {str(e)}")


@app.post("/ask", response_model=AskResponse)
def ask_question(request: AskRequest):
    """
    Answer a question using RAG over ingested documents with conversation memory.
    
    The endpoint:
    1. Determines conversation ID (uses provided or generates new UUID)
    2. Retrieves conversation history for context
    3. Retrieves relevant document chunks from the vector store (RAG)
    4. Constructs a prompt with conversation history, context, and question
    5. Calls the local LLM to generate an answer
    6. Saves the user query and assistant answer to conversation history
    7. Returns the answer with conversation ID for follow-up questions
    """
    if not request.query or not request.query.strip():
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    # Determine conversation ID
    conversation_id = request.conversation_id if request.conversation_id else str(uuid.uuid4())
    
    logger.info(f"Processing question (conv_id={conversation_id[:8]}...): {request.query[:100]}...")
    
    try:
        # Retrieve conversation history
        history = conv_store.get_history(conversation_id)
        
        # Retrieve relevant chunks from vector store (RAG - only on current query)
        top_k = request.top_k if request.top_k is not None else settings.top_k
        
        # Detect if query spans multiple topics
        topics = extract_topics_from_query(request.query)
        
        if topics:
            # Multi-topic query: retrieve chunks for each topic independently
            logger.info(f"Using multi-topic retrieval for topics: {topics}")
            results = query_multi_topic(request.query, topics, top_k=top_k)
        else:
            # Single-topic query: use standard retrieval
            results = query_top_k(request.query, top_k=top_k)
        
        if not results:
            logger.warning("No relevant documents found")
            answer = "I don't have any documents to answer this question. Please upload documents first."
            
            # Save to conversation history even for no-docs response
            conv_store.add_turn(conversation_id, "user", request.query)
            conv_store.add_turn(conversation_id, "assistant", answer)
            
            return AskResponse(
                answer=answer,
                conversation_id=conversation_id
            )
        
        # Build context from retrieved chunks and collect images
        context_chunks = []
        image_paths = []
        for result in results:
            context_chunks.append(result['text'])
            # Collect image path if present
            if 'image_path' in result and result['image_path']:
                image_paths.append(result['image_path'])
        
        # Convert image paths to URLs and deduplicate
        image_urls = []
        if image_paths:
            # Deduplicate while preserving order
            seen = set()
            for img_path in image_paths:
                if img_path not in seen:
                    seen.add(img_path)
                    # Extract just the filename from the path (e.g., "images/doc_0.png" -> "doc_0.png")
                    filename = Path(img_path).name
                    image_urls.append(f"/images/{filename}")
        
        # Build enhanced system prompt with conversation awareness
        enhanced_system_prompt = """You are a helpful assistant that answers questions based strictly on the provided context and prior conversation.

Rules:
1. **PROVIDE DETAILED, COMPREHENSIVE ANSWERS:** Use ALL relevant information from the context to give thorough, complete answers. Include specific details, examples, steps, requirements, and explanations found in the documents. Don't summarize too briefly - be comprehensive and informative.
2. Answer ONLY using information from the context provided below and the conversation history
3. **URL FORMATTING - CRITICAL:**
   - When URLs appear in the context, format them as markdown links with MEANINGFUL, SPECIFIC text
   - Use contextual link text that describes what the link is for
   - Example: "You can access DIRRT at [the DIRRT portal](https://dirrt.ops.charter.com/home)"
   - Example: "Submit requests via [DIRRT's request system](https://dirrt.ops.charter.com/requests)"
   - NEVER use placeholder text: ❌ [Descriptive Text](URL) or [Access Here](URL) or [Tool Name](URL)
   - NEVER use plain URLs: ❌ https://example.com
   - NEVER use angle brackets: ❌ <https://example.com>
   - NEVER reference documents by number: ❌ "Document 1", "Document 5", "Refer to Document X"
   - Include URLs naturally in your sentences with meaningful link text
4. If the question refers to previous conversation (e.g., "it", "that", "the previous"), use the conversation history to understand the reference
5. If the answer cannot be found in the context, respond with "I don't know based on the provided documents"
6. Format your answer using markdown for readability:
   - Use **bold** for important terms, tool names, and key concepts
   - Break down information into bullet points (-) when listing features or requirements
   - Use numbered lists (1., 2., 3.) for sequential steps
   - Add blank lines between sections
   - Include all relevant details, specifications, and requirements from the context
7. Do not make up information or use external knowledge
8. If the context is insufficient, acknowledge the limitation"""
        
        # Calculate available token budget
        # Context window minus tokens reserved for generation
        max_prompt_tokens = settings.llm_context_size - settings.llm_max_tokens
        
        # Build prompt with token budget management
        system_prompt_final, user_prompt, estimated_tokens = build_prompt_with_budget(
            system_prompt=enhanced_system_prompt,
            user_query=request.query,
            conversation_history=history,
            context_chunks=context_chunks,
            max_context_tokens=max_prompt_tokens
        )
        
        logger.info(f"Prompt uses ~{estimated_tokens} tokens (budget: {max_prompt_tokens})")
        
        # Generate answer using local LLM
        logger.info("Generating answer with local LLM...")
        answer = generate_answer(
            user_prompt, 
            system_prompt=system_prompt_final,
            estimated_prompt_tokens=estimated_tokens
        )
        
        logger.info(f"Answer generated: {answer[:100]}...")
        
        # Save conversation turns
        conv_store.add_turn(conversation_id, "user", request.query)
        conv_store.add_turn(conversation_id, "assistant", answer)
        
        return AskResponse(
            answer=answer,
            conversation_id=conversation_id,
            images=image_urls
        )
        
    except Exception as e:
        logger.error(f"Error processing question: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process question: {str(e)}")


@app.post("/generate", response_model=GenerateResponse)
def generate_direct(request: GenerateRequest):
    """
    Direct LLM generation without RAG retrieval.

    Use this endpoint for tasks that don't need document context,
    such as parsing/extraction tasks, summarization, or classification.
    """
    if not request.prompt or not request.prompt.strip():
        raise HTTPException(status_code=400, detail="Prompt cannot be empty")

    logger.info(f"Direct LLM generation request: {request.prompt[:100]}...")

    try:
        # Use the generate_answer function with just the prompt
        system = request.system_prompt or "You are a helpful assistant. Respond concisely and accurately."

        response = generate_answer(
            request.prompt,
            system_prompt=system,
            estimated_prompt_tokens=len(request.prompt.split()) * 2  # Rough estimate
        )

        logger.info(f"Generated response: {response[:100]}...")

        return GenerateResponse(response=response)

    except Exception as e:
        logger.error(f"Error in direct generation: {e}")
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.api:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True
    )

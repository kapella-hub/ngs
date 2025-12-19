"""Vector store operations using ChromaDB."""
import logging
from typing import List, Dict, Any, Optional
from functools import lru_cache
from datetime import datetime

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings
from app.embeddings import embed_texts, embed_query

logger = logging.getLogger(__name__)

# Suppress ChromaDB telemetry errors - they're harmless but noisy
logging.getLogger("chromadb.telemetry.product.posthog").setLevel(logging.CRITICAL)

COLLECTION_NAME = "documents"


@lru_cache(maxsize=1)
def get_chroma_client() -> chromadb.Client:
    """
    Initialize and cache ChromaDB persistent client.
    
    Returns:
        chromadb.Client: Initialized ChromaDB persistent client
    """
    logger.info(f"Initializing ChromaDB persistent client with persist_directory: {settings.vector_db_dir}")
    
    try:
        # Use PersistentClient to ensure data is saved to disk
        client = chromadb.PersistentClient(
            path=settings.vector_db_dir,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True
            )
        )
        logger.info("ChromaDB persistent client initialized successfully")
        return client
    except Exception as e:
        logger.error(f"Failed to initialize ChromaDB client: {e}")
        raise RuntimeError(f"Failed to initialize ChromaDB client: {e}")


def get_collection() -> chromadb.Collection:
    """
    Get or create the documents collection.
    
    Returns:
        chromadb.Collection: The documents collection
    """
    client = get_chroma_client()
    
    try:
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Document chunks for RAG system"}
        )
        logger.debug(f"Collection '{COLLECTION_NAME}' ready")
        return collection
    except Exception as e:
        logger.error(f"Failed to get/create collection: {e}")
        raise RuntimeError(f"Failed to get/create collection: {e}")


def add_chunks(
    texts: List[str],
    doc_ids: List[str],
    sources: List[str],
    upload_date: Optional[str] = None,
    image_paths: Optional[List[Optional[str]]] = None
) -> None:
    """
    Add document chunks to the vector store.
    
    Args:
        texts: List of text chunks
        doc_ids: List of logical document IDs for each chunk
        sources: List of source file paths/names for each chunk
        upload_date: ISO format upload timestamp (defaults to current time)
        image_paths: Optional list of image file paths associated with each chunk (None for text-only chunks)
        
    Raises:
        ValueError: If input lists have different lengths
        RuntimeError: If adding chunks fails
    """
    if not texts:
        logger.warning("No texts provided to add_chunks")
        return
    
    if not (len(texts) == len(doc_ids) == len(sources)):
        raise ValueError(
            f"Length mismatch: texts={len(texts)}, doc_ids={len(doc_ids)}, sources={len(sources)}"
        )
    
    if image_paths is not None and len(image_paths) != len(texts):
        raise ValueError(
            f"Length mismatch: texts={len(texts)}, image_paths={len(image_paths)}"
        )
    
    # Use current timestamp if not provided
    if upload_date is None:
        upload_date = datetime.utcnow().isoformat()
    
    logger.info(f"Adding {len(texts)} chunks to vector store")
    
    try:
        # Generate embeddings
        embeddings = embed_texts(texts)
        
        # Create unique IDs for each chunk (ChromaDB requires unique IDs)
        chunk_ids = [f"{doc_id}_chunk_{i}" for i, doc_id in enumerate(doc_ids)]
        
        # Build metadata for each chunk
        metadatas = []
        for i, (doc_id, source) in enumerate(zip(doc_ids, sources)):
            metadata = {"doc_id": doc_id, "source": source, "upload_date": upload_date}
            # Add image path if provided for this chunk
            if image_paths and image_paths[i]:
                metadata["image_path"] = image_paths[i]
            metadatas.append(metadata)
        
        # Add to collection
        collection = get_collection()
        collection.add(
            ids=chunk_ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas
        )
        
        logger.info(f"Successfully added {len(texts)} chunks")
        
    except Exception as e:
        logger.error(f"Error adding chunks: {e}")
        raise RuntimeError(f"Error adding chunks: {e}")


def query_top_k(
    query: str,
    top_k: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Query the vector store for top-k most relevant chunks.
    
    Args:
        query: Query string
        top_k: Number of results to return (defaults to settings.top_k)
        
    Returns:
        List of dictionaries containing:
            - text: chunk text
            - doc_id: logical document ID
            - source: source file path
            - distance: similarity distance
            - image_path: path to associated image (optional, only if chunk has an image)
    """
    if top_k is None:
        top_k = settings.top_k
    
    logger.debug(f"Querying vector store: query='{query[:50]}...', top_k={top_k}")
    
    try:
        # Query collection metadata first to avoid Chroma warnings when empty
        collection = get_collection()
        doc_count = collection.count()
        if doc_count == 0:
            logger.warning(
                "Vector store collection is empty (0 documents). "
                "Skipping similarity search."
            )
            return []
        
        # Never request more results than exist in the index
        effective_k = min(top_k, doc_count)
        if effective_k <= 0:
            logger.warning(
                "Effective top_k computed as 0 after comparing with collection size; "
                "no results will be returned."
            )
            return []
        
        # Generate query embedding
        query_embedding = embed_query(query)
        
        # Query collection
        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=effective_k
        )
        
        # Parse results
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        
        # Build result list
        result_list = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            result_dict = {
                "text": doc,
                "doc_id": meta.get("doc_id", "unknown"),
                "source": meta.get("source", "unknown"),
                "distance": dist
            }
            # Add image path if present in metadata
            if "image_path" in meta:
                result_dict["image_path"] = meta["image_path"]
            result_list.append(result_dict)
        
        logger.debug(f"Retrieved {len(result_list)} results")
        return result_list
        
    except Exception as e:
        logger.error(f"Error querying vector store: {e}")
        raise RuntimeError(f"Error querying vector store: {e}")


def query_multi_topic(
    query: str,
    topics: List[str],
    top_k: Optional[int] = None
) -> List[Dict[str, Any]]:
    """
    Query the vector store for multiple topics, ensuring diverse results across topics.
    
    This function retrieves chunks for each topic independently and combines them,
    ensuring representation from all topics rather than having one dominant topic.
    
    Args:
        query: Original query string (for logging)
        topics: List of topic strings to query independently
        top_k: Total number of results to return (defaults to settings.top_k)
        
    Returns:
        List of dictionaries containing chunks from all topics, deduplicated
    """
    if top_k is None:
        top_k = settings.top_k
    
    if not topics:
        logger.warning("No topics provided for multi-topic query, falling back to single query")
        return query_top_k(query, top_k)
    
    logger.info(f"Multi-topic query with {len(topics)} topics: {topics}")
    
    try:
        collection = get_collection()
        doc_count = collection.count()
        if doc_count == 0:
            logger.warning(
                "Vector store collection is empty (0 documents). "
                "Skipping multi-topic similarity search."
            )
            return []

        # Calculate chunks per topic (distribute evenly)
        chunks_per_topic = max(1, top_k // len(topics))
        
        # Retrieve chunks for each topic
        all_results = []
        seen_chunks = set()  # Track unique chunks by text hash
        
        for topic in topics:
            # Generate embedding for this topic
            topic_embedding = embed_query(topic)
            
            # Query for this topic
            results = collection.query(
                query_embeddings=[topic_embedding],
                n_results=chunks_per_topic
            )
            
            # Parse results
            documents = results.get("documents", [[]])[0]
            metadatas = results.get("metadatas", [[]])[0]
            distances = results.get("distances", [[]])[0]
            
            # Add unique results
            for doc, meta, dist in zip(documents, metadatas, distances):
                # Use text hash for deduplication
                chunk_hash = hash(doc)
                if chunk_hash not in seen_chunks:
                    seen_chunks.add(chunk_hash)
                    result_dict = {
                        "text": doc,
                        "doc_id": meta.get("doc_id", "unknown"),
                        "source": meta.get("source", "unknown"),
                        "distance": dist
                    }
                    # Add image path if present
                    if "image_path" in meta:
                        result_dict["image_path"] = meta["image_path"]
                    all_results.append(result_dict)
            
            logger.debug(f"Retrieved {len(documents)} chunks for topic: '{topic[:50]}...'")
        
        # Sort by distance (ascending - lower is better)
        all_results.sort(key=lambda x: x["distance"])
        
        # Limit to top_k
        final_results = all_results[:top_k]
        
        logger.info(f"Multi-topic query returned {len(final_results)} unique chunks from {len(topics)} topics")
        return final_results
        
    except Exception as e:
        logger.error(f"Error in multi-topic query: {e}")
        # Fallback to single query
        logger.warning("Falling back to single query")
        return query_top_k(query, top_k)


def get_collection_stats() -> Dict[str, Any]:
    """
    Get statistics about the collection.
    
    Returns:
        Dictionary with collection statistics
    """
    try:
        collection = get_collection()
        count = collection.count()
        
        return {
            "collection_name": COLLECTION_NAME,
            "document_count": count
        }
    except Exception as e:
        logger.error(f"Error getting collection stats: {e}")
        return {"error": str(e)}


def list_files() -> List[Dict[str, Any]]:
    """
    List all unique files in the vector store with metadata.
    
    Returns:
        List of dictionaries containing:
            - filename: Source filename
            - upload_date: ISO format upload timestamp
            - chunk_count: Number of chunks for this file
    """
    try:
        collection = get_collection()
        
        # Get all items from collection
        results = collection.get()
        
        if not results or not results.get("metadatas"):
            logger.info("No files found in collection")
            return []
        
        metadatas = results["metadatas"]
        
        # Group by source filename
        files_dict = {}
        for metadata in metadatas:
            source = metadata.get("source", "unknown")
            upload_date = metadata.get("upload_date", "unknown")
            
            if source not in files_dict:
                files_dict[source] = {
                    "filename": source,
                    "upload_date": upload_date,
                    "chunk_count": 0
                }
            
            files_dict[source]["chunk_count"] += 1
        
        # Convert to list and sort by upload date (newest first)
        files_list = list(files_dict.values())
        files_list.sort(key=lambda x: x["upload_date"], reverse=True)
        
        logger.info(f"Found {len(files_list)} unique files")
        return files_list
        
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise RuntimeError(f"Error listing files: {e}")


def delete_file_by_source(filename: str) -> Dict[str, Any]:
    """
    Delete all chunks associated with a specific source file.
    
    Args:
        filename: Source filename to delete
        
    Returns:
        Dictionary with deletion results
    """
    try:
        collection = get_collection()
        
        # Get all items
        results = collection.get()
        
        if not results or not results.get("ids"):
            logger.warning(f"No data found when trying to delete {filename}")
            return {
                "status": "error",
                "message": "No data in collection",
                "deleted_count": 0
            }
        
        # Find all chunk IDs that match the filename
        ids_to_delete = []
        metadatas = results.get("metadatas", [])
        ids = results.get("ids", [])
        
        for chunk_id, metadata in zip(ids, metadatas):
            if metadata.get("source") == filename:
                ids_to_delete.append(chunk_id)
        
        if not ids_to_delete:
            logger.warning(f"No chunks found for file: {filename}")
            return {
                "status": "error",
                "message": f"File not found: {filename}",
                "deleted_count": 0
            }
        
        # Delete the chunks
        collection.delete(ids=ids_to_delete)
        
        logger.info(f"Deleted {len(ids_to_delete)} chunks for file: {filename}")
        
        return {
            "status": "success",
            "message": f"Successfully deleted file: {filename}",
            "deleted_count": len(ids_to_delete)
        }
        
    except Exception as e:
        logger.error(f"Error deleting file {filename}: {e}")
        raise RuntimeError(f"Error deleting file {filename}: {e}")


def clear_collection() -> Dict[str, Any]:
    """
    Clear all data from the collection.
    
    This deletes the collection and recreates it empty.
    
    Returns:
        Dictionary with clear operation results
    """
    try:
        client = get_chroma_client()
        
        # Delete the existing collection
        try:
            client.delete_collection(name=COLLECTION_NAME)
            logger.info(f"Deleted collection '{COLLECTION_NAME}'")
        except Exception as e:
            logger.warning(f"Collection deletion warning (may not exist): {e}")
        
        # Recreate the collection
        collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"description": "Document chunks for RAG system"}
        )
        logger.info(f"Recreated collection '{COLLECTION_NAME}'")
        
        return {
            "status": "success",
            "message": "All data cleared successfully",
            "collection_name": COLLECTION_NAME
        }
    except Exception as e:
        logger.error(f"Error clearing collection: {e}")
        raise RuntimeError(f"Error clearing collection: {e}")

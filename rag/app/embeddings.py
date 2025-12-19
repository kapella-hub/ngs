"""Embeddings module using sentence-transformers."""
import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import List

from app.config import settings

logger = logging.getLogger(__name__)


# Configure Hugging Face environment as early as possible so that
# sentence_transformers / huggingface_hub pick up offline and SSL
# settings before making any network calls.
if settings.hf_offline:
    logger.info("HF offline mode enabled - forcing local cache only for Hugging Face models")
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

if not settings.hf_ssl_verify:
    logger.warning(
        "SSL verification is disabled via settings.hf_ssl_verify - "
        "this is not recommended for production"
    )
    os.environ.setdefault("CURL_CA_BUNDLE", "")
    os.environ.setdefault("REQUESTS_CA_BUNDLE", "")


from sentence_transformers import SentenceTransformer


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    """
    Load and cache the sentence transformer model.
    
    Returns:
        SentenceTransformer: Initialized embedding model
    """
    logger.info(f"Loading embedding model: {settings.embedding_model_name}")
    logger.info(f"Device: {settings.embedding_device}")
    
    # Configure proxy settings
    if settings.hf_proxy:
        logger.info(f"Using proxy: {settings.hf_proxy}")
        os.environ["HTTP_PROXY"] = settings.hf_proxy
        os.environ["HTTPS_PROXY"] = settings.hf_proxy
    
    # Configure SSL verification
    if not settings.hf_ssl_verify:
        logger.warning("SSL verification is disabled - this is not recommended for production")
        os.environ["CURL_CA_BUNDLE"] = ""
        os.environ["REQUESTS_CA_BUNDLE"] = ""
    
    # Configure offline mode
    if settings.hf_offline:
        logger.info("Using offline mode - models must be pre-downloaded")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    
    # Ensure cache directory exists
    cache_dir = Path(settings.embedding_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"Using cache directory: {cache_dir.absolute()}")
    
    try:
        model = SentenceTransformer(
            settings.embedding_model_name,
            device=settings.embedding_device,
            cache_folder=str(cache_dir.absolute())
        )
        logger.info("Embedding model loaded successfully")
        return model
    except Exception as e:
        logger.error(f"Failed to load embedding model: {e}")
        if settings.hf_offline:
            logger.error(
                f"Offline mode is enabled. Make sure the model is downloaded to: {cache_dir.absolute()}"
            )
        else:
            logger.error(
                "If you're behind a proxy or firewall, configure HF_PROXY in .env or enable HF_OFFLINE mode"
            )
        raise RuntimeError(f"Failed to load embedding model: {e}")


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Generate embeddings for a list of texts.
    
    Args:
        texts: List of text strings to embed
        
    Returns:
        List of embedding vectors (each vector is a list of floats)
    """
    if not texts:
        return []
    
    model = get_embedding_model()
    
    logger.debug(f"Embedding {len(texts)} texts")
    
    try:
        # encode returns numpy array, convert to list of lists
        embeddings = model.encode(
            texts,
            show_progress_bar=False,
            convert_to_numpy=True
        )
        
        # Convert numpy array to list of lists
        embeddings_list = embeddings.tolist()
        
        logger.debug(f"Generated {len(embeddings_list)} embeddings")
        return embeddings_list
    except Exception as e:
        logger.error(f"Error generating embeddings: {e}")
        raise RuntimeError(f"Error generating embeddings: {e}")


def embed_query(query: str) -> List[float]:
    """
    Generate embedding for a single query string.
    
    Args:
        query: Query text to embed
        
    Returns:
        Embedding vector as a list of floats
    """
    embeddings = embed_texts([query])
    return embeddings[0] if embeddings else []

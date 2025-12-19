"""Main entry point for the Local RAG System."""
import logging

import uvicorn

from app.config import settings

# Configure logging
logging.basicConfig(
    level=settings.log_level,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def main():
    """Run the FastAPI application."""
    logger.info("Starting Local RAG System...")
    logger.info(f"Host: {settings.app_host}")
    logger.info(f"Port: {settings.app_port}")
    logger.info(f"LLM Model: {settings.llm_model_path}")
    logger.info(f"Embedding Model: {settings.embedding_model_name}")
    logger.info(f"Vector Store: {settings.vector_db_dir}")
    
    # Check if model exists
    if not settings.validate_model_exists():
        logger.warning(
            f"LLM model not found at {settings.llm_model_path}. "
            f"The /ask endpoint will fail until a model is placed in the models/ directory."
        )
    
    # Run server
    uvicorn.run(
        "app.api:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True
    )


if __name__ == "__main__":
    main()

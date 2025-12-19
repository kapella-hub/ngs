"""Configuration management using pydantic-settings."""
import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from .env file."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )
    
    # Server configuration
    app_host: str = Field(default="0.0.0.0", description="Server host")
    app_port: int = Field(default=8001, description="Server port")
    
    # Paths
    data_dir: str = Field(default="./data", description="Base data directory")
    upload_dir: str = Field(default="./data/uploads", description="Document upload directory")
    vector_db_dir: str = Field(default="./data/chroma", description="ChromaDB storage directory")
    image_dir: str = Field(default="./data/images", description="Extracted images storage directory")
    llm_model_path: str = Field(default="./models/llama-model.gguf", description="Path to .gguf model file")
    
    # LLM runtime configuration
    llm_context_size: int = Field(default=4096, description="Context window size")
    llm_max_tokens: int = Field(default=512, description="Maximum tokens to generate")
    llm_n_threads: int = Field(default=4, description="Number of CPU threads")
    llm_n_gpu_layers: int = Field(default=0, description="Number of layers to offload to GPU (0=CPU only)")
    llm_temperature: float = Field(default=0.1, description="Temperature for generation")
    
    # Embeddings configuration
    embedding_model_name: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Sentence transformer model name"
    )
    embedding_device: Literal["cpu", "cuda", "mps"] = Field(
        default="cpu",
        description="Device for embeddings (cpu/cuda/mps)"
    )
    embedding_cache_dir: str = Field(
        default="./models/sentence-transformers",
        description="Local cache directory for embedding models"
    )
    
    # Network configuration
    hf_proxy: str = Field(
        default="",
        description="HTTP/HTTPS proxy for Hugging Face downloads (e.g., http://proxy.example.com:8080)"
    )
    hf_ssl_verify: bool = Field(
        default=True,
        description="Verify SSL certificates for Hugging Face downloads"
    )
    hf_offline: bool = Field(
        default=False,
        description="Use offline mode (requires pre-downloaded models)"
    )
    
    # Chunking & retrieval
    chunk_size: int = Field(default=800, description="Character chunk size")
    chunk_overlap: int = Field(default=200, description="Chunk overlap")
    chunking_strategy: Literal["simple", "smart", "paragraph"] = Field(
        default="smart",
        description="Chunking strategy: simple (character-based), smart (sentence-aware), paragraph (preserves structure)"
    )
    top_k: int = Field(default=8, description="Number of chunks to retrieve")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level")
    
    def ensure_directories(self) -> None:
        """Create necessary directories if they don't exist."""
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        Path(self.upload_dir).mkdir(parents=True, exist_ok=True)
        Path(self.vector_db_dir).mkdir(parents=True, exist_ok=True)
        Path(self.image_dir).mkdir(parents=True, exist_ok=True)
        
        # Create models directory if it doesn't exist
        model_dir = Path(self.llm_model_path).parent
        model_dir.mkdir(parents=True, exist_ok=True)
    
    def validate_model_exists(self) -> bool:
        """Check if the LLM model file exists."""
        return Path(self.llm_model_path).exists()


# Global settings instance
settings = Settings()
settings.ensure_directories()

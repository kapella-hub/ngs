"""Script to pre-download embedding model for offline use."""
import os
import sys
from pathlib import Path

from sentence_transformers import SentenceTransformer


# Default model configuration
DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_CACHE_DIR = "./models/sentence-transformers"


def download_model(
    model_name: str = DEFAULT_MODEL_NAME,
    cache_dir: str = DEFAULT_CACHE_DIR,
    proxy: str = None,
    verify_ssl: bool = True
):
    """
    Download embedding model to local cache directory.
    
    Args:
        model_name: Name of the sentence-transformers model
        cache_dir: Local directory to cache the model
        proxy: HTTP/HTTPS proxy (e.g., http://proxy.example.com:8080)
        verify_ssl: Whether to verify SSL certificates
    """
    print(f"Downloading model: {model_name}")
    print(f"Cache directory: {cache_dir}")
    
    # Configure proxy if provided
    if proxy:
        print(f"Using proxy: {proxy}")
        os.environ["HTTP_PROXY"] = proxy
        os.environ["HTTPS_PROXY"] = proxy
    
    # Configure SSL verification
    if not verify_ssl:
        print("WARNING: SSL verification disabled")
        os.environ["CURL_CA_BUNDLE"] = ""
        os.environ["REQUESTS_CA_BUNDLE"] = ""
    
    # Ensure cache directory exists
    cache_path = Path(cache_dir)
    cache_path.mkdir(parents=True, exist_ok=True)
    
    try:
        print("Starting download...")
        model = SentenceTransformer(
            model_name,
            cache_folder=str(cache_path.absolute())
        )
        print(f"\n✓ Model downloaded successfully!")
        print(f"  Location: {cache_path.absolute()}")
        print(f"\nTo use offline mode, add to your .env file:")
        print(f"  HF_OFFLINE=true")
        print(f"  EMBEDDING_CACHE_DIR={cache_dir}")
        
        # Test the model
        print("\nTesting model...")
        test_embedding = model.encode(["Test sentence"])
        print(f"✓ Model test successful! Embedding dimension: {len(test_embedding[0])}")
        
    except Exception as e:
        print(f"\n✗ Failed to download model: {e}", file=sys.stderr)
        print("\nTroubleshooting tips:", file=sys.stderr)
        print("  1. Check your internet connection", file=sys.stderr)
        print("  2. If behind a proxy, use --proxy option", file=sys.stderr)
        print("  3. If SSL issues persist, use --no-verify-ssl (not recommended)", file=sys.stderr)
        print("  4. Try downloading from a different network", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Download sentence-transformers model for offline use"
    )
    parser.add_argument(
        "--model",
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="Model name (default: sentence-transformers/all-MiniLM-L6-v2)"
    )
    parser.add_argument(
        "--cache-dir",
        default="./models/sentence-transformers",
        help="Cache directory (default: ./models/sentence-transformers)"
    )
    parser.add_argument(
        "--proxy",
        help="HTTP/HTTPS proxy (e.g., http://proxy.example.com:8080)"
    )
    parser.add_argument(
        "--no-verify-ssl",
        action="store_true",
        help="Disable SSL verification (not recommended)"
    )
    
    args = parser.parse_args()
    
    download_model(
        model_name=args.model,
        cache_dir=args.cache_dir,
        proxy=args.proxy,
        verify_ssl=not args.no_verify_ssl
    )

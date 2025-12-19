"""Script to download LLM model (GGUF format) for offline use."""
import os
import sys
from pathlib import Path
from huggingface_hub import hf_hub_download


# Default model configuration - Phi-4-mini (from unsloth, no auth required)
DEFAULT_MODEL_ID = "unsloth/Phi-4-mini-instruct-GGUF"
DEFAULT_FILENAME = "Phi-4-mini-instruct-Q4_K_M.gguf"
DEFAULT_OUTPUT_DIR = "./models"


def download_llm_model(
    model_id: str = DEFAULT_MODEL_ID,
    filename: str = DEFAULT_FILENAME,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    proxy: str = None,
    verify_ssl: bool = True
):
    """
    Download LLM model in GGUF format from Hugging Face.

    Args:
        model_id: Hugging Face model repository ID
        filename: Specific GGUF file to download
        output_dir: Local directory to save the model
        proxy: HTTP/HTTPS proxy (e.g., http://proxy.example.com:8080)
        verify_ssl: Whether to verify SSL certificates
    """
    print(f"Downloading model: {model_id}")
    print(f"File: {filename}")
    print(f"Output directory: {output_dir}")

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
        # Disable SSL verification for huggingface_hub
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context

    # Ensure output directory exists
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        print("\nStarting download...")
        print("This may take a while depending on file size and network speed...")

        # Download the model file
        downloaded_path = hf_hub_download(
            repo_id=model_id,
            filename=filename,
            cache_dir=str(output_path.absolute()),
            local_dir=str(output_path.absolute())
        )

        print(f"\n✓ Model downloaded successfully!")
        print(f"  Location: {downloaded_path}")
        print(f"\nTo use this model, update your .env file:")
        print(f"  LLM_MODEL_PATH={os.path.join(output_dir, filename)}")

        # Display file size
        file_size = Path(downloaded_path).stat().st_size
        size_gb = file_size / (1024 ** 3)
        size_mb = file_size / (1024 ** 2)
        if size_gb >= 1:
            print(f"\nFile size: {size_gb:.2f} GB")
        else:
            print(f"\nFile size: {size_mb:.2f} MB")

    except Exception as e:
        print(f"\n✗ Failed to download model: {e}", file=sys.stderr)
        print("\nTroubleshooting tips:", file=sys.stderr)
        print("  1. Check your internet connection", file=sys.stderr)
        print("  2. Verify the model ID and filename are correct", file=sys.stderr)
        print("  3. If behind a proxy, use --proxy option", file=sys.stderr)
        print("  4. If SSL issues persist, use --no-verify-ssl (not recommended)", file=sys.stderr)
        print("  5. Try downloading from a different network", file=sys.stderr)
        print("\nRun with --list-models to see available models", file=sys.stderr)
        sys.exit(1)


def list_popular_models():
    """Print a list of popular GGUF models."""
    print("\n=== Popular GGUF Models ===\n")

    models = [
        {
            "name": "Phi-4 Mini Instruct (RECOMMENDED - Latest & Best)",
            "model_id": "bartowski/Phi-4-mini-instruct-GGUF",
            "files": [
                "Phi-4-mini-instruct-Q4_K_M.gguf (~2.5 GB) - Best for CPU",
                "Phi-4-mini-instruct-Q5_K_M.gguf (~3.0 GB) - Better quality",
                "Phi-4-mini-instruct-Q8_0.gguf (~4.0 GB) - Highest quality"
            ]
        },
        {
            "name": "Phi-3.1 Mini 4K Instruct (Previous Gen)",
            "model_id": "bartowski/Phi-3.1-mini-4k-instruct-GGUF",
            "files": [
                "Phi-3.1-mini-4k-instruct-Q4_K_M.gguf (2.3 GB) - Best for CPU",
                "Phi-3.1-mini-4k-instruct-Q5_K_M.gguf (2.7 GB) - Better quality",
                "Phi-3.1-mini-4k-instruct-Q8_0.gguf (3.9 GB) - Highest quality"
            ]
        },
        {
            "name": "Llama 3.2 3B Instruct",
            "model_id": "bartowski/Llama-3.2-3B-Instruct-GGUF",
            "files": [
                "Llama-3.2-3B-Instruct-Q4_K_M.gguf (2.0 GB) - Good balance",
                "Llama-3.2-3B-Instruct-Q5_K_M.gguf (2.4 GB) - Better quality",
                "Llama-3.2-3B-Instruct-Q8_0.gguf (3.2 GB) - Highest quality"
            ]
        },
        {
            "name": "Llama 3.2 1B Instruct (Fastest)",
            "model_id": "bartowski/Llama-3.2-1B-Instruct-GGUF",
            "files": [
                "Llama-3.2-1B-Instruct-Q4_K_M.gguf (~700 MB)",
                "Llama-3.2-1B-Instruct-Q5_K_M.gguf (~850 MB)"
            ]
        },
        {
            "name": "Qwen 2.5 3B Instruct",
            "model_id": "Qwen/Qwen2.5-3B-Instruct-GGUF",
            "files": [
                "qwen2.5-3b-instruct-q4_k_m.gguf (~2.0 GB)",
                "qwen2.5-3b-instruct-q5_k_m.gguf (~2.4 GB)"
            ]
        },
        {
            "name": "Mistral 7B Instruct v0.3",
            "model_id": "bartowski/Mistral-7B-Instruct-v0.3-GGUF",
            "files": [
                "Mistral-7B-Instruct-v0.3-Q4_K_M.gguf (4.4 GB)",
                "Mistral-7B-Instruct-v0.3-Q5_K_M.gguf (5.3 GB)"
            ]
        }
    ]

    for model in models:
        print(f"{model['name']}")
        print(f"  Model ID: {model['model_id']}")
        print(f"  Files:")
        for file in model['files']:
            print(f"    - {file}")
        print()

    print("Example usage:")
    print(f"  python download_llm_model.py  # Downloads default: {DEFAULT_MODEL_ID}")
    print()
    print("  python download_llm_model.py --model-id bartowski/Phi-4-mini-instruct-GGUF \\")
    print("                               --filename Phi-4-mini-instruct-Q4_K_M.gguf")
    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Download LLM model in GGUF format for offline use",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Examples:
  # Download Phi-4-mini (default, recommended)
  python download_llm_model.py

  # Download specific model
  python download_llm_model.py --model-id bartowski/Phi-4-mini-instruct-GGUF \\
                               --filename Phi-4-mini-instruct-Q4_K_M.gguf

  # Download Llama 3.2 1B (fastest, smallest)
  python download_llm_model.py --model-id bartowski/Llama-3.2-1B-Instruct-GGUF \\
                               --filename Llama-3.2-1B-Instruct-Q4_K_M.gguf

  # Download with proxy
  python download_llm_model.py --proxy http://proxy.example.com:8080

  # List popular models
  python download_llm_model.py --list-models
        """
    )
    parser.add_argument(
        "--model-id",
        default=DEFAULT_MODEL_ID,
        help=f"Hugging Face model repository ID (default: {DEFAULT_MODEL_ID})"
    )
    parser.add_argument(
        "--filename",
        default=DEFAULT_FILENAME,
        help=f"Specific GGUF file to download (default: {DEFAULT_FILENAME})"
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})"
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
    parser.add_argument(
        "--list-models",
        action="store_true",
        help="List popular GGUF models and exit"
    )

    args = parser.parse_args()

    if args.list_models:
        list_popular_models()
        sys.exit(0)

    download_llm_model(
        model_id=args.model_id,
        filename=args.filename,
        output_dir=args.output_dir,
        proxy=args.proxy,
        verify_ssl=not args.no_verify_ssl
    )

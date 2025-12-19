"""Local LLM wrapper using llama-cpp-python."""
import logging
import traceback
from functools import lru_cache
from typing import Optional

from llama_cpp import Llama

from app.config import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_llm() -> Llama:
    """
    Load and cache the Llama model.
    
    Returns:
        Llama: Initialized Llama model instance
        
    Raises:
        FileNotFoundError: If model file doesn't exist
        RuntimeError: If model loading fails
    """
    if not settings.validate_model_exists():
        raise FileNotFoundError(
            f"Model file not found at {settings.llm_model_path}. "
            f"Please download a .gguf model and place it in the models/ directory."
        )
    
    logger.info(f"Loading LLM from {settings.llm_model_path}")
    logger.info(f"Configuration: context_size={settings.llm_context_size}, "
                f"n_threads={settings.llm_n_threads}, "
                f"n_gpu_layers={settings.llm_n_gpu_layers}")
    
    try:
        llm = Llama(
            model_path=settings.llm_model_path,
            n_ctx=settings.llm_context_size,
            n_threads=settings.llm_n_threads,
            n_gpu_layers=settings.llm_n_gpu_layers,
            verbose=True  # Enable verbose to capture loading errors
        )
        logger.info("LLM loaded successfully")
        return llm
    except AssertionError as e:
        # Catch AssertionError specifically - usually indicates corrupted/incomplete model file
        error_msg = (
            "Model file appears to be corrupted or incomplete. "
            "Common causes: incomplete download, file transfer error, or incompatible format. "
            "Please re-download the model file."
        )
        logger.error(f"Failed to load LLM: {error_msg}")
        logger.error(f"Original error: {type(e).__name__}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise RuntimeError(error_msg)
    except Exception as e:
        logger.error(f"Failed to load LLM: {e}")
        logger.error(f"Exception type: {type(e).__name__}")
        logger.error(f"Traceback:\n{traceback.format_exc()}")
        raise RuntimeError(f"Failed to load LLM: {e}")


def _detect_model_type() -> str:
    """
    Detect the model type based on the model path.

    Returns:
        str: Model type identifier ("mistral", "phi3", or "llama")
    """
    model_path_lower = settings.llm_model_path.lower()
    if "mistral" in model_path_lower:
        return "mistral"
    elif "phi-3" in model_path_lower or "phi3" in model_path_lower:
        return "phi3"
    else:
        return "llama"


def _is_mistral_model() -> bool:
    """
    Detect if the loaded model is a Mistral model based on the model path.

    Returns:
        bool: True if Mistral model, False otherwise
    """
    return _detect_model_type() == "mistral"


def generate_answer(
    prompt: str,
    system_prompt: Optional[str] = None,
    max_tokens: Optional[int] = None,
    temperature: Optional[float] = None,
    estimated_prompt_tokens: Optional[int] = None
) -> str:
    """
    Generate an answer using the local LLM.
    
    Args:
        prompt: User prompt/question
        system_prompt: Optional system prompt for instructions
        max_tokens: Maximum tokens to generate (defaults to settings, adjusted for prompt size)
        temperature: Temperature for sampling (defaults to settings)
        estimated_prompt_tokens: Estimated token count of the prompt (for dynamic max_tokens)
        
    Returns:
        str: Generated text response
    """
    llm = get_llm()
    
    temperature = temperature or settings.llm_temperature
    
    # Build chat-style prompt based on model type (do this before token calculation)
    model_type = _detect_model_type()
    if system_prompt:
        if model_type == "mistral":
            # Mistral 7B Instruct v0.2 format
            # Format: [INST] system_instruction\n\nuser_query [/INST]
            full_prompt = f"[INST] {system_prompt}\n\n{prompt} [/INST]"
            stop_tokens = ["[INST]", "</s>"]
            logger.debug("Using Mistral prompt format")
        elif model_type == "phi3":
            # Phi-3 ChatML format
            # Format: <|system|>\n{system}<|end|>\n<|user|>\n{user}<|end|>\n<|assistant|>\n
            full_prompt = f"<|system|>\n{system_prompt}<|end|>\n<|user|>\n{prompt}<|end|>\n<|assistant|>\n"
            stop_tokens = ["<|end|>", "<|user|>", "<|system|>"]
            logger.debug("Using Phi-3 ChatML prompt format")
        else:
            # Llama-style format (default)
            full_prompt = f"""<|system|>
{system_prompt}
<|user|>
{prompt}
<|assistant|>
"""
            stop_tokens = ["<|user|>", "<|system|>"]
            logger.debug("Using Llama prompt format")
    else:
        full_prompt = prompt
        stop_tokens = []
    
    # Calculate safe max_tokens based on ACTUAL full prompt size
    if estimated_prompt_tokens is not None:
        # Re-estimate based on the actual formatted prompt
        from app.token_manager import estimate_tokens
        actual_prompt_tokens = estimate_tokens(full_prompt)
        
        # Leave safety margin for tokenization differences
        safety_margin = 50
        available_tokens = settings.llm_context_size - actual_prompt_tokens - safety_margin
        
        # Use the smaller of: requested max_tokens or available tokens
        requested_max = max_tokens or settings.llm_max_tokens
        max_tokens = max(1, min(requested_max, available_tokens))
        
        logger.info(
            f"Token allocation: estimated ~{estimated_prompt_tokens}, "
            f"actual formatted ~{actual_prompt_tokens}, "
            f"generation {max_tokens}, context_size {settings.llm_context_size}"
        )
        
        if max_tokens < requested_max:
            logger.warning(
                f"Reduced max_tokens from {requested_max} to {max_tokens} "
                f"to fit within context window"
            )
    else:
        max_tokens = max_tokens or settings.llm_max_tokens
    
    logger.debug(f"Generating answer with max_tokens={max_tokens}, temperature={temperature}")
    
    try:
        response = llm(
            full_prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=stop_tokens if stop_tokens else None,
            echo=False
        )
        
        # Extract text from response
        answer = response["choices"][0]["text"].strip()
        logger.debug(f"Generated answer: {answer[:100]}...")
        
        return answer
    except Exception as e:
        logger.error(f"Error generating answer: {e}")
        raise RuntimeError(f"Error generating answer: {e}")

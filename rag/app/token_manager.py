"""Token management utilities for preventing context window overflow."""
import logging
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger(__name__)

# Cache for the tokenizer
_tokenizer_cache: Optional[Any] = None


def get_tokenizer():
    """Get cached tokenizer from llama_cpp."""
    global _tokenizer_cache
    if _tokenizer_cache is None:
        try:
            from app.llm import get_llm
            llm = get_llm()
            _tokenizer_cache = llm
        except Exception as e:
            logger.warning(f"Failed to get tokenizer, falling back to estimation: {e}")
    return _tokenizer_cache


def estimate_tokens(text: str, use_actual_tokenizer: bool = True) -> int:
    """
    Estimate or count the number of tokens in a text string.
    
    Args:
        text: Input text string
        use_actual_tokenizer: If True, use llama_cpp's tokenizer for accurate count
        
    Returns:
        Token count (accurate if tokenizer available, estimated otherwise)
    """
    if not text:
        return 0
    
    if use_actual_tokenizer:
        try:
            tokenizer = get_tokenizer()
            if tokenizer is not None:
                # Use llama_cpp's tokenize method for accurate count
                tokens = tokenizer.tokenize(text.encode('utf-8'))
                return len(tokens)
        except Exception as e:
            logger.debug(f"Tokenizer not available, using estimation: {e}")
    
    # Fallback to character-based estimation
    # Adjusted ratio: more conservative at ~2.5 chars per token for safety
    return max(1, len(text) // 2)


def truncate_text(text: str, max_tokens: int) -> str:
    """
    Truncate text to fit within a token budget.
    
    Args:
        text: Text to truncate
        max_tokens: Maximum number of tokens allowed
        
    Returns:
        Truncated text
    """
    if estimate_tokens(text) <= max_tokens:
        return text
    
    # Calculate target character count
    target_chars = max_tokens * 4
    
    if len(text) <= target_chars:
        return text
    
    # Truncate and add ellipsis
    return text[:target_chars - 3] + "..."


def build_prompt_with_budget(
    system_prompt: str,
    user_query: str,
    conversation_history: List[Dict[str, str]],
    context_chunks: List[str],
    max_context_tokens: int
) -> Tuple[str, str, int]:
    """
    Build a prompt that fits within the token budget.
    
    Priority order:
    1. System prompt (always included, truncated if necessary)
    2. User query (always included)
    3. Recent conversation history (truncated from oldest)
    4. Retrieved context (reduced number of chunks if needed)
    
    Args:
        system_prompt: System instructions for the LLM
        user_query: Current user question
        conversation_history: List of previous turns [{"role": "user"|"assistant", "content": str}]
        context_chunks: List of retrieved document chunks
        max_context_tokens: Maximum tokens available for the entire prompt
        
    Returns:
        Tuple of (system_prompt, user_prompt, estimated_total_tokens)
    """
    # Reserve token budget
    reserved_system = min(800, max_context_tokens // 4)  # Max 800 tokens for system prompt
    reserved_query = estimate_tokens(user_query) + 50  # Query + formatting
    remaining_budget = max_context_tokens - reserved_system - reserved_query
    
    logger.debug(f"Token budget: {max_context_tokens} total, {remaining_budget} for history+context")
    
    # Truncate system prompt if necessary
    system_tokens = estimate_tokens(system_prompt)
    if system_tokens > reserved_system:
        logger.warning(f"System prompt ({system_tokens} tokens) exceeds budget ({reserved_system}), truncating")
        system_prompt = truncate_text(system_prompt, reserved_system)
        system_tokens = reserved_system
    
    # Build conversation history transcript (newest to oldest, reverse later)
    history_transcript = ""
    history_tokens = 0
    
    if conversation_history:
        # Process from newest to oldest so we keep recent context
        history_lines = []
        for turn in reversed(conversation_history):
            role_label = "User" if turn["role"] == "user" else "Assistant"
            turn_line = f"{role_label}: {turn['content']}"
            turn_tokens = estimate_tokens(turn_line)
            
            # Check if we can afford this turn
            if history_tokens + turn_tokens > remaining_budget // 2:  # Use max 50% for history
                logger.debug(f"Truncating history: {len(history_lines)} turns kept, stopping here")
                break
            
            history_lines.append(turn_line)
            history_tokens += turn_tokens
        
        # Reverse back to chronological order
        if history_lines:
            history_transcript = "\n".join(reversed(history_lines)) + "\n\n"
    
    # Calculate remaining budget for context
    context_budget = remaining_budget - history_tokens
    logger.debug(f"History: {history_tokens} tokens, Context budget: {context_budget} tokens")
    
    # Build context from chunks
    context_str = ""
    context_tokens = 0
    chunks_used = 0
    
    for chunk in context_chunks:
        chunk_with_separator = chunk + "\n\n---\n\n"
        chunk_tokens = estimate_tokens(chunk_with_separator)
        
        if context_tokens + chunk_tokens > context_budget:
            logger.debug(f"Context budget exceeded, using {chunks_used}/{len(context_chunks)} chunks")
            break
        
        context_str += chunk_with_separator
        context_tokens += chunk_tokens
        chunks_used += 1
    
    # Remove trailing separator
    if context_str.endswith("\n\n---\n\n"):
        context_str = context_str[:-7]
    
    # Build final user prompt
    user_prompt = f"""{history_transcript}Context from documents:

{context_str}

Question: {user_query}

Answer:"""
    
    # Calculate total tokens
    total_tokens = system_tokens + estimate_tokens(user_prompt)
    
    logger.info(
        f"Prompt built: {total_tokens}/{max_context_tokens} tokens "
        f"(system: {system_tokens}, history: {history_tokens}, "
        f"context: {context_tokens} from {chunks_used} chunks, query: {reserved_query})"
    )
    
    if total_tokens > max_context_tokens:
        logger.warning(
            f"Prompt still exceeds budget: {total_tokens} > {max_context_tokens}. "
            f"Further truncation may be needed."
        )
    
    return system_prompt, user_prompt, total_tokens

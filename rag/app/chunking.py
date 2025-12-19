"""Text chunking utilities."""
import logging
import re
from typing import List, Dict, Any

from app.config import settings

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    """
    Normalize text by cleaning up whitespace and formatting issues.
    
    Args:
        text: Text to normalize
        
    Returns:
        Normalized text
    """
    if not text:
        return ""
    
    # Replace multiple spaces with single space
    text = re.sub(r' +', ' ', text)
    
    # Replace multiple newlines with double newline (paragraph separator)
    text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
    
    # Remove trailing whitespace from lines
    text = '\n'.join(line.rstrip() for line in text.split('\n'))
    
    # Remove leading/trailing whitespace
    text = text.strip()
    
    return text


def split_into_sentences(text: str) -> List[str]:
    """
    Split text into sentences using improved patterns.
    Handles common abbreviations, decimals, and other edge cases.
    
    Args:
        text: Text to split
        
    Returns:
        List of sentences
    """
    if not text:
        return []
    
    # Common abbreviations that shouldn't trigger sentence breaks
    abbreviations = ['Mr.', 'Mrs.', 'Ms.', 'Dr.', 'Prof.', 'Sr.', 'Jr.', 
                     'vs.', 'etc.', 'Inc.', 'Ltd.', 'Co.', 'Corp.',
                     'Ave.', 'St.', 'Rd.', 'Blvd.', 'Ph.D.', 'M.D.', 
                     'B.A.', 'M.A.', 'U.S.', 'U.K.', 'E.g.', 'I.e.']
    
    # Replace abbreviations temporarily to protect them
    protected_text = text
    placeholders = {}
    for i, abbr in enumerate(abbreviations):
        placeholder = f"__ABBR{i}__"
        if abbr in protected_text:
            placeholders[placeholder] = abbr
            protected_text = protected_text.replace(abbr, placeholder)
    
    # Pattern for sentence boundaries
    # Match periods, exclamation marks, or question marks
    # followed by whitespace and a capital letter, or end of string
    # but not after a digit (for decimals like 1.5)
    sentence_pattern = r'(?<!\d)([.!?]+)\s+(?=[A-Z])|([.!?]+)$'
    
    # Split by sentence boundaries
    sentences = re.split(sentence_pattern, protected_text)
    
    # Reconstruct sentences with their punctuation and restore abbreviations
    result = []
    i = 0
    while i < len(sentences):
        if sentences[i] and sentences[i].strip():
            # Build sentence with its punctuation
            sentence = sentences[i]
            
            # Add punctuation if present in next element
            if i + 1 < len(sentences) and sentences[i + 1] and sentences[i + 1] in '.!?':
                sentence += sentences[i + 1]
                i += 1
            elif i + 2 < len(sentences) and sentences[i + 2] and sentences[i + 2] in '.!?':
                sentence += sentences[i + 2]
                i += 1
            
            # Restore abbreviations
            for placeholder, abbr in placeholders.items():
                sentence = sentence.replace(placeholder, abbr)
            
            sentence = sentence.strip()
            if sentence:
                result.append(sentence)
        
        i += 1
    
    # If no sentences were found, return the original text as one sentence
    if not result and text.strip():
        # Restore abbreviations in original text
        restored_text = text
        for placeholder, abbr in placeholders.items():
            restored_text = restored_text.replace(placeholder, abbr)
        return [restored_text.strip()]
    
    return result


def split_into_paragraphs(text: str) -> List[str]:
    """
    Split text into paragraphs.
    
    Args:
        text: Text to split
        
    Returns:
        List of paragraphs
    """
    if not text:
        return []
    
    # Split by double newlines (paragraph separator)
    paragraphs = re.split(r'\n\s*\n+', text)
    
    return [p.strip() for p in paragraphs if p.strip()]


def chunk_text(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None
) -> List[str]:
    """
    Split text into overlapping chunks.
    
    Args:
        text: Text to chunk
        chunk_size: Maximum characters per chunk (defaults to settings)
        chunk_overlap: Number of overlapping characters (defaults to settings)
        
    Returns:
        List of text chunks
    """
    if not text or not text.strip():
        return []
    
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap
    
    # Ensure overlap is smaller than chunk size
    if chunk_overlap >= chunk_size:
        chunk_overlap = chunk_size // 2
        logger.warning(f"Overlap too large, adjusted to {chunk_overlap}")
    
    chunks = []
    start = 0
    text_length = len(text)
    
    while start < text_length:
        end = start + chunk_size
        
        # Get chunk
        chunk = text[start:end]
        
        # Only add non-empty chunks
        if chunk.strip():
            chunks.append(chunk)
        
        # Move start position
        if end >= text_length:
            break
        
        start = end - chunk_overlap
    
    logger.debug(f"Created {len(chunks)} chunks from text of length {text_length}")
    return chunks


def chunk_text_smart(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None
) -> List[str]:
    """
    Split text into overlapping chunks with improved sentence boundary detection.
    
    Uses advanced regex patterns to detect sentence boundaries while handling:
    - Common abbreviations (Dr., Mr., Inc., etc.)
    - Decimal numbers
    - Multiple punctuation marks
    
    Args:
        text: Text to chunk
        chunk_size: Maximum characters per chunk (defaults to settings)
        chunk_overlap: Number of overlapping characters (defaults to settings)
        
    Returns:
        List of text chunks
    """
    if not text or not text.strip():
        return []
    
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap
    
    # Ensure overlap is smaller than chunk size
    if chunk_overlap >= chunk_size:
        chunk_overlap = chunk_size // 2
        logger.warning(f"Overlap too large, adjusted to {chunk_overlap}")
    
    # Normalize text first
    text = normalize_text(text)
    
    # Split into sentences using improved detection
    sentences = split_into_sentences(text)
    
    if not sentences:
        # Fallback to simple chunking if sentence detection fails
        return chunk_text(text, chunk_size, chunk_overlap)
    
    # Build chunks from sentences
    chunks = []
    current_chunk = ""
    overlap_sentences = []
    
    for sentence in sentences:
        # Try adding sentence to current chunk
        test_chunk = current_chunk + (" " if current_chunk else "") + sentence
        
        if len(test_chunk) <= chunk_size:
            # Sentence fits, add it
            current_chunk = test_chunk
            overlap_sentences.append(sentence)
        else:
            # Current chunk is full, save it
            if current_chunk.strip():
                chunks.append(current_chunk.strip())
            
            # Start new chunk with overlap
            if chunk_overlap > 0 and overlap_sentences:
                # Calculate how many sentences to include for overlap
                overlap_text = ""
                for overlap_sent in reversed(overlap_sentences):
                    test_overlap = overlap_sent + (" " if overlap_text else "") + overlap_text
                    if len(test_overlap) <= chunk_overlap:
                        overlap_text = test_overlap
                    else:
                        break
                
                # Start new chunk with overlap and current sentence
                if overlap_text:
                    current_chunk = overlap_text + " " + sentence
                    overlap_sentences = [sentence]
                else:
                    current_chunk = sentence
                    overlap_sentences = [sentence]
            else:
                # No overlap, just start with current sentence
                current_chunk = sentence
                overlap_sentences = [sentence]
            
            # If single sentence is larger than chunk_size, split it
            if len(current_chunk) > chunk_size:
                chunks.append(current_chunk.strip())
                current_chunk = ""
                overlap_sentences = []
    
    # Add final chunk
    if current_chunk.strip():
        chunks.append(current_chunk.strip())
    
    logger.debug(f"Created {len(chunks)} smart chunks from {len(sentences)} sentences")
    return chunks


def chunk_text_with_paragraphs(
    text: str,
    chunk_size: int | None = None,
    chunk_overlap: int | None = None
) -> List[Dict[str, Any]]:
    """
    Split text into chunks that respect paragraph boundaries and include metadata.
    
    This is the most precise chunking method, preserving document structure.
    Returns chunks with metadata about their position in the document.
    
    Args:
        text: Text to chunk
        chunk_size: Maximum characters per chunk (defaults to settings)
        chunk_overlap: Number of overlapping characters (defaults to settings)
        
    Returns:
        List of dictionaries with 'text' and 'metadata' keys
    """
    if not text or not text.strip():
        return []
    
    chunk_size = chunk_size or settings.chunk_size
    chunk_overlap = chunk_overlap or settings.chunk_overlap
    
    # Normalize text
    text = normalize_text(text)
    
    # Split into paragraphs
    paragraphs = split_into_paragraphs(text)
    
    if not paragraphs:
        # Fallback to simple chunking
        simple_chunks = chunk_text_smart(text, chunk_size, chunk_overlap)
        return [{"text": chunk, "metadata": {}} for chunk in simple_chunks]
    
    chunks_with_metadata = []
    current_chunk = ""
    current_para_indices = []
    
    for para_idx, paragraph in enumerate(paragraphs):
        # Split paragraph into sentences for finer control
        sentences = split_into_sentences(paragraph)
        
        for sentence in sentences:
            test_chunk = current_chunk + ("\n\n" if current_chunk else "") + sentence
            
            if len(test_chunk) <= chunk_size:
                # Sentence fits
                if not current_chunk:
                    current_chunk = sentence
                    current_para_indices = [para_idx]
                else:
                    current_chunk = test_chunk
                    if para_idx not in current_para_indices:
                        current_para_indices.append(para_idx)
            else:
                # Save current chunk
                if current_chunk.strip():
                    chunks_with_metadata.append({
                        "text": current_chunk.strip(),
                        "metadata": {
                            "paragraph_indices": current_para_indices.copy(),
                            "paragraph_start": current_para_indices[0] if current_para_indices else 0,
                            "paragraph_end": current_para_indices[-1] if current_para_indices else 0
                        }
                    })
                
                # Start new chunk
                current_chunk = sentence
                current_para_indices = [para_idx]
    
    # Add final chunk
    if current_chunk.strip():
        chunks_with_metadata.append({
            "text": current_chunk.strip(),
            "metadata": {
                "paragraph_indices": current_para_indices,
                "paragraph_start": current_para_indices[0] if current_para_indices else 0,
                "paragraph_end": current_para_indices[-1] if current_para_indices else 0
            }
        })
    
    logger.debug(f"Created {len(chunks_with_metadata)} paragraph-aware chunks from {len(paragraphs)} paragraphs")
    return chunks_with_metadata

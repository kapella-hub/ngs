"""Conversation memory management for multi-turn interactions."""
import logging
import threading
from collections import deque
from typing import Literal, TypedDict

logger = logging.getLogger(__name__)


class Turn(TypedDict):
    """Represents a single turn in a conversation."""
    role: Literal["user", "assistant"]
    content: str


class ConversationStore:
    """
    Thread-safe in-memory store for conversation history.
    
    Each conversation is identified by a conversation_id and stores up to
    max_turns recent turns. Older turns are automatically dropped when the
    limit is reached.
    
    This implementation uses in-memory storage and will be lost on server
    restart. The API shape is designed to be easily extended to Redis or
    a database backend in the future.
    """
    
    def __init__(self, max_turns: int = 8):
        """
        Initialize the conversation store.
        
        Args:
            max_turns: Maximum number of turns to keep per conversation.
                      Older turns are automatically dropped. Default is 8.
                      
        Note:
            In the future, this could read from settings:
            max_turns = getattr(settings, 'MAX_CONVERSATION_TURNS', 8)
        """
        self.max_turns = max_turns
        self._conversations: dict[str, deque[Turn]] = {}
        self._lock = threading.Lock()
        logger.info(f"ConversationStore initialized with max_turns={max_turns}")
    
    def add_turn(self, conversation_id: str, role: Literal["user", "assistant"], content: str) -> None:
        """
        Add a turn to the conversation history.
        
        Args:
            conversation_id: Unique identifier for the conversation
            role: Either "user" or "assistant"
            content: The text content of the turn
            
        Note:
            This method is thread-safe. If the conversation doesn't exist,
            it will be created automatically.
        """
        with self._lock:
            if conversation_id not in self._conversations:
                # Create a new deque with maxlen for automatic size limiting
                self._conversations[conversation_id] = deque(maxlen=self.max_turns)
                logger.debug(f"Created new conversation: {conversation_id}")
            
            turn: Turn = {"role": role, "content": content}
            self._conversations[conversation_id].append(turn)
            logger.debug(
                f"Added {role} turn to conversation {conversation_id} "
                f"(total turns: {len(self._conversations[conversation_id])})"
            )
    
    def get_history(self, conversation_id: str) -> list[Turn]:
        """
        Retrieve the conversation history.
        
        Args:
            conversation_id: Unique identifier for the conversation
            
        Returns:
            List of turns ordered from oldest to newest. Returns an empty
            list if the conversation doesn't exist.
            
        Note:
            This method is thread-safe and returns a copy of the history
            to prevent external modifications.
        """
        with self._lock:
            if conversation_id not in self._conversations:
                logger.debug(f"No history found for conversation {conversation_id}")
                return []
            
            # Convert deque to list (creates a copy)
            history = list(self._conversations[conversation_id])
            logger.debug(f"Retrieved {len(history)} turns for conversation {conversation_id}")
            return history
    
    def reset(self, conversation_id: str) -> None:
        """
        Clear all history for a specific conversation.
        
        Args:
            conversation_id: Unique identifier for the conversation
            
        Note:
            This method is thread-safe. If the conversation doesn't exist,
            this is a no-op.
        """
        with self._lock:
            if conversation_id in self._conversations:
                del self._conversations[conversation_id]
                logger.info(f"Reset conversation {conversation_id}")
            else:
                logger.debug(f"Attempted to reset non-existent conversation {conversation_id}")
    
    def get_conversation_count(self) -> int:
        """
        Get the number of active conversations.
        
        Returns:
            Number of conversations currently in memory
            
        Note:
            This method is primarily for monitoring and debugging.
        """
        with self._lock:
            return len(self._conversations)

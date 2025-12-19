"""Cancellation management for long-running ingestion operations."""
import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class CancellationStore:
    """
    Thread-safe store for managing cancellation events for ingestion jobs.
    
    Allows tracking and cancelling long-running URL crawling operations.
    """
    
    def __init__(self):
        """Initialize the cancellation store."""
        self._jobs: Dict[str, threading.Event] = {}
        self._lock = threading.Lock()
        logger.info("CancellationStore initialized")
    
    def create_job(self, job_id: str) -> threading.Event:
        """
        Create a new cancellation event for a job.
        
        Args:
            job_id: Unique identifier for the ingestion job
            
        Returns:
            threading.Event: Event that will be set when cancellation is requested
        """
        with self._lock:
            if job_id in self._jobs:
                logger.warning(f"Job {job_id} already exists, returning existing event")
                return self._jobs[job_id]
            
            event = threading.Event()
            self._jobs[job_id] = event
            logger.info(f"Created cancellation event for job {job_id}")
            return event
    
    def cancel_job(self, job_id: str) -> bool:
        """
        Request cancellation of a job.
        
        Args:
            job_id: Unique identifier for the ingestion job
            
        Returns:
            bool: True if job was found and cancellation requested, False if job not found
        """
        with self._lock:
            if job_id not in self._jobs:
                logger.warning(f"Job {job_id} not found for cancellation")
                return False
            
            event = self._jobs[job_id]
            event.set()
            logger.info(f"Cancellation requested for job {job_id}")
            return True
    
    def is_cancelled(self, job_id: str) -> bool:
        """
        Check if a job has been cancelled.
        
        Args:
            job_id: Unique identifier for the ingestion job
            
        Returns:
            bool: True if cancellation was requested, False otherwise
        """
        with self._lock:
            if job_id not in self._jobs:
                return False
            return self._jobs[job_id].is_set()
    
    def cleanup_job(self, job_id: str) -> None:
        """
        Remove a job from tracking (call after job completes or is cancelled).
        
        Args:
            job_id: Unique identifier for the ingestion job
        """
        with self._lock:
            if job_id in self._jobs:
                del self._jobs[job_id]
                logger.info(f"Cleaned up job {job_id}")
            else:
                logger.debug(f"Job {job_id} not found for cleanup")
    
    def get_active_jobs(self) -> list[str]:
        """
        Get list of active job IDs.
        
        Returns:
            list[str]: List of active job IDs
        """
        with self._lock:
            return list(self._jobs.keys())


# Global cancellation store instance
cancellation_store = CancellationStore()

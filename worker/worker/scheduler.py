"""Scheduler for periodic worker tasks."""
import asyncio
from typing import Optional

import structlog

from worker.correlator import Correlator
from worker.maintenance_engine import MaintenanceEngine
from worker.rag_client import RAGClient

logger = structlog.get_logger()


class Scheduler:
    """Runs periodic background tasks."""

    def __init__(
        self,
        correlator: Correlator,
        maintenance_engine: MaintenanceEngine,
        rag_client: Optional[RAGClient] = None
    ):
        self.correlator = correlator
        self.maintenance_engine = maintenance_engine
        self.rag_client = rag_client
        self.running = False

    async def run(self):
        """Run the scheduler loop."""
        self.running = True
        logger.info("Scheduler started")

        while self.running:
            try:
                # Run periodic tasks
                await self._run_periodic_tasks()
            except Exception as e:
                logger.error("Scheduler error", error=str(e))

            # Wait before next cycle
            await asyncio.sleep(60)  # 1 minute cycle

        logger.info("Scheduler stopped")

    async def stop(self):
        """Stop the scheduler."""
        self.running = False
        if self.rag_client:
            await self.rag_client.close()

    async def _run_periodic_tasks(self):
        """Run all periodic tasks."""
        # Auto-resolve stale incidents
        await self._safe_run(
            "auto_resolve",
            self.correlator.auto_resolve_stale_incidents
        )

        # Match incidents to maintenance windows
        await self._safe_run(
            "maintenance_match",
            self.maintenance_engine.match_incidents_to_maintenance
        )

        # Clear expired maintenance flags
        await self._safe_run(
            "maintenance_clear",
            self.maintenance_engine.clear_expired_maintenance
        )

        # RAG enrichment for incidents
        if self.rag_client:
            await self._safe_run(
                "rag_enrichment",
                self._enrich_incidents
            )

    async def _safe_run(self, task_name: str, func):
        """Safely run a task with error handling."""
        try:
            await func()
        except Exception as e:
            logger.error(f"Task {task_name} failed", error=str(e))

    async def _enrich_incidents(self):
        """Enrich incidents that need RAG processing."""
        incidents = await self.correlator.get_incidents_for_enrichment(limit=5)

        for incident in incidents:
            try:
                await self.rag_client.enrich_incident(str(incident["id"]))
            except Exception as e:
                logger.error(
                    "Failed to enrich incident",
                    incident_id=str(incident["id"]),
                    error=str(e)
                )
            # Rate limit
            await asyncio.sleep(2)

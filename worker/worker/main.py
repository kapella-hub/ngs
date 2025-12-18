"""NGS Worker - Main entry point."""
import asyncio
import signal
import sys

import structlog

from worker.config import get_settings
from worker.logging_config import setup_logging
from worker.database import init_db, close_db
from worker.imap_poller import IMAPPoller
from worker.correlator import Correlator
from worker.maintenance_engine import MaintenanceEngine
from worker.rag_client import RAGClient
from worker.scheduler import Scheduler

setup_logging()
logger = structlog.get_logger()


class NGSWorker:
    """Main worker orchestrator."""

    def __init__(self):
        self.settings = get_settings()
        self.running = False
        self.imap_poller = None
        self.correlator = None
        self.maintenance_engine = None
        self.rag_client = None
        self.scheduler = None

    async def start(self):
        """Start the worker."""
        logger.info("Starting NGS Worker")

        # Initialize database
        await init_db()

        # Initialize components
        self.correlator = Correlator()
        self.maintenance_engine = MaintenanceEngine()

        if self.settings.rag_enabled:
            self.rag_client = RAGClient(
                endpoint=self.settings.rag_endpoint,
                timeout=self.settings.rag_timeout_seconds
            )

        # Initialize email poller based on provider
        provider = self.settings.email_provider.lower()

        if provider == "graph":
            # Microsoft Graph API for Office 365
            if self.settings.graph_tenant_id and self.settings.graph_client_id:
                from worker.graph_client import GraphEmailPoller
                self.imap_poller = GraphEmailPoller(
                    tenant_id=self.settings.graph_tenant_id,
                    client_id=self.settings.graph_client_id,
                    client_secret=self.settings.graph_client_secret,
                    user_email=self.settings.graph_user_email,
                    folders=self.settings.imap_folders_list,
                    poll_interval=self.settings.imap_poll_interval_seconds,
                    backfill_days=self.settings.imap_initial_backfill_days,
                    correlator=self.correlator,
                    maintenance_engine=self.maintenance_engine
                )
                logger.info("Using Microsoft Graph API for email access")
            else:
                logger.warning("Graph API not configured - running in demo mode")

        elif provider == "file":
            # File-based poller - watch folder for .eml/.msg files
            from worker.file_poller import FilePoller
            self.imap_poller = FilePoller(
                watch_path=self.settings.file_watch_path,
                poll_interval=self.settings.imap_poll_interval_seconds,
                correlator=self.correlator,
                maintenance_engine=self.maintenance_engine
            )
            logger.info("Using file-based poller", watch_path=self.settings.file_watch_path)
            logger.info("Drop .eml or .msg files into the watch folder to process them")

        elif provider == "outlook":
            # Outlook COM automation (Windows only)
            try:
                from worker.outlook_poller import OutlookPoller
                self.imap_poller = OutlookPoller(
                    folders=self.settings.imap_folders_list,
                    poll_interval=self.settings.imap_poll_interval_seconds,
                    backfill_days=self.settings.imap_initial_backfill_days,
                    correlator=self.correlator,
                    maintenance_engine=self.maintenance_engine
                )
                logger.info("Using Outlook COM automation for email access")
            except ImportError as e:
                logger.error("Outlook COM not available (requires Windows + pywin32)", error=str(e))
                logger.info("Falling back to file-based poller")
                from worker.file_poller import FilePoller
                self.imap_poller = FilePoller(
                    watch_path=self.settings.file_watch_path,
                    poll_interval=self.settings.imap_poll_interval_seconds,
                    correlator=self.correlator,
                    maintenance_engine=self.maintenance_engine
                )

        elif provider == "imap" and self.settings.imap_host and self.settings.imap_user:
            # Traditional IMAP
            self.imap_poller = IMAPPoller(
                host=self.settings.imap_host,
                port=self.settings.imap_port,
                ssl=self.settings.imap_ssl,
                user=self.settings.imap_user,
                password=self.settings.imap_password,
                folders=self.settings.imap_folders_list,
                poll_interval=self.settings.imap_poll_interval_seconds,
                backfill_days=self.settings.imap_initial_backfill_days,
                correlator=self.correlator,
                maintenance_engine=self.maintenance_engine
            )
            logger.info("Using IMAP for email access")

        else:
            logger.warning("Email access not configured - running in demo mode")

        # Initialize scheduler for periodic tasks
        self.scheduler = Scheduler(
            correlator=self.correlator,
            maintenance_engine=self.maintenance_engine,
            rag_client=self.rag_client
        )

        self.running = True

        # Start all components
        tasks = [self.scheduler.run()]

        if self.imap_poller:
            tasks.append(self.imap_poller.run())

        logger.info("NGS Worker started successfully")

        await asyncio.gather(*tasks)

    async def stop(self):
        """Stop the worker gracefully."""
        logger.info("Stopping NGS Worker")
        self.running = False

        if self.imap_poller:
            await self.imap_poller.stop()

        if self.scheduler:
            await self.scheduler.stop()

        await close_db()
        logger.info("NGS Worker stopped")


async def main():
    """Main entry point."""
    worker = NGSWorker()

    # Setup signal handlers
    loop = asyncio.get_event_loop()

    def signal_handler():
        logger.info("Received shutdown signal")
        asyncio.create_task(worker.stop())

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        await worker.start()
    except KeyboardInterrupt:
        await worker.stop()
    except Exception as e:
        logger.exception("Worker crashed", error=str(e))
        await worker.stop()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

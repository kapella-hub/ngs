"""File-based email poller for local testing.

Watch a folder for .eml or .msg files (drag from Outlook).
Great for testing without configuring IMAP or Graph API.
"""
import asyncio
import email
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

import structlog

from worker.database import get_pool
from worker.parser import EmailParser

logger = structlog.get_logger()


class FilePoller:
    """
    Polls a local folder for email files (.eml, .msg).

    Usage:
    1. Set EMAIL_PROVIDER=file in .env
    2. Set FILE_WATCH_PATH to your folder path
    3. Drag emails from Outlook to that folder
    4. NGS will process them automatically

    Processed files are moved to a 'processed' subfolder.
    """

    def __init__(
        self,
        watch_path: str,
        poll_interval: int,
        correlator,
        maintenance_engine,
    ):
        self.watch_path = Path(watch_path)
        self.poll_interval = poll_interval
        self.correlator = correlator
        self.maintenance_engine = maintenance_engine
        self.parser = EmailParser()
        self.running = False

        # Create directories if needed
        self.watch_path.mkdir(parents=True, exist_ok=True)
        self.processed_path = self.watch_path / "processed"
        self.processed_path.mkdir(exist_ok=True)
        self.failed_path = self.watch_path / "failed"
        self.failed_path.mkdir(exist_ok=True)

    def _parse_eml_file(self, file_path: Path) -> dict:
        """Parse a .eml file."""
        with open(file_path, 'rb') as f:
            msg = email.message_from_binary_file(f)

        return self._extract_email_data(msg, file_path.name)

    def _parse_msg_file(self, file_path: Path) -> Optional[dict]:
        """Parse a .msg file (Outlook format)."""
        try:
            # Try using extract_msg library if available
            import extract_msg

            msg = extract_msg.Message(str(file_path))

            return {
                "subject": msg.subject or "",
                "from_address": msg.sender or "",
                "to_addresses": [msg.to] if msg.to else [],
                "cc_addresses": [msg.cc] if msg.cc else [],
                "date_header": msg.date,
                "body_text": msg.body or "",
                "body_html": msg.htmlBody or "",
                "headers": {},
                "attachments": [
                    {"filename": att.longFilename, "size": len(att.data) if att.data else 0}
                    for att in msg.attachments
                ] if msg.attachments else [],
                "message_id": f"<{uuid4()}@local>",
            }
        except ImportError:
            logger.warning("extract_msg not installed, .msg files not supported. Install with: pip install extract-msg")
            return None
        except Exception as e:
            logger.error("Failed to parse .msg file", error=str(e))
            return None

    def _extract_email_data(self, msg: email.message.Message, filename: str) -> dict:
        """Extract data from email.message.Message object."""
        from email.header import decode_header
        from email.utils import parsedate_to_datetime

        def decode_hdr(value):
            if not value:
                return ""
            try:
                decoded = decode_header(value)
                parts = []
                for part, enc in decoded:
                    if isinstance(part, bytes):
                        parts.append(part.decode(enc or 'utf-8', errors='replace'))
                    else:
                        parts.append(part)
                return " ".join(parts)
            except:
                return str(value)

        # Extract body
        body_text = ""
        body_html = ""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in disposition:
                    attachments.append({
                        "filename": part.get_filename(),
                        "content_type": content_type,
                        "size": len(part.get_payload(decode=True) or b"")
                    })
                elif content_type == "text/plain":
                    try:
                        body_text = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    except:
                        pass
                elif content_type == "text/html":
                    try:
                        body_html = part.get_payload(decode=True).decode('utf-8', errors='replace')
                    except:
                        pass
        else:
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    content = payload.decode('utf-8', errors='replace')
                    if msg.get_content_type() == "text/html":
                        body_html = content
                    else:
                        body_text = content
            except:
                pass

        # Parse date
        date_header = None
        date_str = msg.get("Date")
        if date_str:
            try:
                date_header = parsedate_to_datetime(date_str)
            except:
                pass

        return {
            "subject": decode_hdr(msg.get("Subject", "")),
            "from_address": decode_hdr(msg.get("From", "")),
            "to_addresses": [decode_hdr(a) for a in (msg.get_all("To") or [])],
            "cc_addresses": [decode_hdr(a) for a in (msg.get_all("Cc") or [])],
            "date_header": date_header,
            "body_text": body_text,
            "body_html": body_html,
            "headers": {k: decode_hdr(v) for k, v in msg.items()},
            "attachments": attachments,
            "message_id": msg.get("Message-ID", f"<{uuid4()}@local>"),
        }

    async def _store_email(self, data: dict, folder: str, filename: str) -> Optional[str]:
        """Store email data in database."""
        pool = await get_pool()

        # Use filename hash as UID
        uid = abs(hash(filename)) % (2**31)

        async with pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO raw_emails (
                    folder, uid, message_id, subject, from_address, to_addresses,
                    cc_addresses, date_header, headers, body_text, body_html,
                    attachments, parse_status
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'pending')
                ON CONFLICT (folder, uid) DO NOTHING
                RETURNING id
                """,
                folder, uid, data.get("message_id"), data.get("subject"),
                data.get("from_address"), data.get("to_addresses", []),
                data.get("cc_addresses", []), data.get("date_header"),
                data.get("headers", {}), data.get("body_text"),
                data.get("body_html"), data.get("attachments", [])
            )

            if result:
                return str(result["id"])
            return None

    async def _process_file(self, file_path: Path):
        """Process a single email file."""
        logger.info("Processing email file", file=file_path.name)

        try:
            # Parse based on extension
            if file_path.suffix.lower() == ".eml":
                data = self._parse_eml_file(file_path)
            elif file_path.suffix.lower() == ".msg":
                data = self._parse_msg_file(file_path)
                if not data:
                    raise ValueError("Failed to parse .msg file")
            else:
                logger.warning("Unsupported file type", file=file_path.name)
                return

            # Determine folder from parent directory or use "file"
            folder = file_path.parent.name if file_path.parent != self.watch_path else "file"

            # Store in database
            email_id = await self._store_email(data, folder, file_path.name)

            if email_id:
                # Check if maintenance
                is_maintenance = "maintenance" in file_path.name.lower() or folder.lower() == "maintenance"

                try:
                    if is_maintenance:
                        await self.maintenance_engine.process_email(email_id)
                    else:
                        parsed = await self.parser.parse_email(email_id, folder)
                        if parsed:
                            await self.correlator.process_event(parsed)
                except Exception as e:
                    logger.error("Failed to process email", email_id=email_id, error=str(e))

            # Move to processed folder
            dest = self.processed_path / file_path.name
            file_path.rename(dest)
            logger.info("Email processed", file=file_path.name)

        except Exception as e:
            logger.error("Failed to process file", file=file_path.name, error=str(e))
            # Move to failed folder
            try:
                dest = self.failed_path / file_path.name
                file_path.rename(dest)
            except:
                pass

    async def _scan_folder(self):
        """Scan watch folder for new email files."""
        try:
            # Get all .eml and .msg files
            files: List[Path] = []
            files.extend(self.watch_path.glob("*.eml"))
            files.extend(self.watch_path.glob("*.msg"))

            # Also check subfolders (for organized testing)
            for subdir in self.watch_path.iterdir():
                if subdir.is_dir() and subdir.name not in ("processed", "failed"):
                    files.extend(subdir.glob("*.eml"))
                    files.extend(subdir.glob("*.msg"))

            if files:
                logger.info("Found email files", count=len(files))

            for file_path in sorted(files, key=lambda p: p.stat().st_mtime):
                await self._process_file(file_path)

        except Exception as e:
            logger.error("Error scanning folder", error=str(e))

    async def run(self):
        """Run the file poller."""
        self.running = True
        logger.info("File poller started", watch_path=str(self.watch_path))
        logger.info("Drop .eml or .msg files into the watch folder to process them")

        while self.running:
            await self._scan_folder()

            if self.running:
                await asyncio.sleep(self.poll_interval)

        logger.info("File poller stopped")

    async def stop(self):
        """Stop the file poller."""
        self.running = False

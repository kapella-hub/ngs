"""IMAP email poller for alert ingestion."""
import asyncio
import email
import imaplib
import ssl
from datetime import datetime, timedelta
from email.header import decode_header
from email.utils import parsedate_to_datetime
from typing import List, Optional, Dict, Any

import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from worker.database import get_pool
from worker.parser import EmailParser
from worker.correlator import Correlator
from worker.maintenance_engine import MaintenanceEngine

logger = structlog.get_logger()


class IMAPPoller:
    """Polls IMAP folders for new emails."""

    def __init__(
        self,
        host: str,
        port: int,
        ssl: bool,
        user: str,
        password: str,
        folders: List[str],
        poll_interval: int,
        backfill_days: int,
        correlator: Correlator,
        maintenance_engine: MaintenanceEngine
    ):
        self.host = host
        self.port = port
        self.use_ssl = ssl
        self.user = user
        self.password = password
        self.folders = folders
        self.poll_interval = poll_interval
        self.backfill_days = backfill_days
        self.correlator = correlator
        self.maintenance_engine = maintenance_engine
        self.parser = EmailParser()
        self.running = False
        self._connection: Optional[imaplib.IMAP4_SSL] = None

    def _connect(self) -> imaplib.IMAP4_SSL:
        """Create IMAP connection."""
        logger.info("Connecting to IMAP server", host=self.host, port=self.port)

        if self.use_ssl:
            context = ssl.create_default_context()
            conn = imaplib.IMAP4_SSL(self.host, self.port, ssl_context=context)
        else:
            conn = imaplib.IMAP4(self.host, self.port)

        conn.login(self.user, self.password)
        logger.info("IMAP connection established")
        return conn

    def _disconnect(self):
        """Close IMAP connection."""
        if self._connection:
            try:
                self._connection.logout()
            except Exception:
                pass
            self._connection = None

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
    async def _fetch_new_emails(self, folder: str, last_uid: int) -> List[Dict[str, Any]]:
        """Fetch new emails from a folder since last_uid."""
        emails = []

        try:
            # Run IMAP operations in thread pool (imaplib is sync)
            loop = asyncio.get_event_loop()

            def fetch_sync():
                conn = self._connect()
                try:
                    conn.select(folder)

                    # Search for emails with UID > last_uid
                    if last_uid > 0:
                        search_criteria = f"UID {last_uid + 1}:*"
                    else:
                        # Initial backfill - get emails from last N days
                        since_date = (datetime.now() - timedelta(days=self.backfill_days)).strftime("%d-%b-%Y")
                        search_criteria = f'SINCE "{since_date}"'

                    typ, data = conn.uid("SEARCH", None, search_criteria)

                    if typ != "OK":
                        return []

                    uid_list = data[0].split()
                    if not uid_list:
                        return []

                    result = []
                    for uid_bytes in uid_list:
                        uid = int(uid_bytes)
                        if uid <= last_uid:
                            continue

                        typ, msg_data = conn.uid("FETCH", str(uid), "(RFC822)")
                        if typ == "OK" and msg_data[0]:
                            raw_email = msg_data[0][1]
                            result.append({
                                "uid": uid,
                                "raw": raw_email,
                                "folder": folder
                            })

                    return result
                finally:
                    conn.logout()

            emails = await loop.run_in_executor(None, fetch_sync)
            logger.info("Fetched emails", folder=folder, count=len(emails))

        except Exception as e:
            logger.error("Failed to fetch emails", folder=folder, error=str(e))
            raise

        return emails

    async def _store_raw_email(self, folder: str, uid: int, raw_email: bytes) -> Optional[str]:
        """Store raw email in database."""
        pool = await get_pool()

        try:
            # Parse email headers
            msg = email.message_from_bytes(raw_email)

            message_id = msg.get("Message-ID", "")
            subject = self._decode_header(msg.get("Subject", ""))
            from_addr = self._decode_header(msg.get("From", ""))
            to_addrs = [self._decode_header(a) for a in msg.get_all("To", [])]
            cc_addrs = [self._decode_header(a) for a in msg.get_all("Cc", [])]

            date_str = msg.get("Date")
            date_header = None
            if date_str:
                try:
                    date_header = parsedate_to_datetime(date_str)
                except Exception:
                    pass

            # Extract headers as dict
            headers = {k: self._decode_header(v) for k, v in msg.items()}

            # Extract body
            body_text, body_html, ics_content, attachments = self._extract_body(msg)

            async with pool.acquire() as conn:
                result = await conn.fetchrow(
                    """
                    INSERT INTO raw_emails (
                        folder, uid, message_id, subject, from_address, to_addresses,
                        cc_addresses, date_header, headers, body_text, body_html,
                        raw_mime, ics_content, attachments, parse_status
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, 'pending')
                    ON CONFLICT (folder, uid) DO NOTHING
                    RETURNING id
                    """,
                    folder, uid, message_id, subject, from_addr, to_addrs,
                    cc_addrs, date_header, headers, body_text, body_html,
                    raw_email, ics_content, attachments
                )

                if result:
                    return str(result["id"])
                return None

        except Exception as e:
            logger.error("Failed to store email", folder=folder, uid=uid, error=str(e))
            return None

    def _decode_header(self, value: str) -> str:
        """Decode email header value."""
        if not value:
            return ""

        try:
            decoded_parts = decode_header(value)
            result = []
            for part, encoding in decoded_parts:
                if isinstance(part, bytes):
                    result.append(part.decode(encoding or "utf-8", errors="replace"))
                else:
                    result.append(part)
            return " ".join(result)
        except Exception:
            return str(value)

    def _extract_body(self, msg: email.message.Message) -> tuple:
        """Extract body text, HTML, ICS content, and attachments."""
        body_text = ""
        body_html = ""
        ics_content = ""
        attachments = []

        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition", ""))

                if "attachment" in content_disposition:
                    filename = part.get_filename()
                    attachments.append({
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(part.get_payload(decode=True) or b"")
                    })

                    if content_type == "text/calendar" or (filename and filename.endswith(".ics")):
                        try:
                            ics_content = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        except Exception:
                            pass
                elif content_type == "text/plain":
                    try:
                        body_text = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    except Exception:
                        pass
                elif content_type == "text/html":
                    try:
                        body_html = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    except Exception:
                        pass
                elif content_type == "text/calendar":
                    try:
                        ics_content = part.get_payload(decode=True).decode("utf-8", errors="replace")
                    except Exception:
                        pass
        else:
            content_type = msg.get_content_type()
            try:
                payload = msg.get_payload(decode=True)
                if payload:
                    decoded = payload.decode("utf-8", errors="replace")
                    if content_type == "text/html":
                        body_html = decoded
                    else:
                        body_text = decoded
            except Exception:
                pass

        return body_text, body_html, ics_content, attachments

    async def _update_cursor(self, folder: str, uid: int):
        """Update folder cursor to new UID."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO folder_cursors (folder, last_uid, last_poll_at, last_success_at, emails_processed)
                VALUES ($1, $2, NOW(), NOW(), 1)
                ON CONFLICT (folder) DO UPDATE SET
                    last_uid = GREATEST(folder_cursors.last_uid, $2),
                    last_poll_at = NOW(),
                    last_success_at = NOW(),
                    emails_processed = folder_cursors.emails_processed + 1,
                    error_count = 0,
                    updated_at = NOW()
                """,
                folder, uid
            )

    async def _record_poll_error(self, folder: str, error: str):
        """Record polling error for a folder."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO folder_cursors (folder, last_uid, last_poll_at, last_error, error_count)
                VALUES ($1, 0, NOW(), $2, 1)
                ON CONFLICT (folder) DO UPDATE SET
                    last_poll_at = NOW(),
                    last_error = $2,
                    error_count = folder_cursors.error_count + 1,
                    updated_at = NOW()
                """,
                folder, error
            )

    async def _get_cursor(self, folder: str) -> int:
        """Get last processed UID for folder."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT last_uid FROM folder_cursors WHERE folder = $1",
                folder
            )
            return result or 0

    async def _process_folder(self, folder: str):
        """Process a single IMAP folder."""
        logger.info("Processing folder", folder=folder)

        try:
            last_uid = await self._get_cursor(folder)
            emails = await self._fetch_new_emails(folder, last_uid)

            for email_data in emails:
                uid = email_data["uid"]
                raw = email_data["raw"]

                # Store raw email
                email_id = await self._store_raw_email(folder, uid, raw)

                if email_id:
                    # Check if this is a maintenance folder or looks like a maintenance email
                    is_maintenance = folder.upper() == "MAINTENANCE"

                    # Parse and process
                    try:
                        if is_maintenance:
                            await self.maintenance_engine.process_email(email_id)
                        else:
                            parsed = await self.parser.parse_email(email_id, folder)
                            if parsed:
                                await self.correlator.process_event(parsed)
                    except Exception as e:
                        logger.error("Failed to process email", email_id=email_id, error=str(e))

                    # Update cursor
                    await self._update_cursor(folder, uid)

            logger.info("Folder processed", folder=folder, emails=len(emails))

        except Exception as e:
            logger.error("Failed to process folder", folder=folder, error=str(e))
            await self._record_poll_error(folder, str(e))

    async def run(self):
        """Run the IMAP poller."""
        self.running = True
        logger.info("IMAP poller started", folders=self.folders, interval=self.poll_interval)

        while self.running:
            for folder in self.folders:
                if not self.running:
                    break
                await self._process_folder(folder)

            if self.running:
                await asyncio.sleep(self.poll_interval)

        logger.info("IMAP poller stopped")

    async def stop(self):
        """Stop the IMAP poller."""
        self.running = False
        self._disconnect()

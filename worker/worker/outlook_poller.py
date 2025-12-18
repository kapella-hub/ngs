"""Outlook COM automation poller for Windows local testing.

Reads emails directly from Outlook desktop application.
Requires: Windows + Outlook installed + pywin32
"""
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from uuid import uuid4

import structlog

logger = structlog.get_logger()

# Import win32com - will raise ImportError on non-Windows
try:
    import win32com.client
    import pythoncom
    HAS_WIN32COM = True
except ImportError:
    HAS_WIN32COM = False
    raise ImportError("pywin32 not installed. Install with: pip install pywin32")

from worker.database import get_pool
from worker.parser import EmailParser


class OutlookPoller:
    """
    Polls Outlook desktop application via COM automation.

    Usage:
    1. Set EMAIL_PROVIDER=outlook in .env
    2. Make sure Outlook is running on your Windows machine
    3. NGS will read from your Outlook folders directly

    Note: First run may prompt for Outlook security confirmation.
    """

    def __init__(
        self,
        folders: List[str],
        poll_interval: int,
        backfill_days: int,
        correlator,
        maintenance_engine,
    ):
        self.folders = folders
        self.poll_interval = poll_interval
        self.backfill_days = backfill_days
        self.correlator = correlator
        self.maintenance_engine = maintenance_engine
        self.parser = EmailParser()
        self.running = False
        self._processed_ids: set = set()  # Track processed EntryIDs

    def _get_outlook(self):
        """Get Outlook application instance."""
        pythoncom.CoInitialize()
        try:
            outlook = win32com.client.Dispatch("Outlook.Application")
            return outlook.GetNamespace("MAPI")
        except Exception as e:
            logger.error("Failed to connect to Outlook", error=str(e))
            raise

    def _find_folder(self, namespace, folder_name: str):
        """Find an Outlook folder by name."""
        # Common folder constants
        folder_map = {
            "inbox": 6,      # olFolderInbox
            "sent": 5,       # olFolderSentMail
            "drafts": 16,    # olFolderDrafts
            "deleted": 3,    # olFolderDeletedItems
            "junk": 23,      # olFolderJunk
        }

        folder_lower = folder_name.lower()

        # Try default folder first
        if folder_lower in folder_map:
            try:
                return namespace.GetDefaultFolder(folder_map[folder_lower])
            except:
                pass

        # Search in default folders
        try:
            inbox = namespace.GetDefaultFolder(6)  # Inbox
            parent = inbox.Parent  # Root folder

            # Search subfolders
            for folder in parent.Folders:
                if folder.Name.lower() == folder_lower:
                    return folder

            # Also check Inbox subfolders
            for folder in inbox.Folders:
                if folder.Name.lower() == folder_lower:
                    return folder

        except Exception as e:
            logger.warning("Error searching folders", error=str(e))

        return None

    def _extract_email_data(self, mail_item) -> dict:
        """Extract data from Outlook MailItem."""
        try:
            # Get basic properties
            subject = mail_item.Subject or ""
            sender = ""
            try:
                sender = mail_item.SenderEmailAddress or mail_item.SenderName or ""
            except:
                pass

            to_recipients = []
            cc_recipients = []
            try:
                to_recipients = [r.Address for r in mail_item.Recipients if r.Type == 1]
                cc_recipients = [r.Address for r in mail_item.Recipients if r.Type == 2]
            except:
                pass

            received_time = None
            try:
                received_time = mail_item.ReceivedTime
                if hasattr(received_time, 'replace'):
                    # Convert COM date to Python datetime
                    received_time = datetime(
                        received_time.year, received_time.month, received_time.day,
                        received_time.hour, received_time.minute, received_time.second
                    )
            except:
                pass

            body_text = ""
            body_html = ""
            try:
                body_text = mail_item.Body or ""
                body_html = mail_item.HTMLBody or ""
            except:
                pass

            # Get attachments info
            attachments = []
            try:
                for att in mail_item.Attachments:
                    attachments.append({
                        "filename": att.FileName,
                        "size": att.Size,
                    })
            except:
                pass

            # Get headers if available
            headers = {}
            try:
                # PR_TRANSPORT_MESSAGE_HEADERS
                headers_prop = mail_item.PropertyAccessor.GetProperty(
                    "http://schemas.microsoft.com/mapi/proptag/0x007D001F"
                )
                if headers_prop:
                    for line in headers_prop.split('\n'):
                        if ':' in line:
                            key, value = line.split(':', 1)
                            headers[key.strip()] = value.strip()
            except:
                pass

            message_id = headers.get("Message-ID", f"<{uuid4()}@outlook.local>")

            return {
                "entry_id": mail_item.EntryID,
                "subject": subject,
                "from_address": sender,
                "to_addresses": to_recipients,
                "cc_addresses": cc_recipients,
                "date_header": received_time,
                "body_text": body_text,
                "body_html": body_html,
                "headers": headers,
                "attachments": attachments,
                "message_id": message_id,
            }

        except Exception as e:
            logger.error("Failed to extract email data", error=str(e))
            return None

    async def _store_email(self, data: dict, folder: str) -> Optional[str]:
        """Store email data in database."""
        pool = await get_pool()

        # Use EntryID hash as UID
        uid = abs(hash(data.get("entry_id", ""))) % (2**31)

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

    async def _process_folder(self, folder_name: str):
        """Process emails from an Outlook folder."""
        logger.info("Processing Outlook folder", folder=folder_name)

        try:
            # Run COM operations in thread pool
            loop = asyncio.get_event_loop()

            def get_emails():
                namespace = self._get_outlook()
                folder = self._find_folder(namespace, folder_name)

                if not folder:
                    logger.warning("Folder not found", folder=folder_name)
                    return []

                # Get items from last N days
                cutoff = datetime.now() - timedelta(days=self.backfill_days)

                emails = []
                items = folder.Items
                items.Sort("[ReceivedTime]", True)  # Descending

                for item in items:
                    try:
                        # Check if it's a mail item
                        if item.Class != 43:  # olMail
                            continue

                        # Check date
                        received = item.ReceivedTime
                        if hasattr(received, 'year'):
                            item_date = datetime(received.year, received.month, received.day)
                            if item_date < cutoff:
                                break  # Items are sorted, so we can stop

                        # Skip already processed
                        if item.EntryID in self._processed_ids:
                            continue

                        data = self._extract_email_data(item)
                        if data:
                            emails.append(data)
                            self._processed_ids.add(item.EntryID)

                    except Exception as e:
                        logger.debug("Skipping item", error=str(e))
                        continue

                    # Limit to 50 per poll
                    if len(emails) >= 50:
                        break

                return emails

            emails = await loop.run_in_executor(None, get_emails)

            logger.info("Found emails", folder=folder_name, count=len(emails))

            for data in emails:
                email_id = await self._store_email(data, folder_name)

                if email_id:
                    is_maintenance = "maintenance" in folder_name.lower()

                    try:
                        if is_maintenance:
                            await self.maintenance_engine.process_email(email_id)
                        else:
                            parsed = await self.parser.parse_email(email_id, folder_name)
                            if parsed:
                                await self.correlator.process_event(parsed)
                    except Exception as e:
                        logger.error("Failed to process email", email_id=email_id, error=str(e))

            logger.info("Folder processed", folder=folder_name)

        except Exception as e:
            logger.error("Failed to process folder", folder=folder_name, error=str(e))

    async def run(self):
        """Run the Outlook poller."""
        self.running = True
        logger.info("Outlook poller started", folders=self.folders)
        logger.info("Make sure Outlook is running on this machine")

        while self.running:
            for folder in self.folders:
                if not self.running:
                    break
                await self._process_folder(folder)

            if self.running:
                await asyncio.sleep(self.poll_interval)

        logger.info("Outlook poller stopped")

    async def stop(self):
        """Stop the poller."""
        self.running = False
        pythoncom.CoUninitialize()

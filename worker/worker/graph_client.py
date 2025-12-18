"""Microsoft Graph API client for Office 365 email access."""
import asyncio
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from uuid import UUID

import httpx
import structlog

from worker.config import get_settings
from worker.database import get_pool

logger = structlog.get_logger()


class GraphClient:
    """
    Microsoft Graph API client for reading emails from Office 365.

    Supports OAuth 2.0 with client credentials flow (app-only) or
    delegated flow (on behalf of user).

    Required Azure AD App Registration:
    1. Go to Azure Portal > Azure Active Directory > App registrations
    2. Create new registration
    3. Add API permissions: Microsoft Graph > Application permissions:
       - Mail.Read (to read all mailboxes) OR
       - Mail.ReadBasic.All (for metadata only)
    4. Grant admin consent
    5. Create a client secret
    6. Note: Tenant ID, Client ID, Client Secret

    For delegated access (user mailbox only):
    - Use Mail.Read delegated permission
    - Requires user sign-in flow
    """

    GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"
    AUTH_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        user_email: Optional[str] = None,
    ):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.user_email = user_email  # For app-only access to specific mailbox
        self._access_token: Optional[str] = None
        self._token_expires: Optional[datetime] = None
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30)
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _ensure_token(self):
        """Ensure we have a valid access token."""
        if self._access_token and self._token_expires and datetime.utcnow() < self._token_expires:
            return

        client = await self._get_client()
        auth_url = self.AUTH_URL.format(tenant=self.tenant_id)

        response = await client.post(
            auth_url,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            },
        )

        if response.status_code != 200:
            logger.error("Failed to get access token", status=response.status_code, body=response.text)
            raise Exception(f"Failed to authenticate with Microsoft Graph: {response.text}")

        data = response.json()
        self._access_token = data["access_token"]
        # Token typically expires in 1 hour, refresh 5 minutes early
        self._token_expires = datetime.utcnow() + timedelta(seconds=data["expires_in"] - 300)

        logger.info("Obtained Microsoft Graph access token")

    async def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make authenticated request to Graph API."""
        await self._ensure_token()
        client = await self._get_client()

        url = f"{self.GRAPH_BASE_URL}{endpoint}"
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

        response = await client.request(method, url, headers=headers, **kwargs)

        if response.status_code == 401:
            # Token expired, refresh and retry
            self._access_token = None
            await self._ensure_token()
            headers["Authorization"] = f"Bearer {self._access_token}"
            response = await client.request(method, url, headers=headers, **kwargs)

        if response.status_code >= 400:
            logger.error("Graph API error", status=response.status_code, body=response.text[:500])
            raise Exception(f"Graph API error: {response.status_code} - {response.text[:500]}")

        return response.json() if response.text else {}

    async def list_mail_folders(self) -> List[Dict[str, Any]]:
        """List all mail folders in the mailbox."""
        endpoint = f"/users/{self.user_email}/mailFolders"
        data = await self._request("GET", endpoint)
        return data.get("value", [])

    async def get_folder_by_name(self, folder_name: str) -> Optional[Dict[str, Any]]:
        """Get a specific folder by display name."""
        folders = await self.list_mail_folders()
        for folder in folders:
            if folder.get("displayName", "").lower() == folder_name.lower():
                return folder
        return None

    async def list_messages(
        self,
        folder_id: str,
        since: Optional[datetime] = None,
        top: int = 50,
        skip: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        List messages in a folder.

        Args:
            folder_id: The folder ID (not display name)
            since: Only get messages received after this time
            top: Maximum messages to return
            skip: Number of messages to skip (for pagination)
        """
        endpoint = f"/users/{self.user_email}/mailFolders/{folder_id}/messages"

        params = {
            "$top": top,
            "$skip": skip,
            "$orderby": "receivedDateTime desc",
            "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,hasAttachments,internetMessageHeaders",
        }

        if since:
            params["$filter"] = f"receivedDateTime ge {since.isoformat()}Z"

        data = await self._request("GET", endpoint, params=params)
        return data.get("value", [])

    async def get_message(self, message_id: str) -> Dict[str, Any]:
        """Get full message details including body."""
        endpoint = f"/users/{self.user_email}/messages/{message_id}"
        params = {
            "$select": "id,subject,from,toRecipients,ccRecipients,receivedDateTime,body,bodyPreview,hasAttachments,internetMessageHeaders,internetMessageId",
        }
        return await self._request("GET", endpoint, params=params)

    async def get_message_attachments(self, message_id: str) -> List[Dict[str, Any]]:
        """Get attachments for a message."""
        endpoint = f"/users/{self.user_email}/messages/{message_id}/attachments"
        data = await self._request("GET", endpoint)
        return data.get("value", [])

    async def get_message_mime(self, message_id: str) -> bytes:
        """Get raw MIME content of a message."""
        await self._ensure_token()
        client = await self._get_client()

        url = f"{self.GRAPH_BASE_URL}/users/{self.user_email}/messages/{message_id}/$value"
        headers = {"Authorization": f"Bearer {self._access_token}"}

        response = await client.get(url, headers=headers)
        if response.status_code >= 400:
            raise Exception(f"Failed to get MIME content: {response.status_code}")

        return response.content


class GraphEmailPoller:
    """
    Polls Office 365 mailbox via Microsoft Graph API.

    Drop-in replacement for IMAPPoller when using Office 365 with OAuth.
    """

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        user_email: str,
        folders: List[str],
        poll_interval: int,
        backfill_days: int,
        correlator,
        maintenance_engine,
    ):
        self.graph = GraphClient(tenant_id, client_id, client_secret, user_email)
        self.folders = folders
        self.poll_interval = poll_interval
        self.backfill_days = backfill_days
        self.correlator = correlator
        self.maintenance_engine = maintenance_engine
        self.running = False

        # Import parser here to avoid circular imports
        from worker.parser import EmailParser
        self.parser = EmailParser()

        # Cache folder IDs
        self._folder_ids: Dict[str, str] = {}

    async def _resolve_folder_ids(self):
        """Resolve folder display names to IDs."""
        all_folders = await self.graph.list_mail_folders()

        for folder_name in self.folders:
            for folder in all_folders:
                if folder.get("displayName", "").lower() == folder_name.lower():
                    self._folder_ids[folder_name] = folder["id"]
                    break
            else:
                logger.warning("Folder not found", folder=folder_name)

        logger.info("Resolved folder IDs", folders=list(self._folder_ids.keys()))

    async def _get_cursor(self, folder: str) -> Optional[datetime]:
        """Get last processed timestamp for folder."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT last_success_at FROM folder_cursors WHERE folder = $1",
                folder
            )
            return result

    async def _update_cursor(self, folder: str, timestamp: datetime):
        """Update folder cursor with new timestamp."""
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO folder_cursors (folder, last_uid, last_poll_at, last_success_at, emails_processed)
                VALUES ($1, 0, NOW(), $2, 1)
                ON CONFLICT (folder) DO UPDATE SET
                    last_poll_at = NOW(),
                    last_success_at = $2,
                    emails_processed = folder_cursors.emails_processed + 1,
                    error_count = 0,
                    updated_at = NOW()
                """,
                folder, timestamp
            )

    async def _store_message(self, folder: str, message: Dict[str, Any]) -> Optional[str]:
        """Store a Graph message as raw_email."""
        pool = await get_pool()

        message_id = message.get("internetMessageId", message.get("id", ""))
        subject = message.get("subject", "")
        from_data = message.get("from", {}).get("emailAddress", {})
        from_address = f"{from_data.get('name', '')} <{from_data.get('address', '')}>"

        to_addresses = [
            r.get("emailAddress", {}).get("address", "")
            for r in message.get("toRecipients", [])
        ]
        cc_addresses = [
            r.get("emailAddress", {}).get("address", "")
            for r in message.get("ccRecipients", [])
        ]

        received_at = None
        if message.get("receivedDateTime"):
            received_at = datetime.fromisoformat(message["receivedDateTime"].replace("Z", "+00:00"))

        body = message.get("body", {})
        body_text = body.get("content", "") if body.get("contentType") == "text" else ""
        body_html = body.get("content", "") if body.get("contentType") == "html" else ""

        # Extract headers
        headers = {}
        for header in message.get("internetMessageHeaders", []):
            headers[header.get("name", "")] = header.get("value", "")

        async with pool.acquire() as conn:
            # Use message ID as UID (Graph messages have unique IDs)
            # We'll use a hash of the ID as a numeric UID
            uid = abs(hash(message.get("id", ""))) % (2**31)

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
                folder, uid, message_id, subject, from_address, to_addresses,
                cc_addresses, received_at, headers, body_text, body_html,
                []  # Attachments handled separately if needed
            )

            if result:
                return str(result["id"])
            return None

    async def _process_folder(self, folder: str):
        """Process messages from a single folder."""
        folder_id = self._folder_ids.get(folder)
        if not folder_id:
            logger.warning("Folder not mapped", folder=folder)
            return

        logger.info("Processing folder", folder=folder)

        try:
            # Get cursor (last processed time)
            last_processed = await self._get_cursor(folder)
            if not last_processed:
                # Initial backfill
                last_processed = datetime.utcnow() - timedelta(days=self.backfill_days)

            # Fetch new messages
            messages = await self.graph.list_messages(
                folder_id,
                since=last_processed,
                top=100
            )

            logger.info("Fetched messages", folder=folder, count=len(messages))

            latest_time = last_processed
            for message in messages:
                received = message.get("receivedDateTime")
                if received:
                    msg_time = datetime.fromisoformat(received.replace("Z", "+00:00"))
                    if msg_time > latest_time:
                        latest_time = msg_time

                # Get full message with body
                full_message = await self.graph.get_message(message["id"])

                # Store raw email
                email_id = await self._store_message(folder, full_message)

                if email_id:
                    is_maintenance = folder.upper() == "MAINTENANCE"

                    try:
                        if is_maintenance:
                            await self.maintenance_engine.process_email(email_id)
                        else:
                            parsed = await self.parser.parse_email(email_id, folder)
                            if parsed:
                                await self.correlator.process_event(parsed)
                    except Exception as e:
                        logger.error("Failed to process message", email_id=email_id, error=str(e))

            # Update cursor
            await self._update_cursor(folder, latest_time)
            logger.info("Folder processed", folder=folder, messages=len(messages))

        except Exception as e:
            logger.error("Failed to process folder", folder=folder, error=str(e))

    async def run(self):
        """Run the Graph email poller."""
        self.running = True
        logger.info("Graph email poller starting", folders=self.folders)

        # Resolve folder IDs
        await self._resolve_folder_ids()

        while self.running:
            for folder in self.folders:
                if not self.running:
                    break
                await self._process_folder(folder)

            if self.running:
                await asyncio.sleep(self.poll_interval)

        logger.info("Graph email poller stopped")

    async def stop(self):
        """Stop the poller."""
        self.running = False
        await self.graph.close()

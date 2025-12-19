"""Configuration versioning with hash-based versioning and rollback support.

Supports versioning of:
- Parser configurations
- Redaction patterns
- Notification settings
- Other runtime configurations
"""
import hashlib
import json
from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog
import yaml

from worker.database import get_pool

logger = structlog.get_logger()


class ConfigVersioning:
    """Manages versioned configurations with rollback support."""

    @staticmethod
    def compute_hash(config_data: Dict[str, Any]) -> str:
        """
        Compute a stable hash for configuration data.

        Args:
            config_data: Configuration dictionary

        Returns:
            64-character hex hash
        """
        # Sort keys for stable serialization
        serialized = yaml.dump(config_data, sort_keys=True, default_flow_style=False)
        return hashlib.sha256(serialized.encode()).hexdigest()

    async def save_config(
        self,
        config_type: str,
        config_data: Dict[str, Any],
        created_by: str,
        notes: Optional[str] = None,
        activate: bool = True
    ) -> int:
        """
        Save a new configuration version.

        Args:
            config_type: Type of config ('parsers', 'redaction', etc.)
            config_data: Configuration data
            created_by: Who created this version
            notes: Optional notes about this version
            activate: Whether to activate this version immediately

        Returns:
            Version ID
        """
        config_hash = self.compute_hash(config_data)
        pool = await get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Check if this exact config already exists
                existing = await conn.fetchrow("""
                    SELECT id FROM config_versions
                    WHERE config_type = $1 AND config_hash = $2
                """, config_type, config_hash)

                if existing:
                    logger.info(
                        "Config version already exists",
                        config_type=config_type,
                        version_id=existing["id"]
                    )
                    if activate:
                        await self.activate_version(config_type, existing["id"])
                    return existing["id"]

                # Deactivate current active version if activating new one
                if activate:
                    await conn.execute("""
                        UPDATE config_versions
                        SET is_active = FALSE, deactivated_at = NOW()
                        WHERE config_type = $1 AND is_active = TRUE
                    """, config_type)

                # Insert new version
                version_id = await conn.fetchval("""
                    INSERT INTO config_versions
                    (config_type, config_hash, config_data, created_by, notes, is_active, activated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    RETURNING id
                """, config_type, config_hash, json.dumps(config_data),
                    created_by, notes, activate,
                    datetime.utcnow() if activate else None)

                logger.info(
                    "Saved config version",
                    config_type=config_type,
                    version_id=version_id,
                    hash=config_hash[:16],
                    activated=activate
                )

                return version_id

    async def activate_version(self, config_type: str, version_id: int) -> bool:
        """
        Activate a specific config version.

        Args:
            config_type: Type of config
            version_id: Version to activate

        Returns:
            True if activated successfully
        """
        pool = await get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                # Verify version exists and is correct type
                version = await conn.fetchrow("""
                    SELECT id, config_type FROM config_versions WHERE id = $1
                """, version_id)

                if not version:
                    logger.error("Config version not found", version_id=version_id)
                    return False

                if version["config_type"] != config_type:
                    logger.error(
                        "Config type mismatch",
                        expected=config_type,
                        actual=version["config_type"]
                    )
                    return False

                # Deactivate all versions of this type
                await conn.execute("""
                    UPDATE config_versions
                    SET is_active = FALSE, deactivated_at = NOW()
                    WHERE config_type = $1 AND is_active = TRUE
                """, config_type)

                # Activate the specified version
                result = await conn.execute("""
                    UPDATE config_versions
                    SET is_active = TRUE, activated_at = NOW()
                    WHERE id = $1
                """, version_id)

                success = result == "UPDATE 1"
                if success:
                    logger.info(
                        "Activated config version",
                        config_type=config_type,
                        version_id=version_id
                    )

                return success

    async def rollback(self, config_type: str, version_id: int) -> bool:
        """
        Rollback to a previous config version.

        Args:
            config_type: Type of config
            version_id: Version to rollback to

        Returns:
            True if rollback successful
        """
        return await self.activate_version(config_type, version_id)

    async def get_active_config(self, config_type: str) -> Optional[Dict[str, Any]]:
        """
        Get the currently active configuration.

        Args:
            config_type: Type of config

        Returns:
            Active configuration data, or None if not found
        """
        pool = await get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT config_data FROM config_versions
                WHERE config_type = $1 AND is_active = TRUE
            """, config_type)

            if row:
                data = row["config_data"]
                return json.loads(data) if isinstance(data, str) else data

            return None

    async def get_version_history(
        self,
        config_type: str,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """
        Get version history for a config type.

        Args:
            config_type: Type of config
            limit: Maximum versions to return

        Returns:
            List of version records
        """
        pool = await get_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT id, config_hash, created_at, created_by, notes, is_active, activated_at
                FROM config_versions
                WHERE config_type = $1
                ORDER BY created_at DESC
                LIMIT $2
            """, config_type, limit)

            return [
                {
                    "id": row["id"],
                    "hash": row["config_hash"][:16],
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "created_by": row["created_by"],
                    "notes": row["notes"],
                    "is_active": row["is_active"],
                    "activated_at": row["activated_at"].isoformat() if row["activated_at"] else None
                }
                for row in rows
            ]

    async def get_version(self, version_id: int) -> Optional[Dict[str, Any]]:
        """
        Get a specific config version.

        Args:
            version_id: Version ID

        Returns:
            Version record with full config data
        """
        pool = await get_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM config_versions WHERE id = $1
            """, version_id)

            if row:
                data = row["config_data"]
                return {
                    "id": row["id"],
                    "config_type": row["config_type"],
                    "hash": row["config_hash"],
                    "data": json.loads(data) if isinstance(data, str) else data,
                    "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                    "created_by": row["created_by"],
                    "notes": row["notes"],
                    "is_active": row["is_active"]
                }

            return None

    async def compare_versions(
        self,
        version_id_1: int,
        version_id_2: int
    ) -> Dict[str, Any]:
        """
        Compare two config versions.

        Args:
            version_id_1: First version
            version_id_2: Second version

        Returns:
            Comparison result with differences
        """
        v1 = await self.get_version(version_id_1)
        v2 = await self.get_version(version_id_2)

        if not v1 or not v2:
            return {"error": "One or both versions not found"}

        if v1["config_type"] != v2["config_type"]:
            return {"error": "Cannot compare different config types"}

        # Simple key-level diff
        d1 = v1["data"]
        d2 = v2["data"]

        added = {k: v for k, v in d2.items() if k not in d1}
        removed = {k: v for k, v in d1.items() if k not in d2}
        modified = {
            k: {"old": d1[k], "new": d2[k]}
            for k in d1.keys() & d2.keys()
            if d1[k] != d2[k]
        }

        return {
            "version_1": {"id": version_id_1, "hash": v1["hash"][:16]},
            "version_2": {"id": version_id_2, "hash": v2["hash"][:16]},
            "added": added,
            "removed": removed,
            "modified": modified
        }


# Global instance
_config_versioning: Optional[ConfigVersioning] = None


def get_config_versioning() -> ConfigVersioning:
    """Get the global ConfigVersioning instance."""
    global _config_versioning
    if _config_versioning is None:
        _config_versioning = ConfigVersioning()
    return _config_versioning


async def get_active_parsers_config() -> Optional[Dict[str, Any]]:
    """Get active parsers configuration."""
    cv = get_config_versioning()
    return await cv.get_active_config("parsers")


async def get_active_redaction_config() -> Optional[Dict[str, Any]]:
    """Get active redaction configuration."""
    cv = get_config_versioning()
    return await cv.get_active_config("redaction")

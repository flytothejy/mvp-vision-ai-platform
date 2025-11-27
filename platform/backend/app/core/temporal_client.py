"""Temporal Client for workflow orchestration.

Phase 12: Temporal Orchestration & Backend Modernization
"""

import logging
from typing import Optional
from temporalio.client import Client
from app.core.config import settings

logger = logging.getLogger(__name__)

# Global Temporal client instance (singleton)
_client: Optional[Client] = None


async def get_temporal_client() -> Client:
    """
    Get or create Temporal client (singleton pattern).

    Returns:
        Client: Temporal client instance

    Example:
        >>> client = await get_temporal_client()
        >>> workflow_handle = await client.start_workflow(...)
    """
    global _client

    if _client is None:
        logger.info(f"Connecting to Temporal at {settings.TEMPORAL_HOST}")
        _client = await Client.connect(
            settings.TEMPORAL_HOST,
            namespace=settings.TEMPORAL_NAMESPACE
        )
        logger.info(f"Connected to Temporal namespace: {settings.TEMPORAL_NAMESPACE}")

    return _client


async def close_temporal_client() -> None:
    """
    Close Temporal client connection.

    Should be called during application shutdown.

    Example:
        >>> await close_temporal_client()
    """
    global _client

    if _client:
        logger.info("Closing Temporal client connection")
        await _client.close()
        _client = None
        logger.info("Temporal client closed")

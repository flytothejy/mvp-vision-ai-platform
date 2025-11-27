"""
Labeler API Client

Client for communicating with Labeler Backend, which is the Single Source of Truth
for dataset metadata and annotation management.

Phase 11.5: Dataset Service Integration
"""

from typing import List, Optional, Dict, Any
import httpx
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


class LabelerClient:
    """
    Client for Labeler Backend API.

    Labeler Backend manages:
    - Dataset metadata (name, format, classes, etc.)
    - Dataset annotations
    - Dataset permissions
    - Dataset storage information (R2 paths)

    Platform uses this client to:
    - Query dataset information
    - Check user permissions
    - Generate download URLs
    - Batch retrieve dataset metadata
    """

    def __init__(self):
        self.base_url = settings.LABELER_API_URL
        self.headers = {
            "Authorization": f"Bearer {settings.LABELER_SERVICE_KEY}",
            "Content-Type": "application/json",
        }
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=30.0,
            follow_redirects=True,
        )
        logger.info(f"[LabelerClient] Initialized with base_url: {self.base_url}")

    async def get_dataset(self, dataset_id: str) -> Dict[str, Any]:
        """
        Get single dataset metadata.

        Args:
            dataset_id: Dataset ID (UUID)

        Returns:
            Dataset metadata dict with keys:
            - id, name, description, format, labeled, storage_type, storage_path,
              annotation_path, num_classes, num_images, class_names, tags,
              visibility, owner_id, created_at, updated_at, version, content_hash

        Raises:
            httpx.HTTPStatusError: If dataset not found (404) or access denied (403)
            httpx.HTTPError: For other HTTP errors
        """
        try:
            response = await self.client.get(f"/api/v1/datasets/{dataset_id}")
            response.raise_for_status()
            dataset = response.json()
            logger.info(f"[LabelerClient] get_dataset({dataset_id}): {dataset['name']}")
            return dataset
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.error(f"[LabelerClient] Dataset not found: {dataset_id}")
            elif e.response.status_code == 403:
                logger.error(f"[LabelerClient] Access denied to dataset: {dataset_id}")
            raise
        except httpx.HTTPError as e:
            logger.error(f"[LabelerClient] HTTP error getting dataset {dataset_id}: {e}")
            raise

    async def list_datasets(
        self,
        user_id: Optional[int] = None,
        visibility: Optional[str] = None,
        labeled: Optional[bool] = None,
        tags: Optional[List[str]] = None,
        format: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        List datasets with filters.

        Args:
            user_id: Filter by owner user ID
            visibility: Filter by visibility (public, private, organization)
            labeled: Filter by annotation status
            tags: Filter by tags (AND logic)
            format: Filter by dataset format (coco, yolo, voc, etc.)
            page: Page number (1-indexed)
            limit: Results per page

        Returns:
            Dict with keys:
            - datasets: List of dataset metadata dicts
            - total: Total number of datasets
            - page: Current page
            - limit: Results per page
        """
        params = {"page": page, "limit": limit}
        if user_id:
            params["user_id"] = user_id
        if visibility:
            params["visibility"] = visibility
        if labeled is not None:
            params["labeled"] = labeled
        if tags:
            params["tags"] = ",".join(tags)
        if format:
            params["format"] = format

        try:
            response = await self.client.get("/api/v1/datasets", params=params)
            response.raise_for_status()
            result = response.json()
            logger.info(
                f"[LabelerClient] list_datasets(user_id={user_id}, filters={visibility}): "
                f"{result.get('total', 0)} total, returned {len(result.get('datasets', []))}"
            )
            return result
        except httpx.HTTPError as e:
            logger.error(f"[LabelerClient] HTTP error listing datasets: {e}")
            raise

    async def check_permission(
        self,
        dataset_id: str,
        user_id: int
    ) -> bool:
        """
        Check if user has access to dataset.

        Args:
            dataset_id: Dataset ID (UUID)
            user_id: User ID

        Returns:
            True if user has access, False otherwise
        """
        try:
            response = await self.client.get(
                f"/api/v1/datasets/{dataset_id}/permissions/{user_id}"
            )
            if response.status_code == 404:
                logger.warning(
                    f"[LabelerClient] Permission check: dataset {dataset_id} not found"
                )
                return False

            response.raise_for_status()
            result = response.json()
            has_access = result.get("has_access", False)

            logger.info(
                f"[LabelerClient] check_permission(dataset={dataset_id}, user={user_id}): "
                f"{has_access} ({result.get('permission_level', 'none')})"
            )
            return has_access

        except httpx.HTTPError as e:
            logger.error(
                f"[LabelerClient] HTTP error checking permission "
                f"(dataset={dataset_id}, user={user_id}): {e}"
            )
            # On error, deny access by default (fail-closed)
            return False

    async def get_download_url(
        self,
        dataset_id: str,
        user_id: int,
        expires_in: int = 3600
    ) -> str:
        """
        Generate presigned download URL for dataset.

        Args:
            dataset_id: Dataset ID (UUID)
            user_id: User ID requesting download
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            Presigned download URL (R2/S3 compatible)

        Raises:
            httpx.HTTPStatusError: If dataset not found or access denied
        """
        payload = {
            "expires_in": expires_in,
            "user_id": user_id
        }

        try:
            response = await self.client.post(
                f"/api/v1/datasets/{dataset_id}/download-url",
                json=payload
            )
            response.raise_for_status()
            result = response.json()
            download_url = result.get("download_url")

            logger.info(
                f"[LabelerClient] get_download_url(dataset={dataset_id}, user={user_id}): "
                f"URL generated (expires in {expires_in}s)"
            )
            return download_url

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                logger.error(f"[LabelerClient] Dataset not found for download URL: {dataset_id}")
            elif e.response.status_code == 403:
                logger.error(f"[LabelerClient] Access denied for download URL: {dataset_id}")
            raise
        except httpx.HTTPError as e:
            logger.error(
                f"[LabelerClient] HTTP error getting download URL "
                f"(dataset={dataset_id}): {e}"
            )
            raise

    async def batch_get_datasets(
        self,
        dataset_ids: List[str]
    ) -> Dict[str, Any]:
        """
        Batch retrieve dataset metadata.

        Args:
            dataset_ids: List of dataset IDs (up to 50)

        Returns:
            Dict with keys:
            - datasets: List of dataset metadata dicts
            - not_found: List of dataset IDs that were not found
        """
        if len(dataset_ids) > 50:
            logger.warning(
                f"[LabelerClient] batch_get_datasets: requested {len(dataset_ids)} datasets, "
                "limiting to first 50"
            )
            dataset_ids = dataset_ids[:50]

        payload = {"dataset_ids": dataset_ids}

        try:
            response = await self.client.post(
                "/api/v1/datasets/batch",
                json=payload
            )
            response.raise_for_status()
            result = response.json()

            found = len(result.get("datasets", []))
            not_found = len(result.get("not_found", []))
            logger.info(
                f"[LabelerClient] batch_get_datasets({len(dataset_ids)} IDs): "
                f"{found} found, {not_found} not found"
            )
            return result

        except httpx.HTTPError as e:
            logger.error(f"[LabelerClient] HTTP error in batch_get_datasets: {e}")
            raise

    async def close(self):
        """Close HTTP client connection."""
        await self.client.aclose()
        logger.info("[LabelerClient] Client connection closed")

    async def health_check(self) -> bool:
        """
        Check if Labeler API is reachable.

        Returns:
            True if Labeler API responds, False otherwise
        """
        try:
            response = await self.client.get("/health")
            return response.status_code == 200
        except Exception as e:
            logger.error(f"[LabelerClient] Health check failed: {e}")
            return False


# Singleton instance
labeler_client = LabelerClient()

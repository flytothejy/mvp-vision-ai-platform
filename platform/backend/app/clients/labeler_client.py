"""
Labeler API Client

Client for communicating with Labeler Backend, which is the Single Source of Truth
for dataset metadata and annotation management.

Phase 11.5: Dataset Service Integration
Phase 11.5.6: Hybrid JWT Authentication
"""

from typing import List, Optional, Dict, Any
import httpx
import logging
from app.core.config import settings
from app.core.service_jwt import ServiceJWT

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

    Authentication (Phase 11.5.6):
    Uses Hybrid JWT approach - generates short-lived service tokens (5min)
    that include user context for permission checks and service identity for audit.
    """

    def __init__(self):
        self.base_url = settings.LABELER_API_URL
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=30.0,
            follow_redirects=True,
        )
        logger.info(f"[LabelerClient] Initialized with base_url: {self.base_url}")

    def _get_service_token(self, user_id: Optional[int] = None, scopes: Optional[List[str]] = None) -> str:
        """
        Generate service JWT for Labeler API request.

        Args:
            user_id: User ID for permission checks (None for background jobs)
            scopes: Required scopes (defaults to ["labeler:read"])

        Returns:
            JWT token string
        """
        if scopes is None:
            scopes = ["labeler:read"]

        if user_id is not None:
            # User-initiated request (5min expiry)
            token = ServiceJWT.create_service_token(
                user_id=user_id,
                service_name="platform",
                scopes=scopes,
                expires_minutes=5
            )
        else:
            # Background job (1 hour expiry)
            token = ServiceJWT.create_background_token(
                service_name="platform-training",
                scopes=scopes,
                expires_hours=1
            )

        return token

    def _get_auth_headers(self, user_id: Optional[int] = None, scopes: Optional[List[str]] = None) -> Dict[str, str]:
        """
        Get authorization headers with service JWT.

        Args:
            user_id: User ID for permission checks
            scopes: Required scopes

        Returns:
            Headers dict with Authorization and Content-Type
        """
        token = self._get_service_token(user_id=user_id, scopes=scopes)
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

    async def get_dataset(self, dataset_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
        """
        Get single dataset metadata.

        Args:
            dataset_id: Dataset ID (UUID)
            user_id: User ID for authentication (optional for background jobs)

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
            headers = self._get_auth_headers(user_id=user_id, scopes=["labeler:read"])
            response = await self.client.get(
                f"/api/v1/platform/datasets/{dataset_id}",
                headers=headers
            )
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
        requesting_user_id: Optional[int] = None,
        owner_user_id: Optional[int] = None,
        visibility: Optional[str] = None,
        labeled: Optional[bool] = None,
        task_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        format: Optional[str] = None,
        page: int = 1,
        limit: int = 20
    ) -> Dict[str, Any]:
        """
        List datasets with filters.

        Args:
            requesting_user_id: User making the request (for authentication)
            owner_user_id: Filter by dataset owner user ID
            visibility: Filter by visibility (public, private, organization)
            labeled: Filter by annotation status
            task_type: Filter by task type (detection, segmentation, classification, etc.)
                      Returns task-type-specific statistics (Phase 16.6)
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
        if owner_user_id:
            params["user_id"] = owner_user_id
        if visibility:
            params["visibility"] = visibility
        if labeled is not None:
            params["labeled"] = labeled
        if task_type:
            params["task_type"] = task_type
        if tags:
            params["tags"] = ",".join(tags)
        if format:
            params["format"] = format

        try:
            headers = self._get_auth_headers(user_id=requesting_user_id, scopes=["labeler:read"])

            # DEBUG: Log request details
            logger.info(f"[LabelerClient] Calling Labeler API: GET /api/v1/platform/datasets")
            logger.info(f"[LabelerClient] Request params: {params}")
            logger.info(f"[LabelerClient] Request headers: {list(headers.keys())}")
            logger.info(f"[LabelerClient] Full URL: {self.base_url}/api/v1/platform/datasets")

            response = await self.client.get(
                "/api/v1/platform/datasets",
                params=params,
                headers=headers
            )

            # DEBUG: Log response
            logger.info(f"[LabelerClient] Response status: {response.status_code}")
            logger.info(f"[LabelerClient] Response headers: {dict(response.headers)}")

            response.raise_for_status()
            result = response.json()
            logger.info(
                f"[LabelerClient] list_datasets(owner={owner_user_id}, filters={visibility}): "
                f"{result.get('total', 0)} total, returned {len(result.get('datasets', []))}"
            )
            return result
        except httpx.HTTPError as e:
            logger.error(f"[LabelerClient] HTTP error listing datasets: {e}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"[LabelerClient] Response status: {e.response.status_code}")
                logger.error(f"[LabelerClient] Response body: {e.response.text}")
            raise

    async def check_permission(
        self,
        dataset_id: str,
        user_id: int
    ) -> Dict[str, Any]:
        """
        Check if user has access to dataset.

        Args:
            dataset_id: Dataset ID (UUID)
            user_id: User ID to check permissions for

        Returns:
            Dict with permission info:
            - has_access: bool
            - is_owner: bool
            - permission_level: str (none, read, write, admin, owner)
        """
        try:
            headers = self._get_auth_headers(user_id=user_id, scopes=["labeler:read"])
            response = await self.client.get(
                f"/api/v1/platform/datasets/{dataset_id}/permissions/{user_id}",
                headers=headers
            )
            if response.status_code == 404:
                logger.warning(
                    f"[LabelerClient] Permission check: dataset {dataset_id} not found"
                )
                return {"has_access": False, "is_owner": False, "permission_level": "none"}

            response.raise_for_status()
            result = response.json()
            has_access = result.get("has_access", False)

            logger.info(
                f"[LabelerClient] check_permission(dataset={dataset_id}, user={user_id}): "
                f"{has_access} ({result.get('permission_level', 'none')})"
            )
            return result

        except httpx.HTTPError as e:
            logger.error(
                f"[LabelerClient] HTTP error checking permission "
                f"(dataset={dataset_id}, user={user_id}): {e}"
            )
            # On error, deny access by default (fail-closed)
            return {"has_access": False, "is_owner": False, "permission_level": "none"}

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
            headers = self._get_auth_headers(user_id=user_id, scopes=["labeler:read"])
            response = await self.client.post(
                f"/api/v1/platform/datasets/{dataset_id}/download-url",
                json=payload,
                headers=headers
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
        dataset_ids: List[str],
        user_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Batch retrieve dataset metadata.

        Args:
            dataset_ids: List of dataset IDs (up to 50)
            user_id: User ID for authentication (optional for background jobs)

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
            headers = self._get_auth_headers(user_id=user_id, scopes=["labeler:read"])
            response = await self.client.post(
                "/api/v1/platform/datasets/batch",
                json=payload,
                headers=headers
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

        Note: Health check does not require authentication.

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

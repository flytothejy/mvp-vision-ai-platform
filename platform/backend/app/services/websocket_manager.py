"""
WebSocket Manager for real-time updates.

Manages WebSocket connections and broadcasts training job updates to connected clients.
"""

import asyncio
import json
import logging
from typing import Dict, Set, Optional
from fastapi import WebSocket
from datetime import datetime

logger = logging.getLogger(__name__)


class WebSocketManager:
    """
    Manages WebSocket connections and message broadcasting.

    Supports:
    - Multiple concurrent connections
    - Filtering by job_id or session_id
    - Automatic reconnection handling
    """

    def __init__(self):
        """Initialize WebSocket manager"""
        # All active connections
        self.active_connections: Set[WebSocket] = set()

        # Connections by job_id (for targeted notifications)
        self.job_connections: Dict[int, Set[WebSocket]] = {}

        # Connections by session_id (for user-specific notifications)
        self.session_connections: Dict[int, Set[WebSocket]] = {}

        logger.info("[WebSocketManager] Initialized")

    async def connect(
        self,
        websocket: WebSocket,
        job_id: Optional[int] = None,
        session_id: Optional[int] = None,
    ):
        """
        Register a new WebSocket connection.

        Args:
            websocket: WebSocket connection
            job_id: Optional job ID to subscribe to
            session_id: Optional session ID for user-specific updates
        """
        await websocket.accept()
        self.active_connections.add(websocket)

        # Subscribe to specific job
        if job_id:
            if job_id not in self.job_connections:
                self.job_connections[job_id] = set()
            self.job_connections[job_id].add(websocket)
            logger.info(f"[WebSocketManager] Client subscribed to job {job_id}")

        # Subscribe to session
        if session_id:
            if session_id not in self.session_connections:
                self.session_connections[session_id] = set()
            self.session_connections[session_id].add(websocket)
            logger.info(f"[WebSocketManager] Client subscribed to session {session_id}")

        # Send welcome message
        await self.send_personal_message(
            {
                "type": "connected",
                "message": "Connected to training updates",
                "timestamp": datetime.utcnow().isoformat(),
            },
            websocket,
        )

    def disconnect(self, websocket: WebSocket):
        """
        Unregister a WebSocket connection.

        Args:
            websocket: WebSocket connection to remove
        """
        # Remove from active connections
        self.active_connections.discard(websocket)

        # Remove from job subscriptions
        for job_id, connections in list(self.job_connections.items()):
            connections.discard(websocket)
            if not connections:
                del self.job_connections[job_id]

        # Remove from session subscriptions
        for session_id, connections in list(self.session_connections.items()):
            connections.discard(websocket)
            if not connections:
                del self.session_connections[session_id]

        logger.info("[WebSocketManager] Client disconnected")

    async def send_personal_message(self, message: dict, websocket: WebSocket):
        """
        Send message to a specific connection.

        Args:
            message: Message dict to send
            websocket: Target WebSocket connection
        """
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"[WebSocketManager] Error sending personal message: {e}")
            self.disconnect(websocket)

    async def broadcast(self, message: dict):
        """
        Broadcast message to all connected clients.

        Args:
            message: Message dict to broadcast
        """
        if not self.active_connections:
            return

        disconnected = set()

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"[WebSocketManager] Error broadcasting: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

    async def broadcast_to_job(self, job_id: int, message: dict):
        """
        Broadcast message to all clients subscribed to a specific job.

        Args:
            job_id: Training job ID
            message: Message dict to send
        """
        if job_id not in self.job_connections:
            logger.debug(f"[WebSocketManager] No subscribers for job {job_id}")
            return

        connections = self.job_connections[job_id].copy()
        disconnected = set()

        logger.info(f"[WebSocketManager] Broadcasting to job {job_id}: {message.get('type')} ({len(connections)} clients)")

        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"[WebSocketManager] Error broadcasting to job {job_id}: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

        if not disconnected:
            logger.debug(f"[WebSocketManager] Successfully broadcasted to {len(connections)} clients")

    async def broadcast_to_session(self, session_id: int, message: dict):
        """
        Broadcast message to all clients subscribed to a specific session.

        Args:
            session_id: Session ID
            message: Message dict to send
        """
        if session_id not in self.session_connections:
            return

        connections = self.session_connections[session_id].copy()
        disconnected = set()

        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"[WebSocketManager] Error broadcasting to session {session_id}: {e}")
                disconnected.add(connection)

        # Clean up disconnected clients
        for connection in disconnected:
            self.disconnect(connection)

    def get_connection_count(self) -> int:
        """Get total number of active connections"""
        return len(self.active_connections)

    def get_job_subscriber_count(self, job_id: int) -> int:
        """Get number of clients subscribed to a job"""
        return len(self.job_connections.get(job_id, set()))


# Global WebSocket manager instance
_ws_manager_instance: Optional[WebSocketManager] = None


def get_websocket_manager() -> WebSocketManager:
    """Get or create global WebSocket manager instance"""
    global _ws_manager_instance
    if _ws_manager_instance is None:
        _ws_manager_instance = WebSocketManager()
    return _ws_manager_instance

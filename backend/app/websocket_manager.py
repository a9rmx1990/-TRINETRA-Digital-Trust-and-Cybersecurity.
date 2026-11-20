"""WebSocket Connection Hub for Real-Time SOC Stream."""

import asyncio
from typing import List, Dict, Any
from fastapi import WebSocket

class SOCConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]):
        """Broadcasts event payload to all connected frontend SOC clients."""
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                disconnected.append(connection)

        for dead in disconnected:
            self.disconnect(dead)

# Global singleton
ws_manager = SOCConnectionManager()

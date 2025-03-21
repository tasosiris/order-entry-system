import json
import asyncio
from typing import Dict, List, Any, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect

class ConnectionManager:
    """
    WebSocket connection manager for real-time updates.
    Supports channels subscriptions to allow filtering updates.
    """
    
    def __init__(self):
        # All active connections
        self.active_connections: List[WebSocket] = []
        
        # Connection subscriptions (WebSocket -> Set of channels)
        self.subscriptions: Dict[WebSocket, Set[str]] = {}
        
        # Channel subscribers (channel -> Set of WebSockets)
        self.channels: Dict[str, Set[WebSocket]] = {}
        
    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection."""
        await websocket.accept()
        self.active_connections.append(websocket)
        self.subscriptions[websocket] = set()
        
    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            
        # Remove from subscriptions
        if websocket in self.subscriptions:
            # Get all channels this connection was subscribed to
            channels = self.subscriptions[websocket]
            
            # Remove from each channel
            for channel in channels:
                if channel in self.channels and websocket in self.channels[channel]:
                    self.channels[channel].remove(websocket)
                    
            # Remove subscription record
            del self.subscriptions[websocket]
    
    async def subscribe(self, websocket: WebSocket, channel: str):
        """Subscribe a connection to a channel."""
        # Add to connection's subscriptions
        if websocket not in self.subscriptions:
            self.subscriptions[websocket] = set()
        self.subscriptions[websocket].add(channel)
        
        # Add to channel's subscribers
        if channel not in self.channels:
            self.channels[channel] = set()
        self.channels[channel].add(websocket)
        
        # Send confirmation
        await websocket.send_json({
            "type": "subscription",
            "channel": channel,
            "status": "subscribed"
        })
    
    async def unsubscribe(self, websocket: WebSocket, channel: str):
        """Unsubscribe a connection from a channel."""
        # Remove from connection's subscriptions
        if websocket in self.subscriptions and channel in self.subscriptions[websocket]:
            self.subscriptions[websocket].remove(channel)
            
        # Remove from channel's subscribers
        if channel in self.channels and websocket in self.channels[channel]:
            self.channels[channel].remove(websocket)
            
        # Send confirmation
        await websocket.send_json({
            "type": "subscription",
            "channel": channel,
            "status": "unsubscribed"
        })
    
    async def broadcast(self, message: Any, channel: Optional[str] = None):
        """
        Broadcast a message to all connections or to a specific channel.
        
        Args:
            message: The message to send (will be converted to JSON)
            channel: Optional channel name to limit broadcast
        """
        try:
            # Select target connections
            if channel is not None and channel in self.channels:
                targets = list(self.channels[channel])
            else:
                targets = self.active_connections
                
            # Skip if no targets
            if not targets:
                return
                
            # Ensure message is JSON-serializable
            if not isinstance(message, (dict, list, str, int, float, bool, type(None))):
                message = str(message)
                
            # Send to all targets
            disconnected = []
            for connection in targets:
                try:
                    await connection.send_json(message)
                except (WebSocketDisconnect, RuntimeError) as e:
                    # Log the error
                    print(f"WebSocket error during broadcast: {e}")
                    # Mark for removal
                    disconnected.append(connection)
                    
            # Clean up any disconnected clients
            for connection in disconnected:
                self.disconnect(connection)
        except Exception as e:
            # Log any unexpected errors
            print(f"Error in broadcast method: {e}")

# Create a singleton instance
connection_manager = ConnectionManager() 
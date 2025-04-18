"""
AAPL Data Streamer

This module provides a simplified data streamer for AAPL stocks.
It generates synthetic data without external dependencies.
"""

import time
import random
import asyncio
from datetime import datetime

# Define a simple aapl_streamer object
class AAPLDataStreamer:
    def __init__(self):
        self.base_price = 170.0
        self.running = False
        self.subscribers = []
    
    async def start(self):
        """Start the data streaming"""
        self.running = True
        # No actual streaming is done here
        return True
    
    async def stop(self):
        """Stop the data streaming"""
        self.running = False
        return True
    
    def subscribe(self, callback):
        """Add a subscriber to the data stream"""
        self.subscribers.append(callback)
        return True
    
    def unsubscribe(self, callback):
        """Remove a subscriber from the data stream"""
        if callback in self.subscribers:
            self.subscribers.remove(callback)
        return True

# Create a singleton instance
aapl_streamer = AAPLDataStreamer() 
"""Utility functions for the OES application."""

from .logging import setup_logging

from fastapi import Request, Depends
from typing import Optional

def get_current_trader_id(request: Request) -> str:
    """
    Get the current trader ID from the session.
    
    This is a placeholder implementation that returns a fixed trader ID.
    In a real application, this would extract the trader ID from the session,
    JWT token, or other authentication mechanism.
    
    Args:
        request: The FastAPI request object
    
    Returns:
        str: The current trader ID
    """
    # In a real app, you would get this from authentication
    # For now, we'll return a fixed ID for testing
    return "current-trader-1234" 
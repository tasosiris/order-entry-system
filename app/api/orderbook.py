from fastapi import APIRouter, HTTPException
from typing import Dict, List, Any, Optional
import logging

from ..order_book import order_book

# Configure logging
logger = logging.getLogger("oes.api.orderbook")
logging.basicConfig(level=logging.INFO)

# Create router with the correct prefix
router = APIRouter(tags=["orderbook"])

@router.get("/api/orderbook")
async def get_orderbook(depth: int = 10, include_internal: bool = False):
    """
    Get the current state of the order book.
    
    Parameters:
    - depth: How many price levels to include (default 10)
    - include_internal: Whether to include dark pool orders (default False)
    """
    try:
        logger.info(f"Fetching orderbook with depth={depth}, include_internal={include_internal}")
        book = order_book.get_order_book(depth=depth, include_internal=include_internal)
        logger.info(f"Found {len(book.get('bids', []))} bids and {len(book.get('asks', []))} asks")
        return book
    except Exception as e:
        logger.error(f"Error fetching order book: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/trades")
async def get_trades(limit: int = 20, include_internal: bool = False):
    """
    Get the most recent trades.
    
    Parameters:
    - limit: Maximum number of trades to return (default 20)
    - include_internal: Whether to include dark pool trades (default False)
    """
    try:
        logger.info(f"Fetching trades with limit={limit}, include_internal={include_internal}")
        trades = order_book.get_recent_trades(limit=limit, include_internal=include_internal)
        logger.info(f"Found {len(trades)} trades")
        return trades
    except Exception as e:
        logger.error(f"Error fetching trades: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

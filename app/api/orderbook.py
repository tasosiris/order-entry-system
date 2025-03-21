from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Any, Optional
import logging

from ..order_book import order_book

# Configure logging
logger = logging.getLogger("oes.api.orderbook")
logging.basicConfig(level=logging.INFO)

# Create router with the correct prefix
router = APIRouter(tags=["orderbook"])

SUPPORTED_ASSET_TYPES = ["stocks", "futures", "options", "crypto"]

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

@router.get("/api/orderbook/internal")
async def get_internal_orderbook(
    asset_type: str = Query(..., description="Asset type (stocks, futures, options, crypto)"),
    symbol: Optional[str] = None,
    depth: int = 10
):
    """
    Get the internal (dark pool) order book for a specific asset type.
    
    Parameters:
    - asset_type: Type of asset (stocks, futures, options, crypto)
    - symbol: Optional symbol to filter by
    - depth: How many price levels to include (default 10)
    """
    try:
        if asset_type.lower() not in SUPPORTED_ASSET_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported asset type. Must be one of: {', '.join(SUPPORTED_ASSET_TYPES)}")
        
        logger.info(f"Fetching internal orderbook for {asset_type} with depth={depth}")
        book = order_book.get_order_book(
            depth=depth,
            include_internal=True,
            asset_type=asset_type.lower(),
            symbol=symbol
        )
        # Filter to only include internal orders
        book['bids'] = [order for order in book.get('bids', []) if order.get('internal_match') == 'True']
        book['asks'] = [order for order in book.get('asks', []) if order.get('internal_match') == 'True']
        logger.info(f"Found {len(book.get('bids', []))} internal bids and {len(book.get('asks', []))} internal asks")
        return book
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching internal order book: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/orderbook/external")
async def get_external_orderbook(
    asset_type: str = Query(..., description="Asset type (stocks, futures, options, crypto)"),
    symbol: Optional[str] = None,
    depth: int = 10
):
    """
    Get the external (public) order book for a specific asset type.
    
    Parameters:
    - asset_type: Type of asset (stocks, futures, options, crypto)
    - symbol: Optional symbol to filter by
    - depth: How many price levels to include (default 10)
    """
    try:
        if asset_type.lower() not in SUPPORTED_ASSET_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported asset type. Must be one of: {', '.join(SUPPORTED_ASSET_TYPES)}")
        
        logger.info(f"Fetching external orderbook for {asset_type} with depth={depth}")
        book = order_book.get_order_book(
            depth=depth,
            include_internal=False,
            asset_type=asset_type.lower(),
            symbol=symbol
        )
        # Filter to only include external orders
        book['bids'] = [order for order in book.get('bids', []) if order.get('internal_match') != 'True']
        book['asks'] = [order for order in book.get('asks', []) if order.get('internal_match') != 'True']
        logger.info(f"Found {len(book.get('bids', []))} external bids and {len(book.get('asks', []))} external asks")
        return book
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching external order book: {e}", exc_info=True)
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

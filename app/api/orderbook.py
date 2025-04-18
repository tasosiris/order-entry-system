from fastapi import APIRouter, HTTPException, Query, Depends
from typing import Dict, List, Any, Optional
import logging

from ..order_book import order_book
from ..utils import get_current_trader_id

# Configure logging
logger = logging.getLogger("oes.api.orderbook")
logging.basicConfig(level=logging.INFO)

# Create router with the correct prefix
router = APIRouter(tags=["orderbook"])

SUPPORTED_ASSET_TYPES = ["stocks", "futures", "options", "crypto"]

@router.get("/api/orderbook")
async def get_orderbook(
    depth: int = 10, 
    include_internal: bool = False,
    symbol: Optional[str] = None,
    asset_type: Optional[str] = None
):
    """
    Get the current state of the order book.
    
    Parameters:
    - depth: How many price levels to include (default 10)
    - include_internal: Whether to include dark pool orders (default False)
    - symbol: Optional symbol to filter by
    - asset_type: Optional asset type to filter by
    """
    try:
        logger.info(f"Fetching orderbook with depth={depth}, include_internal={include_internal}" + 
                   (f", symbol={symbol}" if symbol else "") +
                   (f", asset_type={asset_type}" if asset_type else ""))
        
        book = order_book.get_order_book(
            depth=depth, 
            include_internal=include_internal,
            symbol=symbol,
            asset_type=asset_type
        )
        
        logger.info(f"Found {len(book.get('bids', []))} bids and {len(book.get('asks', []))} asks")
        return book
    except Exception as e:
        logger.error(f"Error fetching order book: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/api/orderbook/internal")
async def get_internal_orderbook(
    asset_type: str = Query(..., description="Asset type (stocks, futures, options, crypto)"),
    symbol: Optional[str] = None,
    depth: int = 10,
    trader_id: str = Depends(get_current_trader_id)  # Add dependency to get current trader ID
):
    """
    Get the internal order book specific to the current trader.
    
    Parameters:
    - asset_type: Type of asset (stocks, futures, options, crypto)
    - symbol: Optional symbol to filter by
    - depth: How many price levels to include (default 10)
    """
    try:
        if asset_type.lower() not in SUPPORTED_ASSET_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported asset type. Must be one of: {', '.join(SUPPORTED_ASSET_TYPES)}")
        
        logger.info(f"Fetching internal orderbook for trader {trader_id}, asset {asset_type} with depth={depth}")
        
        # Get all internal orders
        book = order_book.get_order_book(
            depth=100,  # Get more orders initially to filter
            include_internal=True,  # Include internal orders only
            asset_type=asset_type.lower(),
            symbol=symbol
        )
        
        # Filter to only include orders from this trader
        book['bids'] = [order for order in book.get('bids', []) if order.get('trader_id') == trader_id]
        book['asks'] = [order for order in book.get('asks', []) if order.get('trader_id') == trader_id]
        
        # Respect the depth parameter after filtering
        book['bids'] = book['bids'][:depth]
        book['asks'] = book['asks'][:depth]
        
        logger.info(f"Found {len(book.get('bids', []))} trader bids and {len(book.get('asks', []))} trader asks")
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
            include_internal=False,  # Don't include internal orders in external book
            asset_type=asset_type.lower(),
            symbol=symbol
        )
        
        # Remove the filtering since we want all exchange orders
        # book['bids'] = [order for order in book.get('bids', []) if order.get('internal_match') != 'True']
        # book['asks'] = [order for order in book.get('asks', []) if order.get('internal_match') != 'True']
        
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

@router.get("/api/orders/my")
async def get_my_orders(
    status: str = Query("open", description="Order status: open, filled, or cancelled"),
    symbol: Optional[str] = None,
    trader_id: str = Depends(get_current_trader_id)
):
    """
    Get orders belonging to the current trader.
    
    Parameters:
    - status: Order status (open, filled, cancelled)
    - symbol: Optional symbol to filter orders
    """
    try:
        logger.info(f"Fetching {status} orders for trader {trader_id}" + (f" and symbol {symbol}" if symbol else ""))
        
        if status not in ["open", "filled", "cancelled"]:
            raise HTTPException(status_code=400, detail="Status must be 'open', 'filled', or 'cancelled'")
        
        # Get orders for this trader
        orders = order_book.get_orders_by_status(
            status=status,
            internal_only=False,  # Get both internal and external orders
            trader_id=trader_id,  # Filter by trader ID
            symbol=symbol  # Filter by symbol if provided
        )
        
        logger.info(f"Found {len(orders)} {status} orders for trader {trader_id}")
        return {"orders": orders}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching trader orders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

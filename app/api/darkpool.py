from fastapi import APIRouter, HTTPException, Form, Depends
from fastapi.responses import JSONResponse
from typing import Dict, Any, Optional
import logging

from ..order_book import order_book
from ..redis_client import DARK_POOL_ENABLED
from .orders import create_order

# Configure logging
logger = logging.getLogger("oes.api.darkpool")
logging.basicConfig(level=logging.INFO)

# Create router
router = APIRouter(tags=["darkpool"])

@router.post("/api/darkpool/orders")
async def create_internal_order(
    type: str = Form(...),
    symbol: str = Form(...),
    price: float = Form(...),
    quantity: float = Form(...),
    order_type: str = Form("limit"),
    tif: str = Form("day"),
    instrument: str = Form("Stocks")
):
    """
    Submit a new order directly to the dark pool.
    This is a convenience endpoint that simply sets internal=True.
    """
    # Force internal routing
    return await create_order(
        type=type,
        symbol=symbol,
        price=price,
        quantity=quantity,
        order_type=order_type,
        tif=tif,
        instrument=instrument,
        internal=True
    )

@router.get("/api/darkpool/status")
async def get_darkpool_status():
    """Get the current status of the dark pool."""
    try:
        # Count orders in the dark pool
        internal_buy_count = order_book.redis.zcard("darkpool:buy")
        internal_sell_count = order_book.redis.zcard("darkpool:sell")
        
        # Count trades
        internal_trade_count = order_book.redis.llen("darkpool:trades")
        
        return {
            "enabled": DARK_POOL_ENABLED,
            "buy_orders": internal_buy_count,
            "sell_orders": internal_sell_count,
            "trades": internal_trade_count
        }
    except Exception as e:
        logger.error(f"Error getting dark pool status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

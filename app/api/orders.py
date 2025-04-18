import time
import json
from fastapi import APIRouter, HTTPException, Form, Depends, Query, Request, Body
from fastapi.responses import JSONResponse, HTMLResponse
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
import logging
import re
import random

from ..order_book import order_book
from ..utils import get_current_trader_id

# Configure logging
logger = logging.getLogger("oes.api.orders")
logging.basicConfig(level=logging.INFO)

# Create router
router = APIRouter(tags=["orders"])

# Sample order data for different asset types and statuses
SAMPLE_ORDERS = {
    "stocks": {
        "open": [
            {"id": "ord-s-1", "symbol": "AAPL", "type": "buy", "quantity": 100, "price": 182.50, "status": "open", "time": int(time.time()) - 120},
            {"id": "ord-s-2", "symbol": "MSFT", "type": "sell", "quantity": 50, "price": 420.00, "status": "open", "time": int(time.time()) - 180}
        ],
        "filled": [
            {"id": "ord-s-3", "symbol": "AAPL", "type": "buy", "quantity": 50, "price": 180.75, "status": "filled", "fill_price": 180.75, "time": int(time.time()) - 3600},
            {"id": "ord-s-4", "symbol": "GOOGL", "type": "sell", "quantity": 25, "price": 175.00, "status": "filled", "fill_price": 175.10, "time": int(time.time()) - 7200}
        ],
        "cancelled": [
            {"id": "ord-s-5", "symbol": "TSLA", "type": "buy", "quantity": 20, "price": 175.00, "status": "cancelled", "time": int(time.time()) - 10800}
        ]
    },
    "futures": {
        "open": [
            {"id": "ord-f-1", "symbol": "ES", "type": "buy", "quantity": 2, "price": 5220.00, "status": "open", "time": int(time.time()) - 150},
            {"id": "ord-f-2", "symbol": "NQ", "type": "sell", "quantity": 1, "price": 18300.00, "status": "open", "time": int(time.time()) - 210}
        ],
        "filled": [
            {"id": "ord-f-3", "symbol": "CL", "type": "buy", "quantity": 5, "price": 78.50, "status": "filled", "fill_price": 78.45, "time": int(time.time()) - 4800},
            {"id": "ord-f-4", "symbol": "GC", "type": "sell", "quantity": 3, "price": 2420.00, "status": "filled", "fill_price": 2418.50, "time": int(time.time()) - 9000}
        ],
        "cancelled": [
            {"id": "ord-f-5", "symbol": "SI", "type": "buy", "quantity": 10, "price": 27.50, "status": "cancelled", "time": int(time.time()) - 12600}
        ]
    },
    "options": {
        "open": [
            {"id": "ord-o-1", "symbol": "AAPL 190 Call", "type": "buy", "quantity": 10, "price": 3.25, "status": "open", "time": int(time.time()) - 180},
            {"id": "ord-o-2", "symbol": "SPY 450 Put", "type": "sell", "quantity": 5, "price": 2.45, "status": "open", "time": int(time.time()) - 240}
        ],
        "filled": [
            {"id": "ord-o-3", "symbol": "MSFT 420 Call", "type": "buy", "quantity": 7, "price": 4.50, "status": "filled", "fill_price": 4.45, "time": int(time.time()) - 5400},
            {"id": "ord-o-4", "symbol": "QQQ 390 Put", "type": "sell", "quantity": 3, "price": 3.25, "status": "filled", "fill_price": 3.30, "time": int(time.time()) - 10200}
        ],
        "cancelled": [
            {"id": "ord-o-5", "symbol": "TSLA 200 Call", "type": "buy", "quantity": 5, "price": 5.75, "status": "cancelled", "time": int(time.time()) - 14400}
        ]
    },
    "crypto": {
        "open": [
            {"id": "ord-c-1", "symbol": "BTC/USD", "type": "buy", "quantity": 0.5, "price": 62300.00, "status": "open", "time": int(time.time()) - 300},
            {"id": "ord-c-2", "symbol": "ETH/USD", "type": "sell", "quantity": 2.5, "price": 3450.00, "status": "open", "time": int(time.time()) - 360}
        ],
        "filled": [
            {"id": "ord-c-3", "symbol": "BTC/USD", "type": "buy", "quantity": 0.25, "price": 61950.00, "status": "filled", "fill_price": 61925.00, "time": int(time.time()) - 7200},
            {"id": "ord-c-4", "symbol": "SOL/USD", "type": "sell", "quantity": 20, "price": 124.50, "status": "filled", "fill_price": 124.75, "time": int(time.time()) - 14400}
        ],
        "cancelled": [
            {"id": "ord-c-5", "symbol": "XRP/USD", "type": "buy", "quantity": 1000, "price": 0.58, "status": "cancelled", "time": int(time.time()) - 21600}
        ]
    }
}

# Pydantic model for order edit
class OrderEdit(BaseModel):
    price: Optional[float] = None
    quantity: Optional[float] = None

@router.post("/api/orders")
async def create_order(
    type: str = Form(...),
    symbol: str = Form(...),
    price: float = Form(...),
    quantity: float = Form(...),
    order_type: str = Form("limit"),
    tif: str = Form("day"),
    asset_type: str = Form("stocks"),
    internal: bool = Form(False)
):
    """
    Create a new order.
    
    Parameters:
    - type: 'buy' or 'sell'
    - symbol: Asset symbol (e.g., 'AAPL')
    - price: Price per unit
    - quantity: Amount to trade
    - order_type: 'market' or 'limit'
    - tif: Time in force ('day', 'gtc', 'ioc', 'fok')
    - asset_type: Asset type ('stocks', 'futures', 'options', 'crypto')
    - internal: Whether to route to internal book (dark pool)
    """
    try:
        logger.info(f"Creating new {type} order for {quantity} {symbol} @ {price}")
        
        # Create order data
        order_data = {
            "type": type,
            "symbol": symbol,
            "price": price,
            "quantity": quantity,
            "order_type": order_type,
            "tif": tif,
            "asset_type": asset_type,
            "internal": internal,
            "timestamp": time.time()
        }
        
        # Submit to order book
        order = await order_book.submit_order(order_data)
        
        if order.get("status") == "rejected":
            logger.warning(f"Order rejected: {order.get('reject_reason')}")
            return JSONResponse(
                status_code=400, 
                content={
                    "success": False, 
                    "message": f"Order rejected: {order.get('reject_reason')}",
                    "order": order
                }
            )
        
        logger.info(f"Order accepted: {order.get('id')}")
        
        # Return success response
        return JSONResponse(
            status_code=201,
            content={
                "success": True,
                "message": f"Order created successfully",
                "order": order
            }
        )
    except Exception as e:
        logger.error(f"Error creating order: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"success": False, "message": f"Internal server error: {str(e)}"}
        )

@router.get("/api/orders/open")
async def get_open_orders(
    asset_type: Optional[str] = None,
    internal_only: bool = False,
    trader_id: Optional[str] = None
):
    """
    Get open orders with optional filtering.
    
    Parameters:
    - asset_type: Optional asset type filter
    - internal_only: Whether to return only internal orders
    - trader_id: Optional trader ID filter
    """
    try:
        logger.info(f"Fetching open orders (asset_type={asset_type}, internal_only={internal_only})")
        
        # Get open orders from order book
        orders = order_book.get_orders_by_status("open", internal_only=internal_only, trader_id=trader_id)
        
        # Filter by asset type if provided
        if asset_type:
            orders = [order for order in orders if order.get("asset_type") == asset_type]
        
        logger.info(f"Found {len(orders)} open orders")
        
        return orders
    except Exception as e:
        logger.error(f"Error fetching open orders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/api/orders/filled")
async def get_filled_orders(
    asset_type: Optional[str] = None,
    internal_only: bool = False,
    trader_id: Optional[str] = None
):
    """
    Get filled orders with optional filtering.
    
    Parameters:
    - asset_type: Optional asset type filter
    - internal_only: Whether to return only internal orders
    - trader_id: Optional trader ID filter
    """
    try:
        logger.info(f"Fetching filled orders (asset_type={asset_type}, internal_only={internal_only})")
        
        # Get filled orders from order book
        orders = order_book.get_orders_by_status("filled", internal_only=internal_only, trader_id=trader_id)
        
        # Filter by asset type if provided
        if asset_type:
            orders = [order for order in orders if order.get("asset_type") == asset_type]
        
        logger.info(f"Found {len(orders)} filled orders")
        
        return orders
    except Exception as e:
        logger.error(f"Error fetching filled orders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/api/orders/cancelled")
async def get_cancelled_orders(
    asset_type: Optional[str] = None,
    internal_only: bool = False,
    trader_id: Optional[str] = None
):
    """
    Get cancelled orders with optional filtering.
    
    Parameters:
    - asset_type: Optional asset type filter
    - internal_only: Whether to return only internal orders
    - trader_id: Optional trader ID filter
    """
    try:
        logger.info(f"Fetching cancelled orders (asset_type={asset_type}, internal_only={internal_only})")
        
        # Get cancelled orders from order book
        orders = order_book.get_orders_by_status("cancelled", internal_only=internal_only, trader_id=trader_id)
        
        # Filter by asset type if provided
        if asset_type:
            orders = [order for order in orders if order.get("asset_type") == asset_type]
        
        logger.info(f"Found {len(orders)} cancelled orders")
        
        return orders
    except Exception as e:
        logger.error(f"Error fetching cancelled orders: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/api/orders/{order_id}")
async def get_order_by_id(order_id: str):
    """
    Get a specific order by ID.
    
    Parameters:
    - order_id: The ID of the order to retrieve
    """
    try:
        logger.info(f"Fetching order details for ID: {order_id}")
        
        # Get order details from order book
        order = order_book.get_order_details(order_id)
        
        if not order:
            logger.warning(f"Order not found: {order_id}")
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        logger.info(f"Found order: {order_id}")
        
        return order
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching order details: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/api/orders/{order_id}/edit")
async def edit_order(order_id: str, edit_data: OrderEdit):
    """
    Edit an existing order.
    
    Parameters:
    - order_id: The ID of the order to edit
    - edit_data: Object containing fields to update (price, quantity)
    """
    try:
        logger.info(f"Editing order {order_id}: {edit_data}")
        
        # Make sure we have at least one field to update
        if edit_data.price is None and edit_data.quantity is None:
            raise HTTPException(status_code=400, detail="No fields to update provided")
        
        # Prepare update data
        update = {}
        if edit_data.price is not None:
            update["price"] = float(edit_data.price)
        if edit_data.quantity is not None:
            update["quantity"] = float(edit_data.quantity)
        
        # Submit edit to order book
        updated_order = await order_book.edit_order(order_id, update)
        
        if not updated_order:
            logger.warning(f"Failed to edit order {order_id}: Order not found or not editable")
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found or not editable")
        
        logger.info(f"Order {order_id} edited successfully")
        
        return {
            "success": True,
            "message": "Order updated successfully",
            "order": updated_order
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error editing order: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.post("/api/orders/{order_id}/cancel")
async def cancel_order(order_id: str):
    """
    Cancel an open order.
    
    Parameters:
    - order_id: The ID of the order to cancel
    """
    try:
        logger.info(f"Cancelling order: {order_id}")
        
        # Submit cancel to order book
        success = order_book.cancel_order(order_id)
        
        if not success:
            logger.warning(f"Failed to cancel order {order_id}: Order not found or already cancelled")
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found or already cancelled")
        
        logger.info(f"Order {order_id} cancelled successfully")
        
        return {
            "success": True,
            "message": "Order cancelled successfully",
            "order_id": order_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling order: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/api/orders/recent")
async def get_recent_orders():
    """Get recent orders for display on dashboard."""
    try:
        # Generate some recent demo orders
        recent_orders = []
        
        for asset_type, orders in SAMPLE_ORDERS.items():
            for status, status_orders in orders.items():
                for order in status_orders:
                    # Clone the order and add some additional attributes
                    recent_order = order.copy()
                    recent_order["asset_type"] = asset_type
                    recent_orders.append(recent_order)
        
        # Sort by time (newest first)
        recent_orders.sort(key=lambda x: x.get("time", 0), reverse=True)
        
        # Take only the 10 most recent
        recent_orders = recent_orders[:10]
        
        # Format orders for display
        formatted_orders = []
        for order in recent_orders:
            formatted_order = {}
            formatted_order["id"] = order.get("id", "")
            formatted_order["asset_type"] = order.get("asset_type", "").capitalize()
            formatted_order["symbol"] = order.get("symbol", "")
            formatted_order["type"] = order.get("type", "").upper()
            formatted_order["price"] = f"${order.get('price', 0.00):.2f}"
            formatted_order["quantity"] = order.get("quantity", 0)
            formatted_order["status"] = order.get("status", "").capitalize()
            
            # Format time as relative time
            seconds_ago = int(time.time()) - order.get("time", 0)
            if seconds_ago < 60:
                formatted_order["time"] = f"{seconds_ago}s ago"
            elif seconds_ago < 3600:
                formatted_order["time"] = f"{seconds_ago // 60}m ago"
            else:
                formatted_order["time"] = f"{seconds_ago // 3600}h ago"
            
            formatted_orders.append(formatted_order)
        
        # Generate HTML rows for HTMX response
        html_rows = ""
        for order in formatted_orders:
            status_class = ""
            if order["status"] == "Filled":
                status_class = "positive"
            elif order["status"] == "Cancelled":
                status_class = "negative"
            
            html_rows += f"""
            <tr>
                <td>{order["id"]}</td>
                <td>{order["asset_type"]}</td>
                <td>{order["symbol"]}</td>
                <td>{order["type"]}</td>
                <td>{order["price"]}</td>
                <td>{order["quantity"]}</td>
                <td class="{status_class}">{order["status"]}</td>
                <td>{order["time"]}</td>
            </tr>
            """
        
        return HTMLResponse(content=html_rows)
    except Exception as e:
        logger.error(f"Error generating recent orders: {e}", exc_info=True)
        return HTMLResponse(content="<tr><td colspan='8'>Error loading recent orders</td></tr>")

# Legacy endpoints for compatibility

@router.get("/api/orders/{asset_type}/open")
async def get_open_orders_by_asset(asset_type: str):
    """Legacy endpoint for getting open orders by asset type."""
    return await get_open_orders(asset_type=asset_type)

@router.get("/api/orders/{asset_type}/filled")
async def get_filled_orders_by_asset(asset_type: str):
    """Legacy endpoint for getting filled orders by asset type."""
    return await get_filled_orders(asset_type=asset_type)

@router.get("/api/orders/{asset_type}/cancelled")
async def get_cancelled_orders_by_asset(asset_type: str):
    """Legacy endpoint for getting cancelled orders by asset type."""
    return await get_cancelled_orders(asset_type=asset_type)

@router.get("/api/orders/my")
async def get_my_orders(
    status: str = Query("open", description="Order status: open, filled, or cancelled"),
    symbol: Optional[str] = None,  # Add symbol parameter for filtering
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

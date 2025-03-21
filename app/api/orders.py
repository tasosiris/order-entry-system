import time
from fastapi import APIRouter, HTTPException, Form, Depends, Query
from fastapi.responses import JSONResponse, HTMLResponse
from typing import Dict, Any, Optional, List
import logging
import re
import random

from ..order_book import order_book

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
            {"id": "ord-o-3", "symbol": "MSFT 420 Call", "type": "buy", "quantity": 3, "price": 5.15, "status": "filled", "fill_price": 5.10, "time": int(time.time()) - 5400},
            {"id": "ord-o-4", "symbol": "QQQ 400 Put", "type": "sell", "quantity": 8, "price": 3.75, "status": "filled", "fill_price": 3.80, "time": int(time.time()) - 10200}
        ],
        "cancelled": [
            {"id": "ord-o-5", "symbol": "TSLA 180 Call", "type": "buy", "quantity": 2, "price": 4.20, "status": "cancelled", "time": int(time.time()) - 14400}
        ]
    },
    "crypto": {
        "open": [
            {"id": "ord-c-1", "symbol": "BTC/USD", "type": "buy", "quantity": 0.25, "price": 61500.00, "status": "open", "time": int(time.time()) - 210},
            {"id": "ord-c-2", "symbol": "ETH/USD", "type": "sell", "quantity": 1.5, "price": 3500.00, "status": "open", "time": int(time.time()) - 270}
        ],
        "filled": [
            {"id": "ord-c-3", "symbol": "SOL/USD", "type": "buy", "quantity": 10, "price": 120.50, "status": "filled", "fill_price": 120.25, "time": int(time.time()) - 6000},
            {"id": "ord-c-4", "symbol": "XRP/USD", "type": "sell", "quantity": 1000, "price": 0.60, "status": "filled", "fill_price": 0.595, "time": int(time.time()) - 11400}
        ],
        "cancelled": [
            {"id": "ord-c-5", "symbol": "DOGE/USD", "type": "buy", "quantity": 2000, "price": 0.125, "status": "cancelled", "time": int(time.time()) - 16200}
        ]
    }
}

@router.post("/api/orders")
async def create_order(
    type: str = Form(...),
    symbol: str = Form(...),
    price: float = Form(...),
    quantity: float = Form(...),
    order_type: str = Form("limit"),
    tif: str = Form("day"),
    instrument: str = Form("Stocks"),
    internal: bool = Form(False)
):
    """
    Submit a new order to the system.

    Required fields:
    - type: "buy" or "sell"
    - symbol: Asset symbol
    - price: Price per unit
    - quantity: Amount to buy/sell
    
    Optional fields:
    - order_type: "limit" or "market"
    - tif: Time in force ("day", "gtc", "ioc", "fok")
    - instrument: Instrument type ("Stocks", "Futures", "Options", "Crypto")
    - internal: Whether to route to dark pool (internal matching)
    """
    try:
        # Start latency measurement
        start_time = time.time() * 1000  # Convert to milliseconds
        
        # Log the incoming order
        logger.info(f"Received order: {type} {quantity} {symbol} @ {price} (internal={internal})")

        # Define the required fields for an order
        required_fields = ["type", "symbol", "price", "quantity"]
        
        # Check if all required fields are present in the order
        for field in required_fields:
            if field not in {"type", "symbol", "price", "quantity"}:
                logger.warning(f"Missing required field: {field}")
                # Raise an HTTPException with a 400 status code for missing fields
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required field: {field}"
                )

        # Validate the 'price' field
        try:
            price = float(price)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid price: {price} - {e}")
            # Raise an HTTPException with a 400 status code for invalid price
            raise HTTPException(
                status_code=400,
                detail=f"Invalid price value: {price}. Must be a number."
            )

        # Validate the 'quantity' field
        try:
            quantity = float(quantity)
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid quantity: {quantity} - {e}")
            # Raise an HTTPException with a 400 status code for invalid quantity
            raise HTTPException(
                status_code=400,
                detail=f"Invalid quantity value: {quantity}. Must be a number."
            )

        # Validate the 'type' field
        if type.lower() not in ["buy", "sell"]:
            logger.warning(f"Invalid order type: {type}")
            # Raise an HTTPException with a 400 status code for invalid order type
            raise HTTPException(
                status_code=400,
                detail=f"Invalid order type: {type}. Must be 'buy' or 'sell'."
            )

        # Create order object with all fields
        order = {
            "type": type,
            "symbol": symbol,
            "price": price,
            "quantity": quantity,
            "order_type": order_type,
            "tif": tif,
            "instrument": instrument,
            "internal": internal
        }
        
        # Submit the order to the order book for processing
        result = await order_book.submit_order(order)
        
        # End latency measurement
        end_time = time.time() * 1000  # Convert to milliseconds
        latency = round(end_time - start_time)
        
        # Add latency to the result
        result["latency"] = latency
        
        # Record latency in Redis for tracking
        try:
            order_book.redis.lpush("latency_measurements", latency)
            order_book.redis.ltrim("latency_measurements", 0, 49)  # Keep last 50 measurements
        except Exception as e:
            logger.warning(f"Error saving latency measurement: {e}")

        # Check if the order was rejected
        if result.get("status") == "rejected":
            logger.warning(f"Order rejected: {result.get('reason')}")
            # Return a JSON response with a 400 status code and rejection reason
            return JSONResponse(
                status_code=400,
                content={
                    "status": "rejected",
                    "reason": result.get("reason", "Order was not accepted"),
                    "latency": latency
                },
                headers={"Content-Type": "application/json"}
            )

        # Log successful order
        logger.info(f"Order accepted: {result} (latency: {latency}ms)")
        # Return the successful order result
        return JSONResponse(
            content=result,
            headers={"Content-Type": "application/json"}
        )

    except HTTPException as http_exc:
        # Re-raise the HTTPException to be handled by FastAPI
        raise
    except Exception as e:
        # Log the unexpected error
        logger.error(f"Unexpected error in create_order: {e}", exc_info=True)
        # Return a JSON response with a 500 status code for server errors
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": f"Server error: {str(e)}"},
            headers={"Content-Type": "application/json"}
        )

@router.get("/api/orders/open", operation_id="get_open_orders")
async def get_open_orders():
    """Get all open orders for rendering in the UI."""
    try:
        print("[API] Fetching open orders")
        orders = order_book.get_orders_by_status("open")
        print(f"[API] Found {len(orders)} open orders")
        
        # Return a JSON response instead of HTML
        order_data = []
        for order in orders:
            # Format timestamp
            timestamp = time.strftime(
                "%H:%M:%S", 
                time.localtime(float(order.get("timestamp", 0)))
            )
            
            # Create simplified order data
            simplified_order = {
                "symbol": order.get("symbol", ""),
                "price": float(order.get("price", 0)),
                "quantity": float(order.get("quantity", 0)),
                "type": order.get("type", ""),
                # Full order details for modal display
                "details": {
                    "id": order.get("order_id", ""),
                    "symbol": order.get("symbol", ""),
                    "type": order.get("type", "").upper(),
                    "order_type": order.get("order_type", "limit").upper(),
                    "price": float(order.get("price", 0)),
                    "quantity": float(order.get("quantity", 0)),
                    "time": timestamp,
                    "status": "OPEN",
                    "internal": order.get("internal", False)
                }
            }
            order_data.append(simplified_order)
            
        if not order_data:
            print("[API] No open orders found")
            return JSONResponse(content={"orders": []})
        
        return JSONResponse(content={"orders": order_data})
        
    except Exception as e:
        logger.error(f"Error fetching open orders: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Error loading orders"}
        )

@router.get("/api/orders/filled", operation_id="get_filled_orders")
async def get_filled_orders():
    """Get all filled orders for rendering in the UI."""
    try:
        logger.info("Fetching filled orders")
        orders = order_book.get_orders_by_status("filled")
        logger.info(f"Found {len(orders)} filled orders")
        
        # Return a JSON response instead of HTML
        order_data = []
        for order in orders:
            # Format timestamp
            fill_time = time.strftime(
                "%H:%M:%S", 
                time.localtime(float(order.get("fill_time", 0)))
            )
            
            # Create simplified order data
            simplified_order = {
                "symbol": order.get("symbol", ""),
                "price": float(order.get("fill_price", 0)),
                "quantity": float(order.get("quantity", 0)),
                "type": order.get("type", ""),
                # Full order details for modal display
                "details": {
                    "id": order.get("order_id", ""),
                    "symbol": order.get("symbol", ""),
                    "type": order.get("type", "").upper(),
                    "order_type": order.get("order_type", "limit").upper(),
                    "price": float(order.get("fill_price", 0)),
                    "quantity": float(order.get("quantity", 0)),
                    "time": fill_time,
                    "status": "FILLED",
                    "internal": order.get("internal", False)
                }
            }
            order_data.append(simplified_order)
            
        if not order_data:
            logger.info("No filled orders found")
            return JSONResponse(content={"orders": []})
        
        logger.info(f"Returning {len(order_data)} filled orders")
        return JSONResponse(content={"orders": order_data})
        
    except Exception as e:
        logger.error(f"Error fetching filled orders: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Error loading orders"}
        )

@router.get("/api/orders/cancelled", operation_id="get_cancelled_orders")
async def get_cancelled_orders():
    """Get all cancelled orders for rendering in the UI."""
    try:
        logger.info("Fetching cancelled orders")
        orders = order_book.get_orders_by_status("cancelled")
        logger.info(f"Found {len(orders)} cancelled orders")
        
        # Return a JSON response instead of HTML
        order_data = []
        for order in orders:
            # Format timestamp
            cancel_time = time.strftime(
                "%H:%M:%S", 
                time.localtime(float(order.get("cancel_time", 0)))
            )
            
            # Create simplified order data
            simplified_order = {
                "symbol": order.get("symbol", ""),
                "price": float(order.get("price", 0)),
                "quantity": float(order.get("quantity", 0)),
                "type": order.get("type", ""),
                # Full order details for modal display
                "details": {
                    "id": order.get("order_id", ""),
                    "symbol": order.get("symbol", ""),
                    "type": order.get("type", "").upper(),
                    "order_type": order.get("order_type", "limit").upper(),
                    "price": float(order.get("price", 0)),
                    "quantity": float(order.get("quantity", 0)),
                    "time": cancel_time,
                    "status": "CANCELLED",
                    "internal": order.get("internal", False)
                }
            }
            order_data.append(simplified_order)
            
        if not order_data:
            logger.info("No cancelled orders found")
            return JSONResponse(content={"orders": []})
        
        logger.info(f"Returning {len(order_data)} cancelled orders")
        return JSONResponse(content={"orders": order_data})
        
    except Exception as e:
        logger.error(f"Error fetching cancelled orders: {e}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"error": "Error loading orders"}
        )

@router.get("/api/orders/{order_id}", operation_id="get_order_by_id")
async def get_order(order_id: str):
    """Get details of a specific order."""
    
    # Check if we're trying to access a special endpoint
    if order_id in ["open", "filled", "cancelled"]:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid order ID: {order_id} is a reserved keyword"
        )
            
    try:
        order = order_book.get_order(order_id)
        
        if not order:
            raise HTTPException(
                status_code=404,
                detail=f"Order {order_id} not found"
            )
            
        return order
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting order {order_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

@router.delete("/api/orders/{order_id}")
async def cancel_order(order_id: str):
    """Cancel an existing order."""
    try:
        success = order_book.cancel_order(order_id)
        
        if not success:
            raise HTTPException(
                status_code=404,
                detail=f"Order {order_id} not found or already filled"
            )
            
        return {"status": "cancelled", "order_id": order_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling order {order_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

# New endpoints for asset-specific order retrieval

@router.get("/api/orders/{asset_type}/open")
async def get_open_orders_by_asset(asset_type: str):
    """
    Get all open orders for a specific asset type.
    
    Args:
        asset_type: One of "stocks", "futures", "options", or "crypto"
    
    Returns:
        HTML formatted table rows for open orders of the specified asset type.
    """
    if asset_type not in SAMPLE_ORDERS:
        return f"<tr><td colspan='6'>No {asset_type} orders found</td></tr>"
    
    orders = SAMPLE_ORDERS[asset_type]["open"]
    
    # Create HTML response for HTMX
    html_rows = ""
    for order in orders:
        # Format the timestamp
        timestamp = time.strftime("%H:%M:%S", time.localtime(order["time"]))
        
        # Format the order row
        html_rows += f"""
        <tr>
            <td>{order["id"]}</td>
            <td>{order["symbol"]}</td>
            <td class="{'positive' if order['type'] == 'buy' else 'negative'}">{order["type"].upper()}</td>
            <td>{order["quantity"]}</td>
            <td>${order["price"]}</td>
            <td>{timestamp}</td>
            <td>
                <button class="btn-cancel-order" data-order-id="{order["id"]}">Cancel</button>
            </td>
        </tr>
        """
    
    return html_rows

@router.get("/api/orders/{asset_type}/filled")
async def get_filled_orders_by_asset(asset_type: str):
    """
    Get all filled orders for a specific asset type.
    
    Args:
        asset_type: One of "stocks", "futures", "options", or "crypto"
    
    Returns:
        HTML formatted table rows for filled orders of the specified asset type.
    """
    if asset_type not in SAMPLE_ORDERS:
        return f"<tr><td colspan='7'>No {asset_type} orders found</td></tr>"
    
    orders = SAMPLE_ORDERS[asset_type]["filled"]
    
    # Create HTML response for HTMX
    html_rows = ""
    for order in orders:
        # Format the timestamp
        timestamp = time.strftime("%H:%M:%S", time.localtime(order["time"]))
        
        # Format the order row
        html_rows += f"""
        <tr>
            <td>{order["id"]}</td>
            <td>{order["symbol"]}</td>
            <td class="{'positive' if order['type'] == 'buy' else 'negative'}">{order["type"].upper()}</td>
            <td>{order["quantity"]}</td>
            <td>${order["price"]}</td>
            <td>${order["fill_price"]}</td>
            <td>{timestamp}</td>
        </tr>
        """
    
    return html_rows

@router.get("/api/orders/{asset_type}/cancelled")
async def get_cancelled_orders_by_asset(asset_type: str):
    """
    Get all cancelled orders for a specific asset type.
    
    Args:
        asset_type: One of "stocks", "futures", "options", or "crypto"
    
    Returns:
        HTML formatted table rows for cancelled orders of the specified asset type.
    """
    if asset_type not in SAMPLE_ORDERS:
        return f"<tr><td colspan='6'>No {asset_type} orders found</td></tr>"
    
    orders = SAMPLE_ORDERS[asset_type]["cancelled"]
    
    # Create HTML response for HTMX
    html_rows = ""
    for order in orders:
        # Format the timestamp
        timestamp = time.strftime("%H:%M:%S", time.localtime(order["time"]))
        
        # Format the order row
        html_rows += f"""
        <tr>
            <td>{order["id"]}</td>
            <td>{order["symbol"]}</td>
            <td class="{'positive' if order['type'] == 'buy' else 'negative'}">{order["type"].upper()}</td>
            <td>{order["quantity"]}</td>
            <td>${order["price"]}</td>
            <td>{timestamp}</td>
        </tr>
        """
    
    return html_rows

# Keep the existing implementation for the general "recent orders" endpoint
@router.get("/api/orders/recent")
async def get_recent_orders():
    """
    Get the most recent orders across all asset types.
    
    Returns:
        HTML formatted table rows for the most recent orders.
    """
    # Collect a few recent orders across all asset types
    recent_orders = []
    
    for asset_type in SAMPLE_ORDERS:
        for status in ["open", "filled", "cancelled"]:
            orders = SAMPLE_ORDERS[asset_type][status]
            for order in orders:
                order_copy = order.copy()
                order_copy["asset_type"] = asset_type
                recent_orders.append(order_copy)
    
    # Sort by time (most recent first) and take top 5
    recent_orders.sort(key=lambda x: x["time"], reverse=True)
    recent_orders = recent_orders[:5]
    
    # Create HTML response for HTMX
    html_rows = ""
    for order in recent_orders:
        # Format the timestamp
        timestamp = time.strftime("%H:%M:%S", time.localtime(order["time"]))
        
        # Format the order row
        html_rows += f"""
        <tr>
            <td>{order["id"]}</td>
            <td>{order["asset_type"].capitalize()}</td>
            <td>{order["symbol"]}</td>
            <td class="{'positive' if order['type'] == 'buy' else 'negative'}">{order["type"].upper()}</td>
            <td>${order["price"]}</td>
            <td>{order["quantity"]}</td>
            <td>{order["status"].capitalize()}</td>
            <td>{timestamp}</td>
        </tr>
        """
    
    return html_rows

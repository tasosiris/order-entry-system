import time
from fastapi import APIRouter, HTTPException, Form, Depends
from fastapi.responses import JSONResponse, HTMLResponse
from typing import Dict, Any, Optional
import logging
import re

from ..order_book import order_book

# Configure logging
logger = logging.getLogger("oes.api.orders")
logging.basicConfig(level=logging.INFO)

# Create router
router = APIRouter(tags=["orders"])

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

        # Check if the order was rejected
        if result.get("status") == "rejected":
            logger.warning(f"Order rejected: {result.get('reason')}")
            # Return a JSON response with a 400 status code and rejection reason
            return JSONResponse(
                status_code=400,
                content={
                    "status": "rejected",
                    "reason": result.get("reason", "Order was not accepted")
                },
                headers={"Content-Type": "application/json"}
            )

        # Log successful order
        logger.info(f"Order accepted: {result}")
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
        
        # Format the response for HTMX consumption
        html_rows = []
        for order in orders:
            print(f"[API] Processing order: {order}")
            # Format timestamp
            timestamp = time.strftime(
                "%H:%M:%S", 
                time.localtime(float(order.get("timestamp", 0)))
            )
            
            # Create HTML table row
            is_internal = order.get("internal", "False") == "True"
            internal_badge = ' <span class="badge internal-badge">DARK</span>' if is_internal else ''
            
            html_row = f"""
            <tr>
                <td>{order.get("order_id", "")[:8]}...</td>
                <td>{order.get("symbol", "")}{internal_badge}</td>
                <td>{order.get("type", "").upper()}</td>
                <td class="price">{float(order.get("price", 0)):.2f}</td>
                <td>{float(order.get("quantity", 0)):.4f}</td>
                <td>{timestamp}</td>
                <td>
                    <button 
                        class="cancel-btn" 
                        hx-delete="/api/orders/{order.get('order_id', '')}" 
                        hx-target="#order-status"
                        hx-swap="innerHTML">
                        Cancel
                    </button>
                </td>
            </tr>
            """
            html_rows.append(html_row)
            
        if not html_rows:
            print("[API] No open orders found")
            response = HTMLResponse("""<tr><td colspan="7">No open orders</td></tr>""")
            print(f"[API] Sending response: {response.body.decode()}")
            return response
        
        response_html = "".join(html_rows)
        print(f"[API] Sending HTML response: {response_html}")
        return HTMLResponse(
            content=response_html,
            headers={"Content-Type": "text/html"}
        )
        
    except Exception as e:
        logger.error(f"Error fetching open orders: {e}", exc_info=True)
        return HTMLResponse("""<tr><td colspan="7">Error loading orders</td></tr>""")

@router.get("/api/orders/filled", operation_id="get_filled_orders")
async def get_filled_orders():
    """Get all filled orders for rendering in the UI."""
    try:
        logger.info("Fetching filled orders")
        orders = order_book.get_orders_by_status("filled")
        logger.info(f"Found {len(orders)} filled orders")
        
        # Format the response for HTMX consumption
        html_rows = []
        for order in orders:
            # Format timestamp
            fill_time = time.strftime(
                "%H:%M:%S", 
                time.localtime(float(order.get("fill_time", 0)))
            )
            
            # Create HTML table row
            is_internal = order.get("internal", "False") == "True"
            internal_badge = ' <span class="badge internal-badge">DARK</span>' if is_internal else ''
            
            html_row = f"""
            <tr>
                <td>{order.get("order_id", "")[:8]}...</td>
                <td>{order.get("symbol", "")}{internal_badge}</td>
                <td>{order.get("type", "").upper()}</td>
                <td class="price">{float(order.get("fill_price", 0)):.2f}</td>
                <td>{float(order.get("quantity", 0)):.4f}</td>
                <td>{fill_time}</td>
            </tr>
            """
            html_rows.append(html_row)
            
        if not html_rows:
            logger.info("No filled orders found")
            return HTMLResponse("""<tr><td colspan="6">No filled orders</td></tr>""")
            
        logger.info(f"Returning {len(html_rows)} filled order rows")
        return HTMLResponse("".join(html_rows))
        
    except Exception as e:
        logger.error(f"Error fetching filled orders: {e}", exc_info=True)
        return HTMLResponse("""<tr><td colspan="6">Error loading orders</td></tr>""")

@router.get("/api/orders/cancelled", operation_id="get_cancelled_orders")
async def get_cancelled_orders():
    """Get all cancelled orders for rendering in the UI."""
    try:
        logger.info("Fetching cancelled orders")
        orders = order_book.get_orders_by_status("cancelled")
        logger.info(f"Found {len(orders)} cancelled orders")
        
        # Format the response for HTMX consumption
        html_rows = []
        for order in orders:
            # Format timestamp
            cancel_time = time.strftime(
                "%H:%M:%S", 
                time.localtime(float(order.get("cancel_time", 0)))
            )
            
            # Create HTML table row
            is_internal = order.get("internal", "False") == "True"
            internal_badge = ' <span class="badge internal-badge">DARK</span>' if is_internal else ''
            
            html_row = f"""
            <tr>
                <td>{order.get("order_id", "")[:8]}...</td>
                <td>{order.get("symbol", "")}{internal_badge}</td>
                <td>{order.get("type", "").upper()}</td>
                <td class="price">{float(order.get("price", 0)):.2f}</td>
                <td>{float(order.get("quantity", 0)):.4f}</td>
                <td>{cancel_time}</td>
            </tr>
            """
            html_rows.append(html_row)
            
        if not html_rows:
            logger.info("No cancelled orders found")
            return HTMLResponse("""<tr><td colspan="6">No cancelled orders</td></tr>""")
            
        logger.info(f"Returning {len(html_rows)} cancelled order rows")
        return HTMLResponse("".join(html_rows))
        
    except Exception as e:
        logger.error(f"Error fetching cancelled orders: {e}", exc_info=True)
        return HTMLResponse("""<tr><td colspan="6">Error loading orders</td></tr>""")

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

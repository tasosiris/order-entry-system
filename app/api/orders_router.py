from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import json
import logging

from app.redis_client import redis_client
from app.matching_engine import matching_engine
from app.accounts import account_manager
from app.schemas import OrderResponse

# Configure logging
logger = logging.getLogger(__name__)

orders_router = APIRouter(
    prefix="/api/orders",
    tags=["orders"],
)

# Basic Order model
class Order(BaseModel):
    id: str
    symbol: str
    type: str
    quantity: int
    price: float
    status: str

# Order Edit model
class OrderEdit(BaseModel):
    price: Optional[float] = None
    quantity: Optional[int] = None

@orders_router.get("/open", response_model=Dict[str, List[Dict[str, Any]]])
async def get_open_orders(asset_type: str = None):
    """Get all open orders, optionally filtered by asset type."""
    try:
        # This is a temporary implementation - in the future, we'll use the matching engine
        # to get all open orders across all accounts
        orders = matching_engine.get_all_active_orders()
        
        # Filter by asset type if provided
        if asset_type:
            orders = [order for order in orders if order.get("asset_type") == asset_type]
            
        return {"orders": orders}
    except Exception as e:
        logger.error(f"Error getting open orders: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting open orders: {str(e)}")

@orders_router.get("/active", response_model=List[Dict[str, Any]])
async def get_all_active_orders(symbol: Optional[str] = None):
    """Get all orders across all accounts including filled orders, optionally filtered by symbol."""
    try:
        # Get ALL orders from matching engine, not just active ones
        orders = matching_engine.get_all_orders()
        
        # Filter by symbol if provided
        if symbol:
            orders = [order for order in orders if order.get("symbol") == symbol]
            
        # For debugging - log how many orders we're returning
        logger.info(f"Returning {len(orders)} orders from all accounts")
        
        return orders
    except Exception as e:
        logger.error(f"Error getting all orders: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting all orders: {str(e)}")

@orders_router.get("/{order_id}", response_model=Dict[str, Any])
async def get_order_by_id(order_id: str):
    """Get a specific order by its ID."""
    # Log the request for debugging
    logger.info(f"Fetching order details for ID: {order_id}")
    
    try:
        # First try to get from matching engine
        order = matching_engine.get_order(order_id)
        
        # If not found in matching engine, try direct Redis lookup
        if not order:
            # Try direct Redis lookup for more reliability
            order_json = redis_client.get(f"oes:order:{order_id}")
            if order_json:
                try:
                    order = json.loads(order_json)
                except Exception as e:
                    logger.error(f"Error parsing order JSON from Redis: {str(e)}", exc_info=True)
        
        if not order:
            logger.warning(f"Order not found: {order_id}")
            raise HTTPException(status_code=404, detail="Order not found")
            
        return order
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Error getting order {order_id}: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting order: {str(e)}")

@orders_router.get("/trades/recent", response_model=List[Dict[str, Any]])
async def get_recent_trades():
    """Get recent trades (matched orders)."""
    try:
        # Get trades from Redis
        trades_key = "oes:trades"
        trade_ids = redis_client.smembers(trades_key)
        
        if not trade_ids:
            return []
        
        trades = []
        # Get the 20 most recent trades
        for trade_id in list(trade_ids)[:20]:
            trade_key = f"oes:trade:{trade_id}"
            trade_json = redis_client.get(trade_key)
            
            if trade_json:
                try:
                    trade = json.loads(trade_json)
                    
                    # Calculate total value
                    price = float(trade.get('price', 0))
                    quantity = float(trade.get('quantity', 0))
                    trade['total'] = price * quantity
                    
                    # Get account names instead of just IDs
                    if trade.get('buy_account_id'):
                        buy_account = account_manager.get_account(trade.get('buy_account_id'))
                        if buy_account:
                            trade['buy_account'] = buy_account.name
                        else:
                            trade['buy_account'] = 'Unknown'
                    else:
                        trade['buy_account'] = 'Unknown'
                        
                    if trade.get('sell_account_id'):
                        sell_account = account_manager.get_account(trade.get('sell_account_id'))
                        if sell_account:
                            trade['sell_account'] = sell_account.name
                        else:
                            trade['sell_account'] = 'Unknown'
                    else:
                        trade['sell_account'] = 'Unknown'
                    
                    # Store the full IDs for potential detailed view
                    trade['buy_account_id_full'] = trade.get('buy_account_id', '')
                    trade['sell_account_id_full'] = trade.get('sell_account_id', '')
                    
                    trades.append(trade)
                except Exception as e:
                    logger.error(f"Error parsing trade JSON: {e}")
        
        # Sort by timestamp (newest first)
        trades.sort(key=lambda x: float(x.get('timestamp', 0)), reverse=True)
        
        return trades
    except Exception as e:
        logger.error(f"Error getting recent trades: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting recent trades: {str(e)}")

@orders_router.post("/{order_id}/edit", response_model=Dict[str, Any])
async def edit_order(order_id: str, edit_data: OrderEdit):
    """
    Edit an existing order.
    
    Args:
        order_id: The ID of the order to edit
        edit_data: New price and/or quantity
        
    Returns:
        Updated order data
    """
    try:
        # Validate data
        if edit_data.price is None and edit_data.quantity is None:
            raise HTTPException(
                status_code=400, 
                detail="No changes specified. Please provide new price and/or quantity."
            )
        
        # Get the current order
        order = matching_engine.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Check if order can be edited (only open/partially_filled)
        if order.get('status') not in ['open', 'partially_filled']:
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot edit order with status '{order.get('status')}'"
            )
        
        # Prepare update data
        update_data = {}
        if edit_data.price is not None:
            update_data['price'] = float(edit_data.price)
        if edit_data.quantity is not None:
            update_data['quantity'] = int(edit_data.quantity)
        
        # Apply the update
        updated_order = await matching_engine.edit_order(order_id, update_data)
        
        if not updated_order:
            raise HTTPException(
                status_code=500, 
                detail=f"Failed to update order {order_id}"
            )
        
        return {
            "success": True,
            "message": "Order updated successfully",
            "order": updated_order
        }
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error editing order: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail=f"Error editing order: {str(e)}"
        )

@orders_router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order(order_id: str, account_id: Optional[str] = None):
    """
    Cancel an order by ID.
    Optionally, verify the order belongs to the specified account before cancelling.
    """
    try:
        logger.info(f"Cancelling order: {order_id}")
        
        # Check if order exists first before trying to cancel
        order = matching_engine.get_order(order_id)
        if not order:
            logger.warning(f"Failed to cancel order {order_id}: Order not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Order {order_id} not found or already cancelled",
            )
            
        # Check if order is already cancelled
        if order.get("status") == "cancelled":
            logger.warning(f"Failed to cancel order {order_id}: Order already cancelled")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Order {order_id} is already cancelled",
            )
            
        # If account_id is provided, check if order belongs to this account
        if account_id and order.get("account_id") != account_id:
            logger.warning(f"Unauthorized attempt to cancel order {order_id} from account {account_id}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Unauthorized - order does not belong to this account",
            )
        
        # Attempt to cancel the order
        success, message = matching_engine.cancel_order(order_id, account_id)
        
        if not success:
            logger.warning(f"Failed to cancel order {order_id}: {message}")
            
            # Determine appropriate error code
            if "not found" in message.lower():
                status_code = status.HTTP_404_NOT_FOUND
            elif "already cancelled" in message.lower():
                status_code = status.HTTP_400_BAD_REQUEST
            else:
                status_code = status.HTTP_500_INTERNAL_SERVER_ERROR
                
            raise HTTPException(
                status_code=status_code,
                detail=message,
            )
            
        return {
            "success": True,
            "message": f"Order {order_id} cancelled successfully",
        }
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        # Log unexpected errors and raise a generic error
        logger.error(f"Error cancelling order {order_id}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cancel order: {str(e)}",
        ) 
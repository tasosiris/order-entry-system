from fastapi import APIRouter, Depends, HTTPException
from fastapi.background import BackgroundTasks
import time
from app.redis_client import RedisClient
from app.utils import get_redis_client
from app.utils import logger
from app.api.accounts_router import accounts_router

router = APIRouter()

@router.post("/orders/{order_id}/edit")
async def edit_order(
    order_id: str,
    order_data: dict,
    background_tasks: BackgroundTasks,
    redis_client: RedisClient = Depends(get_redis_client)
):
    """Edit an existing order"""
    try:
        # Get the original order
        order = await redis_client.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Update the order with new values
        order.update({
            "price": float(order_data.get("price", order["price"])),
            "quantity": int(order_data.get("quantity", order["quantity"])),
            "updated_at": time.time()
        })
        
        # Save the updated order back to Redis
        success = await redis_client.update_order(order_id, order)
        
        # Update the order in the order book
        background_tasks.add_task(update_order_in_book, order_id, order, redis_client)
        
        return {"success": success, "order": order}
    except Exception as e:
        logger.error(f"Error editing order {order_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error editing order: {str(e)}")

# Add the same endpoint for the accounts_router
@accounts_router.post("/orders/{order_id}/edit")
async def edit_account_order(
    order_id: str,
    order_data: dict,
    background_tasks: BackgroundTasks,
    redis_client: RedisClient = Depends(get_redis_client)
):
    """Edit an existing order through the accounts API"""
    try:
        # Get the original order
        order = await redis_client.get_order(order_id)
        if not order:
            raise HTTPException(status_code=404, detail=f"Order {order_id} not found")
        
        # Update the order with new values
        order.update({
            "price": float(order_data.get("price", order["price"])),
            "quantity": int(order_data.get("quantity", order["quantity"])),
            "updated_at": time.time()
        })
        
        # Save the updated order back to Redis
        success = await redis_client.update_order(order_id, order)
        
        # Update the order in the order book
        background_tasks.add_task(update_order_in_book, order_id, order, redis_client)
        
        return {"success": success, "order": order}
    except Exception as e:
        logger.error(f"Error editing order {order_id} via accounts API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error editing order: {str(e)}")

# Helper function to update order in the order book
async def update_order_in_book(order_id, updated_order, redis_client):
    try:
        logger.info(f"Updating order {order_id} in order book")
        
        # First remove the old order from the book
        logger.info(f"Removing order {order_id} from order book")
        remove_result = await redis_client.remove_order_from_book(order_id)
        logger.info(f"Removal result: {remove_result}")
        
        # Then add the updated order back to the book if it's still open
        if updated_order["status"] in ("open", "partially_filled"):
            logger.info(f"Adding updated order {order_id} back to order book with price={updated_order.get('price')}, quantity={updated_order.get('quantity')}")
            add_result = await redis_client.add_order_to_book(updated_order)
            logger.info(f"Add result: {add_result}")
        else:
            logger.info(f"Not adding order {order_id} back to book because status is {updated_order.get('status')}")
    except Exception as e:
        logger.error(f"Error updating order in book: {str(e)}") 
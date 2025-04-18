"""
Account Management API

This module provides API endpoints for managing trading accounts and accessing account information.
"""

from fastapi import APIRouter, HTTPException, Depends, Query, Body, Path, Form, status
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import logging
import uuid
import time
import json
from datetime import datetime
import asyncio

from app.accounts import account_manager
from app.matching_engine import matching_engine, ORDERS_KEY
from app.redis_client import redis_client

# Configure logging
logger = logging.getLogger("oes.accounts")

# Create router
accounts_router = APIRouter(
    prefix="/api/accounts",
    tags=["accounts"],
)

# Pydantic models for request/response validation
class AccountCreate(BaseModel):
    name: str = Field(..., min_length=1, description="Account name")
    initial_balance: float = Field(..., gt=0, description="Initial account balance")
    account_type: str = Field("standard", description="Account type")
    risk_level: str = Field("medium", description="Risk tolerance level")

class AccountUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, description="Account name")
    balance: Optional[float] = Field(None, ge=0, description="Account balance")
    account_type: Optional[str] = Field(None, description="Account type")
    risk_level: Optional[str] = Field(None, description="Risk tolerance level")
    active: Optional[bool] = Field(None, description="Account active status")

class TransactionCreate(BaseModel):
    amount: float = Field(..., description="Transaction amount")
    transaction_type: str = Field(..., description="Transaction type (deposit, withdrawal, adjustment)")
    description: Optional[str] = Field(None, description="Transaction description")

class OrderCreate(BaseModel):
    symbol: str = Field(..., description="Trading symbol")
    type: str = Field(..., description="Order side (buy/sell)")
    price: float = Field(0.0, description="Order price (0 for market orders)")
    quantity: int = Field(..., gt=0, description="Order quantity")
    asset_type: str = "stocks"
    tif: str = "day"
    order_type: str = "market"
    internal: bool = True
    status: Optional[str] = "open"

@accounts_router.get("/")
async def get_all_accounts() -> List[Dict[str, Any]]:
    """Get all trading accounts."""
    accounts = account_manager.get_all_accounts()
    return [account.to_dict() for account in accounts]

@accounts_router.post("/")
async def create_account(account_data: AccountCreate) -> Dict[str, Any]:
    """Create a new trading account."""
    account = account_manager.create_account(
        name=account_data.name,
        initial_balance=account_data.initial_balance,
        account_type=account_data.account_type,
        risk_level=account_data.risk_level
    )
    return account.to_dict()

@accounts_router.get("/{account_id}")
async def get_account(account_id: str) -> Dict[str, Any]:
    """Get a specific account by ID."""
    account = account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    return account.to_dict()

@accounts_router.put("/{account_id}")
async def update_account(account_id: str, account_data: AccountUpdate) -> Dict[str, Any]:
    """Update an existing account."""
    account = account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    # Update allowed fields
    if account_data.name is not None:
        account.name = account_data.name
    
    if account_data.balance is not None:
        account_manager.update_account_balance(account_id, account_data.balance)
    
    if account_data.account_type is not None:
        account.account_type = account_data.account_type
    
    if account_data.risk_level is not None:
        account.risk_level = account_data.risk_level
    
    if account_data.active is not None:
        account.active = account_data.active
    
    # Save the updated account
    account_manager._save_account(account)
    
    return account.to_dict()

@accounts_router.get("/{account_id}/transactions")
async def get_account_transactions(account_id: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Get transactions for an account."""
    account = account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return account_manager.get_account_transactions(account_id, limit)

@accounts_router.post("/{account_id}/transactions")
async def create_transaction(account_id: str, transaction: TransactionCreate) -> Dict[str, Any]:
    """Create a new transaction for an account."""
    account = account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    # Perform the transaction
    if transaction.transaction_type in ["deposit", "adjustment"]:
        success = account_manager.adjust_account_balance(
            account_id=account_id,
            amount=transaction.amount,
            transaction_type=transaction.transaction_type,
            description=transaction.description or f"{transaction.transaction_type.capitalize()} transaction"
        )
    elif transaction.transaction_type == "withdrawal":
        success = account_manager.adjust_account_balance(
            account_id=account_id,
            amount=-abs(transaction.amount),  # Ensure negative for withdrawals
            transaction_type="withdrawal",
            description=transaction.description or "Withdrawal transaction"
        )
    else:
        raise HTTPException(status_code=400, detail=f"Invalid transaction type: {transaction.transaction_type}")
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to process transaction")
    
    # Get the latest account data
    updated_account = account_manager.get_account(account_id)
    if not updated_account:
        raise HTTPException(status_code=500, detail="Failed to retrieve updated account")
    
    return {"status": "success", "account": updated_account.to_dict()}

@accounts_router.get("/{account_id}/positions")
async def get_account_positions(account_id: str) -> List[Dict[str, Any]]:
    """Get all positions for an account."""
    account = account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    return account_manager.get_all_positions(account_id)

@accounts_router.get("/{account_id}/orders", response_model=List[Dict[str, Any]])
async def get_account_orders(account_id: str):
    """Get all orders for an account."""
    try:
        # Verify the account exists
        account = account_manager.get_account(account_id)
        if not account:
            logger.error(f"Account not found: {account_id}")
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Get ALL orders for the account, not just active ones
        orders = matching_engine.get_account_orders(account_id)
        
        # Log for debugging
        logger.info(f"Retrieved {len(orders)} orders for account {account_id}")
        
        return orders
    except Exception as e:
        logger.error(f"Error fetching orders: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching orders: {str(e)}")

@accounts_router.post("/{account_id}/orders/{order_id}/cancel", response_model=Dict[str, Any])
async def cancel_account_order(account_id: str, order_id: str):
    """Cancel an order for a specific account."""
    try:
        # Verify the account exists
        account = account_manager.get_account(account_id)
        if not account:
            logger.error(f"Account not found: {account_id}")
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Attempt to cancel the order
        success, message = matching_engine.cancel_order(order_id, account_id)
        
        if not success:
            logger.warning(f"Failed to cancel order {order_id}: {message}")
            raise HTTPException(status_code=400, detail=message)
        
        logger.info(f"Order {order_id} cancelled successfully for account {account_id}")
        
        return {
            "success": True,
            "message": "Order cancelled successfully",
            "order_id": order_id
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling order: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error cancelling order: {str(e)}")

@accounts_router.get("/orders/all")
async def get_all_accounts_orders() -> List[Dict[str, Any]]:
    """Get all orders from all accounts including filled orders."""
    try:
        # Use the method to get all orders, not just active ones
        all_orders = matching_engine.get_all_orders()
        logger.info(f"Found {len(all_orders)} orders across all accounts")
        return all_orders
    except Exception as e:
        logger.error(f"Error fetching all orders: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching orders: {str(e)}")

@accounts_router.post("/{account_id}/orders")
async def create_order(account_id: str, order: OrderCreate) -> Dict[str, Any]:
    """Create a new order for an account using reliable storage."""
    # Log the incoming order data for debugging
    logger.info(f"Creating new order for account {account_id}: {order.dict()}")
    
    account = account_manager.get_account(account_id)
    if not account:
        logger.error(f"Account not found: {account_id}")
        raise HTTPException(status_code=404, detail="Account not found")
    
    # Prepare order data
    order_data = order.dict()
    order_data["account_id"] = account_id
    
    try:
        # Submit the order
        result = await matching_engine.submit_order(order_data)
        
        if result.get("status") == "rejected":
            logger.error(f"Order rejected: {result.get('reject_reason', 'Unknown reason')}")
            raise HTTPException(
                status_code=400, 
                detail=f"Order rejected: {result.get('reject_reason', 'Unknown reason')}"
            )
        
        # Get the new order ID
        order_id = result.get("id")
        
        # Verify the order exists in Redis
        stored_order = matching_engine.get_order(order_id)
        if not stored_order:
            # Backup: Check if we should store it directly in Redis as fallback
            logger.warning(f"Order {order_id} not found in Redis after creation, attempting direct storage")
            
            # Set up a complete order directly
            order_data["id"] = order_id
            order_data["timestamp"] = time.time()
            order_data["status"] = "open"
            
            # Store order directly in Redis
            redis_client.set(f"oes:order:{order_id}", json.dumps(order_data))
            
            # Add to orders collection
            redis_client.sadd("oes:orders:all", order_id)
            
            # Add to account index
            redis_client.sadd(f"oes:account:{account_id}:orders", order_id)
            
            # Add to symbol index
            redis_client.sadd(f"oes:symbol:{order_data['symbol']}:orders", order_id)
            
            logger.info(f"Order {order_id} stored directly in Redis as fallback")
            return order_data
        else:
            logger.info(f"Order {order_id} successfully verified in Redis")
        
        return result
    except HTTPException:
        raise  # Re-raise HTTP exceptions
    except Exception as e:
        logger.error(f"Error creating order: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating order: {str(e)}")

@accounts_router.delete("/{account_id}/orders/{order_id}")
async def cancel_order(account_id: str, order_id: str) -> Dict[str, Any]:
    """Cancel an open order."""
    account = account_manager.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="Account not found")
    
    success, message = matching_engine.cancel_order(order_id, account_id)
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    return {"status": "success", "message": message}

@accounts_router.get("/debug/orders/{order_id}")
async def debug_order(order_id: str):
    """Debug endpoint for checking order data directly."""
    try:
        # Get the order directly from Redis
        order = matching_engine.get_order(order_id)
        if not order:
            return {"error": f"Order {order_id} not found in database"}
        
        # Check if order appears in account orders
        account_id = order.get("account_id")
        if account_id:
            account_orders = matching_engine.get_account_orders(account_id)
            account_order_ids = [o.get("id") for o in account_orders]
            order_in_account = order_id in account_order_ids
        else:
            order_in_account = False
            
        # Check if order appears in symbol orders
        symbol = order.get("symbol")
        if symbol:
            symbol_orders_key = f"oes:symbol:{symbol}:orders"
            symbol_order_ids = matching_engine.redis.smembers(symbol_orders_key)
            order_in_symbol = order_id in symbol_order_ids
        else:
            order_in_symbol = False
            
        return {
            "order": order,
            "order_in_account_list": order_in_account,
            "order_in_symbol_list": order_in_symbol,
            "account_id": account_id,
            "symbol": symbol,
            "status": order.get("status")
        }
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}", exc_info=True)
        return {"error": str(e)}

@accounts_router.get("/debug/accounts/{account_id}/orders")
async def debug_account_orders(account_id: str):
    """Debug endpoint for checking all orders for an account."""
    try:
        # Get account orders from Redis set
        account_orders_key = f"oes:account:{account_id}:orders"
        order_ids = matching_engine.redis.smembers(account_orders_key)
        
        # Get actual order data
        orders = []
        for order_id in order_ids:
            order = matching_engine.get_order(order_id)
            if order:
                orders.append(order)
                
        # Get account orders through normal function
        normal_orders = matching_engine.get_account_orders(account_id)
        
        return {
            "order_ids_in_set": list(order_ids),
            "order_count_in_set": len(order_ids),
            "orders_fetched_directly": orders,
            "orders_fetched_normally": normal_orders,
            "account_id": account_id
        }
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}", exc_info=True)
        return {"error": str(e)}

@accounts_router.post("/{account_id}/orders/direct")
async def create_order_direct(account_id: str, order: OrderCreate) -> Dict[str, Any]:
    """Create a new order with direct Redis storage for reliability."""
    # Log the incoming order data for debugging
    logger.info(f"Creating order directly for account {account_id}: {order.dict()}")
    
    try:
        account = account_manager.get_account(account_id)
        if not account:
            logger.error(f"Account not found: {account_id}")
            raise HTTPException(status_code=404, detail="Account not found")
        
        # Prepare order data
        order_data = order.dict()
        order_data["account_id"] = account_id
        
        # Handle market orders - we need to set price to 0 explicitly
        if order_data.get("order_type") == "market":
            logger.info(f"Processing market order for {order_data.get('symbol')}")
            order_data["price"] = 0.0
            
        # Check if this is a valid symbol
        if not order_data.get("symbol"):
            logger.error("Missing symbol in order data")
            raise HTTPException(status_code=400, detail="Symbol is required")
            
        # Generate a unique order ID
        order_id = f"order-{uuid.uuid4()}"
        order_data["id"] = order_id
        order_data["order_id"] = order_id
        
        # Add timestamp
        timestamp = time.time()
        order_data["timestamp"] = timestamp
        order_data["created_at"] = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        
        # Use provided status or default to 'open'
        if 'status' not in order_data:
            order_data["status"] = "open"
            
        # If status is filled or cancelled, add closed_at timestamp
        if order_data["status"] in ['filled', 'cancelled']:
            order_data["closed_at"] = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
        
        # Set filled_quantity to 0 for new orders
        if order_data["status"] == "open":
            order_data["filled_quantity"] = 0
        
        # Ensure internal_match field is set
        if 'internal_match' not in order_data:
            # Check if internal field exists
            if 'internal' in order_data:
                order_data['internal_match'] = str(order_data['internal'])
            else:
                # Default to 'False'
                order_data['internal_match'] = 'False'
        else:
            # Make sure it's a string
            order_data['internal_match'] = str(order_data['internal_match'])
            
        # Directly store the order in Redis
        try:
            # Serialize the order to JSON
            order_json = json.dumps(order_data)
            
            # Store the order
            redis_client.set(f"oes:order:{order_id}", order_json)
            
            # Add to orders collection
            redis_client.sadd("oes:orders:all", order_id)
            
            # Add to account index
            redis_client.sadd(f"oes:account:{account_id}:orders", order_id)
            
            # Add to symbol index
            redis_client.sadd(f"oes:symbol:{order_data['symbol']}:orders", order_id)
            
            # Add to the matching engine's key for all orders
            redis_client.sadd(ORDERS_KEY, order_id)
            
            logger.info(f"Order {order_id} successfully stored directly in Redis with status: {order_data['status']}")
            
            # Verify the order was stored
            stored_order = redis_client.get(f"oes:order:{order_id}")
            if not stored_order:
                logger.error(f"Failed to verify order {order_id} in Redis")
                raise HTTPException(status_code=500, detail="Failed to store order in database")
            else:
                logger.info(f"Order {order_id} verified in Redis")
            
            # Now pass the order to the matching engine for processing
            if order_data.get("order_type") == "market":
                # For market orders, we want to try to match immediately
                asyncio.create_task(matching_engine.process_market_order(order_id))
                
            return order_data
            
        except Exception as e:
            logger.error(f"Error storing order directly: {str(e)}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Error storing order: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating order: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error creating order: {str(e)}")

@accounts_router.get("/debug/all-orders")
async def debug_all_orders():
    """Debug endpoint for checking all orders in the system."""
    try:
        # Get all order IDs from the global orders set
        all_order_ids = matching_engine.redis.smembers(ORDERS_KEY)
        
        # Get all orders directly from Redis
        all_orders = []
        for order_id in all_order_ids:
            order_key = f"oes:order:{order_id}"
            order_json = matching_engine.redis.get(order_key)
            if order_json:
                try:
                    order = json.loads(order_json)
                    all_orders.append(order)
                except Exception as e:
                    logger.error(f"Error parsing order JSON for {order_id}: {e}")
        
        # Get orders using the matching engine method
        engine_orders = matching_engine.get_all_orders()
        
        # Count orders by status
        status_counts = {}
        for order in all_orders:
            status = order.get("status", "unknown")
            if status not in status_counts:
                status_counts[status] = 0
            status_counts[status] += 1
        
        return {
            "total_order_ids": len(all_order_ids),
            "total_orders_direct": len(all_orders),
            "total_orders_engine": len(engine_orders),
            "status_counts": status_counts,
            "all_orders": all_orders
        }
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}", exc_info=True)
        return {"error": str(e)} 
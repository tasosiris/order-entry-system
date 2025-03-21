"""
Order Book Implementation

This module implements a high-performance order book using Redis sorted sets for
ultra-low latency trading operations. It supports both regular order matching
and dark pool (internal) matching functionality.

Key Features:
- Price-time priority ordering
- Dark pool support
- Redis-based implementation for performance
- Comprehensive filtering and depth control
- Risk management integration

The order book uses negative prices for buy orders to achieve descending order,
while sell orders use positive prices for ascending order. This enables efficient
price-time priority matching.
"""

# Standard library imports
import uuid
import time
import json
import asyncio
from typing import Dict, Any, List, Optional, Tuple, Literal

# Application-specific imports
from .redis_client import (
    get_redis_client, 
    match_orders, 
    BUY_ORDERS_KEY, 
    SELL_ORDERS_KEY, 
    TRADES_KEY,
    INTERNAL_BUY_ORDERS_KEY, 
    INTERNAL_SELL_ORDERS_KEY,
    INTERNAL_TRADES_KEY,
    DARK_POOL_ENABLED
)
from .risk_management import risk_manager

class OrderBook:
    """
    High-performance order book implementation using Redis sorted sets.
    
    This class provides the core trading functionality, including:
    - Order submission and validation
    - Price-time priority matching
    - Dark pool support
    - Order book state management
    - Trade execution tracking
    
    The implementation uses Redis sorted sets for efficient order storage and retrieval:
    - Buy orders use negative prices for descending order (highest first)
    - Sell orders use positive prices for ascending order (lowest first)
    - Timestamps are incorporated into scores for precise ordering
    
    Attributes:
        redis: Redis client instance for database operations
    """
    
    def __init__(self):
        """Initialize the order book with a Redis client connection."""
        self.redis = get_redis_client()
        
    async def submit_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit an order to the order book and potentially match it.
        
        This method:
        1. Validates the order against risk parameters
        2. Assigns a unique ID if not present
        3. Stores the order in Redis with a score based on price-time priority
        4. Attempts to match the order against existing orders
        
        Args:
            order_data: Order information including:
                - type: 'buy' or 'sell'
                - symbol: Asset symbol (e.g., 'BTC-USD')
                - price: Price per unit as a float
                - quantity: Amount to buy/sell as a float
                - internal: Whether to route to dark pool (optional)
                
        Returns:
            Dict with 'status' ('accepted' or 'rejected') and either:
                - 'order_id': The ID of the accepted order
                - 'reason': The reason for rejection
        """
        # Validate the order using risk management rules
        is_valid, reason = risk_manager.validate_order(order_data)
        if not is_valid:
            return {"status": "rejected", "reason": reason}
        
        # Assign a unique ID if not present
        if "order_id" not in order_data:
            order_data["order_id"] = str(uuid.uuid4())
            
        # Add timestamp for order prioritization
        order_data["timestamp"] = time.time()
        
        # Determine if this is a dark pool order (internal routing)
        is_internal = order_data.get("internal", False)
        
        # Determine price score for sorted set
        # For buy orders: use negative price for descending sort (higher bids first)
        # For sell orders: use positive price for ascending sort (lower asks first)
        order_type = order_data["type"].lower()
        price = float(order_data["price"])
        timestamp_fraction = order_data["timestamp"] % 1
        
        # Calculate score - includes tiny fraction of timestamp for tie-breaking
        if order_type == "buy":
            # Negate price for descending sort, add timestamp for tiebreaking
            score = -1 * (price + (timestamp_fraction / 1000000))
            orders_key = INTERNAL_BUY_ORDERS_KEY if is_internal else BUY_ORDERS_KEY
        else:  # sell
            # Keep price positive for ascending sort, add timestamp for tiebreaking
            score = price + (timestamp_fraction / 1000000)
            orders_key = INTERNAL_SELL_ORDERS_KEY if is_internal else SELL_ORDERS_KEY
            
        # Prepare order for Redis storage
        order_id = order_data["order_id"]
        order_key = f"order:{order_id}"
        
        # Convert all values to strings for Redis storage
        string_order = {k: str(v) for k, v in order_data.items()}
        
        try:
            # Store order in Redis using a pipeline (atomic transaction)
            pipeline = self.redis.pipeline()
            pipeline.hmset(order_key, string_order)  # Store order details
            pipeline.zadd(orders_key, {order_id: score})  # Add to sorted set
            pipeline.execute()
            
            # Run the matching algorithm to find potential matches
            await self.match_orders()
            
            return {"status": "accepted", "order_id": order_id}
        except Exception as e:
            # Log any Redis errors
            print(f"Error storing order in Redis: {e}")
            return {"status": "rejected", "reason": f"Database error: {str(e)}"}
    
    async def match_orders(self) -> List[Dict[str, Any]]:
        """
        Execute the order matching algorithm using the Lua script.
        Enhanced to support Dark Pool matching.
        Returns a list of trades that were executed.
        """
        executed_trades = []
        
        # Try to match orders up to 10 times or until no more matches are found
        for _ in range(10):
            # Execute the Lua script for atomic matching
            # With dark pool keys included and dark pool flag passed as argument
            result = match_orders(
                keys=[
                    BUY_ORDERS_KEY, 
                    SELL_ORDERS_KEY, 
                    TRADES_KEY,
                    INTERNAL_BUY_ORDERS_KEY,
                    INTERNAL_SELL_ORDERS_KEY,
                    INTERNAL_TRADES_KEY
                ],
                args=[1 if DARK_POOL_ENABLED else 0]
            )
            
            if not result:
                break  # No more matches
                
            # Parse the result from Lua script
            # Now includes dark_pool_flag at position 7
            trade_id, buy_id, sell_id, price, quantity, remaining_buy, remaining_sell, dark_pool_flag = result
            
            # Get full trade details
            trade = self.redis.hgetall(f"trade:{trade_id}")
            
            # Log the execution
            risk_manager.log_execution(trade)
            
            executed_trades.append(trade)
            
            # Small delay to prevent CPU hogging
            await asyncio.sleep(0)
            
        return executed_trades
    
    def get_order_book(
        self, 
        depth: int = 10, 
        include_internal: bool = False,
        asset_type: Optional[str] = None,
        symbol: Optional[str] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get the current state of the order book.
        
        Args:
            depth: How many levels to include
            include_internal: Whether to include dark pool orders
            asset_type: Filter by asset type (stocks, futures, options, crypto)
            symbol: Filter by specific symbol
            
        Returns:
            Dict with 'bids' and 'asks' lists
        """
        # Get top buy orders (highest price first)
        buy_orders = self.redis.zrange(BUY_ORDERS_KEY, 0, -1, withscores=True)
        
        # Get top sell orders (lowest price first)
        sell_orders = self.redis.zrange(SELL_ORDERS_KEY, 0, -1, withscores=True)
        
        # If requested, get internal dark pool orders too
        if include_internal:
            internal_buy_orders = self.redis.zrange(INTERNAL_BUY_ORDERS_KEY, 0, -1, withscores=True)
            internal_sell_orders = self.redis.zrange(INTERNAL_SELL_ORDERS_KEY, 0, -1, withscores=True)
            
            # Combine the orders, will sort by order later
            buy_orders.extend(internal_buy_orders)
            sell_orders.extend(internal_sell_orders)
        
        # Convert to full order objects and apply filters
        bids = []
        for order_id, _ in buy_orders:
            order = self.redis.hgetall(f"order:{order_id}")
            if order:
                # Apply asset type filter
                if asset_type and order.get("asset_type", "").lower() != asset_type.lower():
                    continue
                    
                # Apply symbol filter
                if symbol and order.get("symbol", "") != symbol:
                    continue
                    
                # Flag internal orders for display purposes
                if include_internal and order.get("internal", "False") == "True":
                    order["internal_match"] = "True"
                bids.append(order)
                
        # Sort bids by price (descending) and time (ascending)
        bids.sort(key=lambda x: (-float(x["price"]), float(x["timestamp"])))
        
        # Convert to full order objects and apply filters
        asks = []
        for order_id, _ in sell_orders:
            order = self.redis.hgetall(f"order:{order_id}")
            if order:
                # Apply asset type filter
                if asset_type and order.get("asset_type", "").lower() != asset_type.lower():
                    continue
                    
                # Apply symbol filter
                if symbol and order.get("symbol", "") != symbol:
                    continue
                    
                # Flag internal orders for display purposes
                if include_internal and order.get("internal", "False") == "True":
                    order["internal_match"] = "True"
                asks.append(order)
                
        # Sort asks by price (ascending) and time (ascending)
        asks.sort(key=lambda x: (float(x["price"]), float(x["timestamp"])))
        
        # Apply depth limit after filtering and sorting
        return {"bids": bids[:depth], "asks": asks[:depth]}
    
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get details for a specific order."""
        return self.redis.hgetall(f"order:{order_id}")
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order by removing it from the order book."""
        order = self.get_order(order_id)
        if not order:
            return False
        
        # Determine which order set to remove from based on type and internal flag
        order_type = order.get("type", "").lower()
        is_internal = order.get("internal", "False") == "True"
        
        if order_type == "buy":
            orders_key = INTERNAL_BUY_ORDERS_KEY if is_internal else BUY_ORDERS_KEY
        else:  # sell
            orders_key = INTERNAL_SELL_ORDERS_KEY if is_internal else SELL_ORDERS_KEY
        
        try:
            # Add cancel timestamp
            order["cancel_time"] = str(time.time())
            order["status"] = "cancelled"
            
            # Store a copy of the cancelled order
            cancelled_key = f"cancelled:{order_id}"
            
            # Remove order in a transactional manner
            pipeline = self.redis.pipeline()
            # Save the cancelled order
            pipeline.hmset(cancelled_key, order)
            # Add to the cancelled orders set
            pipeline.sadd("cancelled_orders", order_id)
            # Remove from active orders
            pipeline.zrem(orders_key, order_id)
            pipeline.delete(f"order:{order_id}")
            pipeline.execute()
            return True
        except Exception as e:
            print(f"Error cancelling order: {e}")
            return False
    
    def get_recent_trades(self, limit: int = 20, include_internal: bool = False) -> List[Dict[str, Any]]:
        """
        Get recent trade history.
        
        Args:
            limit: Maximum number of trades to return
            include_internal: Whether to include dark pool trades
            
        Returns:
            List of trade objects
        """
        trades = []
        
        # Get external trade IDs
        trade_ids = self.redis.lrange(TRADES_KEY, 0, limit - 1)
        
        # Get internal trade IDs if requested
        if include_internal:
            internal_trade_ids = self.redis.lrange(INTERNAL_TRADES_KEY, 0, limit - 1)
            trade_ids.extend(internal_trade_ids)
            
            # We might have more trades than the limit now, so take the most recent only
            # This assumes timestamp ordering, which is valid for our use case
            if len(trade_ids) > limit:
                # Get full trades to sort by timestamp
                all_trades = []
                for trade_id in trade_ids:
                    trade = self.redis.hgetall(f"trade:{trade_id}")
                    if trade:
                        all_trades.append(trade)
                
                # Sort by timestamp (descending) and take only up to the limit
                all_trades.sort(key=lambda x: float(x.get("timestamp", 0)), reverse=True)
                trades = all_trades[:limit]
                return trades
        
        # Get trade details
        for trade_id in trade_ids:
            trade = self.redis.hgetall(f"trade:{trade_id}")
            if trade:
                trades.append(trade)
                
        return trades
    
    def get_orders_by_status(self, status: Literal["open", "filled", "cancelled"]) -> List[Dict[str, Any]]:
        """
        Get orders by status.
        
        Args:
            status: The status to filter by ("open", "filled", "cancelled")
            
        Returns:
            List of order objects
        """
        # Start latency measurement
        start_time = time.time() * 1000  # Convert to milliseconds
        
        try:
            if status == "open":
                # Open orders are in the active order books
                orders = []
                
                # Get external buy orders
                buy_order_ids = self.redis.zrange(BUY_ORDERS_KEY, 0, -1)
                for order_id in buy_order_ids:
                    order = self.redis.hgetall(f"order:{order_id}")
                    if order:
                        orders.append(order)
                
                # Get external sell orders
                sell_order_ids = self.redis.zrange(SELL_ORDERS_KEY, 0, -1)
                for order_id in sell_order_ids:
                    order = self.redis.hgetall(f"order:{order_id}")
                    if order:
                        orders.append(order)
                        
                # Get internal buy orders
                internal_buy_order_ids = self.redis.zrange(INTERNAL_BUY_ORDERS_KEY, 0, -1)
                for order_id in internal_buy_order_ids:
                    order = self.redis.hgetall(f"order:{order_id}")
                    if order:
                        orders.append(order)
                
                # Get internal sell orders
                internal_sell_order_ids = self.redis.zrange(INTERNAL_SELL_ORDERS_KEY, 0, -1)
                for order_id in internal_sell_order_ids:
                    order = self.redis.hgetall(f"order:{order_id}")
                    if order:
                        orders.append(order)
                        
                result = orders
            elif status == "filled":
                # Look up by trades to find filled orders
                filled_orders = []
                
                # Get all trades (both external and internal)
                trade_ids = self.redis.lrange(TRADES_KEY, 0, -1)
                trade_ids.extend(self.redis.lrange(INTERNAL_TRADES_KEY, 0, -1))
                
                processed_order_ids = set()
                
                for trade_id in trade_ids:
                    trade = self.redis.hgetall(f"trade:{trade_id}")
                    if not trade:
                        continue
                        
                    # Extract order IDs
                    buy_order_id = trade.get("buy_order_id")
                    sell_order_id = trade.get("sell_order_id")
                    
                    # Check buy order
                    if buy_order_id and buy_order_id not in processed_order_ids:
                        buy_order = self.redis.hgetall(f"order:{buy_order_id}")
                        if buy_order:
                            # Mark as filled and add trade info
                            buy_order["status"] = "filled"
                            buy_order["fill_time"] = trade.get("timestamp", "0")
                            buy_order["fill_price"] = trade.get("price", "0")
                            filled_orders.append(buy_order)
                            processed_order_ids.add(buy_order_id)
                    
                    # Check sell order
                    if sell_order_id and sell_order_id not in processed_order_ids:
                        sell_order = self.redis.hgetall(f"order:{sell_order_id}")
                        if sell_order:
                            # Mark as filled and add trade info
                            sell_order["status"] = "filled"
                            sell_order["fill_time"] = trade.get("timestamp", "0")
                            sell_order["fill_price"] = trade.get("price", "0")
                            filled_orders.append(sell_order)
                            processed_order_ids.add(sell_order_id)
                
                result = filled_orders
            elif status == "cancelled":
                # Get cancelled orders from the cancelled_orders set
                cancelled_orders = []
                
                # Check if the set exists
                if not self.redis.exists("cancelled_orders"):
                    result = []
                else:
                    # Get all cancelled order IDs
                    cancelled_order_ids = self.redis.smembers("cancelled_orders")
                    
                    for order_id in cancelled_order_ids:
                        order = self.redis.hgetall(f"cancelled:{order_id}")
                        if order:
                            cancelled_orders.append(order)
                
                result = cancelled_orders
            else:
                result = []
            
            # End latency measurement and record it
            end_time = time.time() * 1000
            latency = round(end_time - start_time)
            
            # Store the latency measurement in Redis
            try:
                self.redis.lpush("orders_retrieval_latency", latency)
                self.redis.ltrim("orders_retrieval_latency", 0, 49)  # Keep last 50 measurements
            except Exception as e:
                print(f"Error saving order retrieval latency: {e}")
            
            return result
        except Exception as e:
            print(f"Error in get_orders_by_status: {e}")
            # End latency measurement even on error
            end_time = time.time() * 1000
            latency = round(end_time - start_time)
            
            # Store the error latency
            try:
                self.redis.lpush("orders_retrieval_error_latency", latency)
                self.redis.ltrim("orders_retrieval_error_latency", 0, 19)  # Keep last 20 error measurements
            except:
                pass
                
            return []

# Create a singleton instance
order_book = OrderBook() 
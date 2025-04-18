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
- Multiple trading accounts support

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
from datetime import datetime
import logging
import random

# Application-specific imports
from .redis_client import redis_client, BUY_ORDERS_KEY, SELL_ORDERS_KEY, TRADES_KEY, INTERNAL_BUY_ORDERS_KEY, INTERNAL_SELL_ORDERS_KEY, INTERNAL_TRADES_KEY, DARK_POOL_ENABLED
from app.risk_management import risk_manager
from app.accounts import account_manager
from app.matching_engine import matching_engine

# Configure logging
logger = logging.getLogger("oes.orderbook")

class OrderBook:
    """
    High-performance order book implementation using Redis sorted sets.
    
    This class provides the core trading functionality, including:
    - Order submission and validation
    - Price-time priority matching
    - Dark pool support
    - Order book state management
    - Trade execution tracking
    - Multiple trading account support
    """
    
    def __init__(self):
        """Initialize the order book with Redis connection."""
        self.redis = redis_client
        self.account_mgr = account_manager
        self.match_engine = matching_engine
        
        # Seed historical data if needed
        try:
            seed_historical_data()
            seed_internal_book()
        except Exception as e:
            print(f"Warning: Failed to seed order book data: {e}")
    
    async def submit_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit an order to the order book.
        
        Args:
            order_data: Dictionary with order details
            
        Returns:
            The submitted order data with additional fields
        """
        # Generate a unique order ID if not provided
        if 'id' not in order_data and 'order_id' not in order_data:
            order_id = f"order-{uuid.uuid4()}"
            order_data['id'] = order_id
            order_data['order_id'] = order_id
        elif 'id' in order_data and 'order_id' not in order_data:
            order_data['order_id'] = order_data['id']
        elif 'order_id' in order_data and 'id' not in order_data:
            order_data['id'] = order_data['order_id']
            
        # Set order timestamp
        if 'timestamp' not in order_data:
            order_data['timestamp'] = time.time()
            
        # Set order status
        if 'status' not in order_data:
            order_data['status'] = 'open'
            
        # Set filled_quantity to 0
        if 'filled_quantity' not in order_data:
            order_data['filled_quantity'] = '0'
            
        # Set order creation time
        if 'created_at' not in order_data:
            order_data['created_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
        # For incoming orders from external systems or UI, let's handle using the matching engine
        # This allows us to work directly with accounts
        internal = order_data.get('internal', False)
        
        # If the order includes an account_id, we're using the matching engine directly
        if 'account_id' in order_data:
            # Use the matching engine for inter-account trades
            return await self.match_engine.submit_order(order_data)
        
        # Check order with risk management system
        is_approved, risk_reason = risk_manager.check_order(order_data)
        
        if not is_approved:
            # Order rejected by risk management
            order_data['status'] = 'rejected'
            order_data['reject_reason'] = risk_reason
            return order_data
        
        # Select appropriate order book (buy/sell, internal/external)
        if order_data['type'].lower() == 'buy':
            if internal:
                orders_key = INTERNAL_BUY_ORDERS_KEY
            else:
                orders_key = BUY_ORDERS_KEY
            
            # For buy orders, store negative price for proper sorting
            price_score = -float(order_data['price'])
        else:  # sell order
            if internal:
                orders_key = INTERNAL_SELL_ORDERS_KEY
            else:
                orders_key = SELL_ORDERS_KEY
            
            # For sell orders, store positive price for proper sorting
            price_score = float(order_data['price'])
        
        # Store the order in Redis sorted set
        # We serialize the order data to JSON
        self.redis.zadd(orders_key, {json.dumps(order_data): price_score})
        
        # Return the submitted order
        return order_data
    
    async def edit_order(self, order_id: str, updated_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Edit an existing open order.
        
        Args:
            order_id: ID of the order to edit
            updated_data: Dictionary with updated field values
        
        Returns:
            Updated order data or None if order not found
        """
        # First retrieve the existing order
        existing_order = self.get_order(order_id)
        
        if not existing_order:
            return None
        
        if existing_order['status'] != 'open':
            # Can only edit open orders
            return None
        
        # Determine which book this order is in - check for different formats of the field values
        internal = False
        
        # First check if internal_match was provided in the update
        if 'internal_match' in updated_data:
            internal_match_value = str(updated_data['internal_match']).lower()
            internal = internal_match_value in ['true', 'yes', 'y', '1']
        # Otherwise check the existing order
        elif 'internal_match' in existing_order:
            internal_match_value = str(existing_order['internal_match']).lower()
            internal = internal_match_value in ['true', 'yes', 'y', '1']
        # Last resort: check the internal field
        elif 'internal' in existing_order:
            internal_value = str(existing_order['internal']).lower()
            internal = internal_value in ['true', 'yes', 'y', '1']
        
        is_buy = existing_order['type'].lower() == 'buy'
        
        if is_buy:
            old_key = INTERNAL_BUY_ORDERS_KEY if internal else BUY_ORDERS_KEY
        else:
            old_key = INTERNAL_SELL_ORDERS_KEY if internal else SELL_ORDERS_KEY
        
        # Remove the old order
        self.redis.zrem(old_key, json.dumps(existing_order))
        
        # Update fields
        allowed_fields = ['price', 'quantity']
        for field in allowed_fields:
            if field in updated_data:
                existing_order[field] = updated_data[field]
        
        # Mark as edited
        existing_order['edited'] = 'True'
        existing_order['last_edit_time'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Ensure internal_match is set consistently as a string
        existing_order['internal_match'] = str(internal)
        if 'internal' in existing_order:
            existing_order['internal'] = internal  # Keep internal field in sync
        
        # Re-insert with potentially new price
        if is_buy:
            # For buy orders, store negative price for proper sorting
            price_score = -float(existing_order['price'])
        else:
            # For sell orders, store positive price for proper sorting
            price_score = float(existing_order['price'])
        
        # Store the updated order
        self.redis.zadd(old_key, {json.dumps(existing_order): price_score})
        
        # Return the updated order
        return existing_order
    
    async def match_orders(self, include_internal=False):
        """Match orders from the order books based on price-time priority."""
        return await self.redis.match_orders(include_internal)
    
    def get_order_book(
        self, 
        depth: int = 10, 
        include_internal: bool = False,
        asset_type: Optional[str] = None,
        symbol: Optional[str] = None,
        trader_id: Optional[str] = None
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get the current state of the order book.
        
        Args:
            depth: Maximum number of price levels to return
            include_internal: Whether to include internal orders
            asset_type: Filter by asset type (stocks, options, etc.)
            symbol: Filter by symbol
            trader_id: Filter by trader ID
            
        Returns:
            Dictionary with bids and asks lists
        """
        # Get the order book data from Redis
        buy_orders = []
        sell_orders = []
        
        # Get external orders (if not filtering for internal only)
        if not include_internal or include_internal == "both":
            ext_buy_orders = self.redis.zrevrange(BUY_ORDERS_KEY, 0, -1, withscores=True)
            ext_sell_orders = self.redis.zrange(SELL_ORDERS_KEY, 0, -1, withscores=True)
            
            # Process buy orders
            for order_json, price in ext_buy_orders:
                order = json.loads(order_json)
                
                # Apply filters
                if asset_type and order.get('asset_type') != asset_type:
                    continue
                    
                if symbol and order.get('symbol') != symbol:
                    continue
                    
                # Apply trader filter if specified
                if trader_id and order.get('trader_id') != trader_id:
                    continue
                
                # Negate price (it's stored negatively for proper sorting)
                order['price'] = -price
                buy_orders.append(order)
                
                # Respect depth limit if not filtering by trader
                if not trader_id and len(buy_orders) >= depth:
                    break
            
            # Process sell orders
            for order_json, price in ext_sell_orders:
                order = json.loads(order_json)
                
                # Apply filters
                if asset_type and order.get('asset_type') != asset_type:
                    continue
                    
                if symbol and order.get('symbol') != symbol:
                    continue
                    
                # Apply trader filter if specified
                if trader_id and order.get('trader_id') != trader_id:
                    continue
                
                order['price'] = price
                sell_orders.append(order)
                
                # Respect depth limit if not filtering by trader
                if not trader_id and len(sell_orders) >= depth:
                    break
        
        # Include internal orders if requested
        if include_internal or include_internal == "only":
            # Get internal orders
            int_buy_orders = self.redis.zrevrange(INTERNAL_BUY_ORDERS_KEY, 0, -1, withscores=True)
            int_sell_orders = self.redis.zrange(INTERNAL_SELL_ORDERS_KEY, 0, -1, withscores=True)
            
            # Process internal buy orders
            for order_json, price in int_buy_orders:
                order = json.loads(order_json)
                
                # Apply filters
                if asset_type and order.get('asset_type') != asset_type:
                    continue
                    
                if symbol and order.get('symbol') != symbol:
                    continue
                    
                # Apply trader filter if specified
                if trader_id and order.get('trader_id') != trader_id:
                    continue
                
                # Negate price (it's stored negatively for proper sorting)
                order['price'] = -price
                buy_orders.append(order)
                
                # Respect depth limit if not filtering by trader
                if not trader_id and len(buy_orders) >= depth:
                    break
            
            # Process internal sell orders
            for order_json, price in int_sell_orders:
                order = json.loads(order_json)
                
                # Apply filters
                if asset_type and order.get('asset_type') != asset_type:
                    continue
                    
                if symbol and order.get('symbol') != symbol:
                    continue
                    
                # Apply trader filter if specified
                if trader_id and order.get('trader_id') != trader_id:
                    continue
                
                order['price'] = price
                sell_orders.append(order)
                
                # Respect depth limit if not filtering by trader
                if not trader_id and len(sell_orders) >= depth:
                    break
        
        # Sort orders by price and time
        buy_orders.sort(key=lambda x: (-float(x['price']), x['timestamp']))
        sell_orders.sort(key=lambda x: (float(x['price']), x['timestamp']))
        
        return {
            'bids': buy_orders[:depth],
            'asks': sell_orders[:depth]
        }
    
    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get an order by its ID."""
        try:
            # Try to get the order from Redis directly
            redis_key = f"oes:order:{order_id}"
            order_json = self.redis.get(redis_key)
            
            if order_json:
                # Parse the order from JSON
                order = json.loads(order_json)
                
                # Ensure both id fields exist for compatibility
                if 'order_id' not in order and 'id' in order:
                    order['order_id'] = order['id']
                if 'id' not in order and 'order_id' in order:
                    order['id'] = order['order_id']
                
                # Ensure internal_match field is properly set
                if 'internal_match' not in order:
                    # Check if internal field exists and use that value
                    if 'internal' in order:
                        order['internal_match'] = str(order['internal'])
                    else:
                        # Default to 'False' if neither field exists
                        order['internal_match'] = 'False'
                # Ensure internal_match is a string for consistency
                else:
                    order['internal_match'] = str(order['internal_match'])
                    
                return order
            
            # If not found, try the matching engine
            order = self.match_engine.get_order(order_id)
            
            # If we got an order from the matching engine, ensure internal_match is present
            if order and 'internal_match' not in order:
                # Check if internal field exists and use that value
                if 'internal' in order:
                    order['internal_match'] = str(order['internal'])
                else:
                    # Default to 'False' if neither field exists
                    order['internal_match'] = 'False'
            # Ensure internal_match is a string for consistency
            elif order and 'internal_match' in order:
                order['internal_match'] = str(order['internal_match'])
                
            return order
            
        except Exception as e:
            logger.error(f"Error getting order {order_id}: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: ID of the order to cancel
            
        Returns:
            True if order was found and cancelled, False otherwise
        """
        # Find the order
        order = self.get_order(order_id)
        
        if not order:
            return False
        
        # Determine which order book it belongs to
        is_internal = order.get('internal_match') == 'True'
        is_buy = order.get('type', '').lower() == 'buy'
        
        if is_buy:
            key = INTERNAL_BUY_ORDERS_KEY if is_internal else BUY_ORDERS_KEY
        else:
            key = INTERNAL_SELL_ORDERS_KEY if is_internal else SELL_ORDERS_KEY
        
        # Remove from order book
        result = self.redis.zrem(key, json.dumps(order))
        
        if result:
            # Update order status
            order['status'] = 'cancelled'
            order['cancelled_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Store cancelled order in history
            if is_internal:
                cancelled_key = f"oes:internal:orders:cancelled"
            else:
                cancelled_key = f"oes:orders:cancelled"
                
            self.redis.lpush(cancelled_key, json.dumps(order))
        
        return bool(result)
    
    def get_recent_trades(self, limit: int = 20, include_internal: bool = False) -> List[Dict[str, Any]]:
        """
        Get the most recent trades.
        
        Args:
            limit: Maximum number of trades to return
            include_internal: Whether to include internal trades
            
        Returns:
            List of recent trades
        """
        # Get external trades
        ext_trades_json = self.redis.lrange(TRADES_KEY, 0, limit - 1)
        trades = [json.loads(trade) for trade in ext_trades_json]
        
        # Include internal trades if requested
        if include_internal:
            int_trades_json = self.redis.lrange(INTERNAL_TRADES_KEY, 0, limit - 1)
            int_trades = [json.loads(trade) for trade in int_trades_json]
            
            # Combine and sort by timestamp
            trades.extend(int_trades)
            trades.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
            
            # Respect limit
            trades = trades[:limit]
        
        return trades
    
    def get_orders_by_status(
        self, 
        status: Literal["open", "filled", "cancelled"], 
        internal_only: bool = False,
        trader_id: Optional[str] = None,
        symbol: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get orders by status, with option to filter by trader and symbol.
        
        Args:
            status: Order status to filter by
            internal_only: Whether to include only internal orders
            trader_id: Optional ID of trader to filter by
            symbol: Optional symbol to filter by
            
        Returns:
            List of orders matching the criteria
        """
        result = []
        
        if status == "open":
            # For open orders, check the active order books
            if not internal_only:
                # External books
                ext_buy_orders = self.redis.zrevrange(BUY_ORDERS_KEY, 0, -1)
                ext_sell_orders = self.redis.zrange(SELL_ORDERS_KEY, 0, -1)
                
                for order_json in ext_buy_orders + ext_sell_orders:
                    order = json.loads(order_json)
                    
                    # Apply trader filter if needed
                    if trader_id and order.get('trader_id') != trader_id:
                        continue
                    
                    # Apply symbol filter if needed
                    if symbol and order.get('symbol') != symbol:
                        continue
                    
                    result.append(order)
            
            # Internal books
            int_buy_orders = self.redis.zrevrange(INTERNAL_BUY_ORDERS_KEY, 0, -1)
            int_sell_orders = self.redis.zrange(INTERNAL_SELL_ORDERS_KEY, 0, -1)
            
            for order_json in int_buy_orders + int_sell_orders:
                order = json.loads(order_json)
                
                # Apply trader filter if needed
                if trader_id and order.get('trader_id') != trader_id:
                    continue
                
                # Apply symbol filter if needed
                if symbol and order.get('symbol') != symbol:
                    continue
                
                result.append(order)
        else:
            # For filled and cancelled orders, check the history
            if not internal_only:
                # Check external history
                ext_history_key = f"oes:orders:{status}"
                ext_orders_json = self.redis.lrange(ext_history_key, 0, -1)
                
                for order_json in ext_orders_json:
                    order = json.loads(order_json)
                    
                    # Apply trader filter if needed
                    if trader_id and order.get('trader_id') != trader_id:
                        continue
                    
                    # Apply symbol filter if needed
                    if symbol and order.get('symbol') != symbol:
                        continue
                    
                    result.append(order)
            
            # Check internal history
            int_history_key = f"oes:internal:orders:{status}"
            int_orders_json = self.redis.lrange(int_history_key, 0, -1)
            
            for order_json in int_orders_json:
                order = json.loads(order_json)
                
                # Apply trader filter if needed
                if trader_id and order.get('trader_id') != trader_id:
                    continue
                
                # Apply symbol filter if needed
                if symbol and order.get('symbol') != symbol:
                    continue
                
                result.append(order)
        
        # Sort by timestamp
        result.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        
        return result
    
    def get_order_details(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a specific order.
        
        Args:
            order_id: ID of the order to retrieve
            
        Returns:
            Dictionary with order details or None if not found
        """
        order = self.get_order(order_id)
        
        if not order:
            # Check in history for filled or cancelled orders
            for status in ["filled", "cancelled"]:
                for prefix in ["oes", "oes:internal"]:
                    history_key = f"{prefix}:orders:{status}"
                    orders_json = self.redis.lrange(history_key, 0, -1)
                    
                    for order_json in orders_json:
                        order_data = json.loads(order_json)
                        if order_data.get('id') == order_id:
                            return order_data
        
        return order

def seed_historical_data():
    """
    Seed the order book with initial market data and set up continuous updates.
    """
    try:
        from .redis_client import redis_client
        import time
        import random
        import math
        import asyncio
        from datetime import datetime

        # Sample tickers and their price ranges with volatility settings
        tickers = {
            'AAPL': {'min': 170, 'max': 180, 'volatility': 0.002, 'trend': 0},
            'GOOGL': {'min': 140, 'max': 150, 'volatility': 0.003, 'trend': 0},
            'MSFT': {'min': 380, 'max': 390, 'volatility': 0.0015, 'trend': 0},
            'AMZN': {'min': 175, 'max': 185, 'volatility': 0.0025, 'trend': 0},
            'TSLA': {'min': 180, 'max': 190, 'volatility': 0.004, 'trend': 0}
        }

        def generate_orders(base_price, ticker_data):
            """Generate realistic order book entries around the base price"""
            current_time = int(time.time())
            orders = {'bids': [], 'asks': []}
            
            # Generate spread
            spread = base_price * 0.0005  # 0.05% spread
            bid_start = base_price - spread
            ask_start = base_price + spread
            
            # Generate bids (buy orders)
            for i in range(15):
                price = round(bid_start * (1 - 0.001 * i), 2)  # 0.1% price steps
                quantity = random.randint(10, 1000) * 10
                orders['bids'].append((price, quantity, current_time-i))
            
            # Generate asks (sell orders)
            for i in range(15):
                price = round(ask_start * (1 + 0.001 * i), 2)  # 0.1% price steps
                quantity = random.randint(10, 1000) * 10
                orders['asks'].append((price, quantity, current_time-i))
            
            return orders

        # Initial seeding of order books
        for ticker, data in tickers.items():
            # Set initial price
            mid_price = (data['min'] + data['max']) / 2
            redis_client.set(f"price:{ticker}", str(mid_price))
            
            # Generate and store initial orders
            orders = generate_orders(mid_price, data)
            
            # Update order books
            redis_client.delete(f"order_book:{ticker}:bids")
            redis_client.delete(f"order_book:{ticker}:asks")
            
            for price, quantity, timestamp in orders['bids']:
                redis_client.zadd(
                    f"order_book:{ticker}:bids",
                    {f"{price}:{quantity}:{timestamp}": price}
                )
            
            for price, quantity, timestamp in orders['asks']:
                redis_client.zadd(
                    f"order_book:{ticker}:asks",
                    {f"{price}:{quantity}:{timestamp}": price}
                )

        async def update_prices():
            """Continuously update prices based on random walks with mean reversion"""
            while True:
                for ticker, data in tickers.items():
                    # Update trend with mean reversion
                    data['trend'] = data['trend'] * 0.95 + random.gauss(0, data['volatility'])
                    
                    # Calculate new base price with bounds
                    mid_price = (data['min'] + data['max']) / 2
                    current_price = redis_client.get(f"price:{ticker}")
                    
                    if current_price is None:
                        current_price = mid_price
                    else:
                        current_price = float(current_price)
                    
                    # Apply trend and random walk
                    new_price = current_price * (1 + data['trend'] + random.gauss(0, data['volatility']))
                    
                    # Apply mean reversion
                    if new_price < data['min']:
                        new_price = data['min'] * (1 + random.random() * 0.01)
                    elif new_price > data['max']:
                        new_price = data['max'] * (1 - random.random() * 0.01)
                    
                    # Store new price
                    redis_client.set(f"price:{ticker}", str(new_price))
                    
                    # Generate and store new orders
                    orders = generate_orders(new_price, data)
                    
                    # Update order books
                    redis_client.delete(f"order_book:{ticker}:bids")
                    redis_client.delete(f"order_book:{ticker}:asks")
                    
                    for price, quantity, timestamp in orders['bids']:
                        redis_client.zadd(
                            f"order_book:{ticker}:bids",
                            {f"{price}:{quantity}:{timestamp}": price}
                        )
                    
                    for price, quantity, timestamp in orders['asks']:
                        redis_client.zadd(
                            f"order_book:{ticker}:asks",
                            {f"{price}:{quantity}:{timestamp}": price}
                        )
                
                # Small delay between updates
                await asyncio.sleep(0.1)  # Update every 100ms

        # Get or create event loop
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        # Start the continuous update task
        loop.create_task(update_prices())
        
        return True
    except Exception as e:
        print(f"Error seeding historical data: {str(e)}")
        return False

def seed_internal_book():
    """
    Initialize the internal order book structure without seeding any orders.
    This ensures the internal order book exists but starts empty.
    """
    try:
        from .redis_client import redis_client
        logger.info("Initializing empty internal order book")
        
        # Create empty internal order books for each ticker
        for ticker in ['AAPL', 'GOOGL', 'MSFT', 'AMZN', 'TSLA']:
            # Initialize empty bid/ask books
            redis_client.delete(f"internal_book:{ticker}:bids")
            redis_client.delete(f"internal_book:{ticker}:asks")
        
        logger.info("Internal order book initialized successfully (empty)")
        return True
        
    except Exception as e:
        logger.error(f"Error initializing internal order book: {e}")
        return False

# Create a singleton instance
order_book = OrderBook() 
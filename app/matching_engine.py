"""
Trading Matching Engine

This module implements a high-performance trading matching engine that efficiently
matches orders between different trading accounts. The matching engine follows the
standard price-time priority algorithm and ensures that trades only occur when 
authorized by the risk management system.

Key features:
- Ultra-low latency matching algorithm
- Price-time priority for fair order execution
- Account separation and authorization
- Detailed trade tracking
"""

import time
import json
import logging
import uuid
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime
import asyncio

# Application-specific imports
from app.redis_client import redis_client
from app.accounts import account_manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oes.matching")

# Redis keys
ORDERS_KEY = "oes:orders"
TRADES_KEY = "oes:trades"

class MatchingEngine:
    """
    High-performance trading matching engine.
    
    This class implements the core matching logic for trades between different
    accounts in the system. It ensures that:
    1. Orders are matched according to price-time priority
    2. Accounts only trade when authorized by risk management
    3. Account balances are updated appropriately
    4. All trades are recorded for audit purposes
    """
    
    def __init__(self):
        """Initialize the matching engine."""
        self.redis = redis_client
        self.account_mgr = account_manager
        
    async def submit_order(self, order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Submit an order to the matching engine.
        
        Args:
            order: Order data including symbol, price, quantity, etc.
            
        Returns:
            Updated order with status
        """
        # Ensure order has required fields
        required_fields = ['symbol', 'price', 'quantity', 'type', 'account_id']
        for field in required_fields:
            if field not in order:
                order['status'] = 'rejected'
                order['reject_reason'] = f"Missing required field: {field}"
                return order
        
        # Generate order ID if not provided
        if 'order_id' not in order:
            order['order_id'] = f"order-{uuid.uuid4()}"
            
        # Ensure ID fields are consistent
        if 'id' not in order:
            order['id'] = order['order_id']
        elif 'order_id' not in order:
            order['order_id'] = order['id']
            
        # Set timestamps
        if 'timestamp' not in order:
            order['timestamp'] = time.time()
            
        if 'created_at' not in order:
            order['created_at'] = datetime.fromtimestamp(
                order['timestamp']
            ).strftime("%Y-%m-%d %H:%M:%S")
            
        # Default status is 'open'
        if 'status' not in order:
            order['status'] = 'open'
            
        # Initialize filled_quantity to 0
        if 'filled_quantity' not in order:
            order['filled_quantity'] = '0'
        
        # Ensure internal_match field is properly set
        if 'internal_match' not in order:
            # Check if internal field exists and use that value
            if 'internal' in order:
                order['internal_match'] = str(order['internal'])
            else:
                # Default to 'False' if neither field exists
                order['internal_match'] = 'False'
        else:
            # Ensure internal_match is a string for consistency
            order['internal_match'] = str(order['internal_match'])
            
        # Check if account can trade
        symbol = order['symbol']
        price = float(order['price'])
        quantity = float(order['quantity'])
        order_type = order['type'].lower()  # buy or sell
        account_id = order['account_id']
        
        can_trade, reason = self.account_mgr.can_trade(
            account_id=account_id,
            symbol=symbol,
            order_type=order_type,
            price=price,
            quantity=quantity
        )
        
        if not can_trade:
            order['status'] = 'rejected'
            order['reject_reason'] = reason
            return order
        
        # Store the order in Redis
        order_json = json.dumps(order)
        order_key = f"oes:order:{order['order_id']}"
        self.redis.set(order_key, order_json)
        
        # Add to the all orders collection for quick retrieval
        self.redis.sadd(ORDERS_KEY, order['order_id'])
        
        # Add to account-specific order index
        account_orders_key = f"oes:account:{account_id}:orders"
        self.redis.sadd(account_orders_key, order['order_id'])
        
        # Add to symbol-specific order index
        symbol_orders_key = f"oes:symbol:{symbol}:orders"
        self.redis.sadd(symbol_orders_key, order['order_id'])
        
        # Try to match orders immediately
        trades = await self.match_orders(symbol)
        
        # If order was matched completely, update its status
        if trades:
            for trade in trades:
                if trade['buy_order_id'] == order['order_id'] and float(trade['buy_quantity']) == quantity:
                    order['status'] = 'filled'
                    self.update_order_status(order['order_id'], 'filled')
                    
                if trade['sell_order_id'] == order['order_id'] and float(trade['sell_quantity']) == quantity:
                    order['status'] = 'filled'
                    self.update_order_status(order['order_id'], 'filled')
                    
        return order
    
    def update_order_status(self, order_id: str, status: str) -> bool:
        """Update an order's status in Redis."""
        if not order_id:
            return False
            
        order_key = f"oes:order:{order_id}"
        order_json = self.redis.get(order_key)
        
        if not order_json:
            return False
            
        order = json.loads(order_json)
        order['status'] = status
        
        # Ensure both id fields exist for compatibility
        if 'order_id' not in order and 'id' in order:
            order['order_id'] = order['id']
        if 'id' not in order and 'order_id' in order:
            order['id'] = order['order_id']
        
        if status == 'filled' or status == 'cancelled':
            order['closed_at'] = datetime.now().isoformat()
            
        self.redis.set(order_key, json.dumps(order))
        return True
    
    async def match_orders(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Match buy and sell orders for a specific symbol.
        
        This method now uses a Lua script that runs directly inside Redis
        for improved performance and atomic operations.
        
        Args:
            symbol: Trading symbol to match orders for
            
        Returns:
            List of executed trades
        """
        # Execute order matching using Lua script in Redis
        try:
            # First, clean up any filled orders that might still be in the lists
            await self.force_cleanup_filled_orders()
            
            # Call the Lua script to match orders atomically
            trades = self.redis.match_orders_lua(symbol)
            
            if trades:
                # Log the trades
                logger.info(f"Successfully matched {len(trades)} trades for {symbol} using Lua script")
                
                # Forcefully clean DOM (Document Object Model) / order book immediately
                filled_buy_order_ids = []
                filled_sell_order_ids = []
                affected_symbols = set([symbol])
                affected_accounts = set()
                
                # Process each trade
                for trade in trades:
                    # Extract trade details
                    buy_account_id = trade.get('buy_account_id')
                    sell_account_id = trade.get('sell_account_id')
                    trade_quantity = float(trade.get('buy_quantity', trade.get('quantity', 0)))
                    trade_price = float(trade.get('price'))
                    buy_order_id = trade.get('buy_order_id', trade.get('id', None))
                    sell_order_id = trade.get('sell_order_id', trade.get('id', None))
                    
                    # Add to affected accounts
                    if buy_account_id:
                        affected_accounts.add(buy_account_id)
                    if sell_account_id:
                        affected_accounts.add(sell_account_id)
                    
                    # Track filled order IDs
                    if buy_order_id:
                        filled_buy_order_ids.append(buy_order_id)
                    if sell_order_id:
                        filled_sell_order_ids.append(sell_order_id)
                    
                    # Update account balances
                    if buy_account_id and sell_account_id:
                        self.account_mgr.update_after_trade(
                            buy_account_id=buy_account_id,
                            sell_account_id=sell_account_id,
                            symbol=symbol,
                            quantity=trade_quantity,
                            price=trade_price
                        )
                    
                    # Forcefully mark orders as filled and remove from all collections
                    if buy_order_id:
                        # Update order status in Redis
                        buy_order = self.get_order(buy_order_id)
                        if buy_order:
                            buy_order['status'] = 'filled'
                            buy_order['filled_quantity'] = buy_order['quantity']
                            buy_order['closed_at'] = datetime.now().isoformat()
                            order_key = f"oes:order:{buy_order_id}"
                            self.redis.set(order_key, json.dumps(buy_order))
                            
                        # Immediately remove from all collections
                        self.redis.srem(ORDERS_KEY, buy_order_id)
                        self.redis.srem(f"oes:symbol:{symbol}:orders", buy_order_id)
                        if buy_account_id:
                            self.redis.srem(f"oes:account:{buy_account_id}:orders", buy_order_id)
                        
                        logger.info(f"Forcefully removed filled buy order {buy_order_id} from all collections")
                    
                    if sell_order_id:
                        # Update order status in Redis
                        sell_order = self.get_order(sell_order_id)
                        if sell_order:
                            sell_order['status'] = 'filled'
                            sell_order['filled_quantity'] = sell_order['quantity']
                            sell_order['closed_at'] = datetime.now().isoformat()
                            order_key = f"oes:order:{sell_order_id}"
                            self.redis.set(order_key, json.dumps(sell_order))
                            
                        # Immediately remove from all collections
                        self.redis.srem(ORDERS_KEY, sell_order_id)
                        self.redis.srem(f"oes:symbol:{symbol}:orders", sell_order_id)
                        if sell_account_id:
                            self.redis.srem(f"oes:account:{sell_account_id}:orders", sell_order_id)
                            
                        logger.info(f"Forcefully removed filled sell order {sell_order_id} from all collections")
                    
                    # Create a single notification for the trade
                    trade_notification = {
                        'type': 'trade_executed',
                        'message': f"Order matched! {trade_quantity} {symbol} @ ${trade_price}",
                        'trade_id': trade.get('id', trade.get('trade_id', str(uuid.uuid4()))),
                        'timestamp': time.time(),
                        'symbol': symbol,
                        'price': trade_price,
                        'quantity': trade_quantity,
                        'buy_account_id': buy_account_id,
                        'sell_account_id': sell_account_id,
                        'toast': {  # Include toast data in the trade notification
                            'title': 'Order Matched',
                            'message': f"Order matched! {trade_quantity} {symbol} @ ${trade_price}",
                            'variant': 'success',
                            'duration': 5000
                        }
                    }
                    
                    # Publish to main notifications channel only
                    await self.redis.publish_notification(trade_notification, channel="oes:notifications")
                    
                    # Store in account-specific channels without creating new notifications
                    if buy_account_id:
                        await self.redis.publish_notification(trade_notification, channel=f"oes:account:{buy_account_id}:notifications")
                    if sell_account_id:
                        await self.redis.publish_notification(trade_notification, channel=f"oes:account:{sell_account_id}:notifications")
                
                # Publish order book updates for affected symbols
                for affected_symbol in affected_symbols:
                    self.redis.publish("oes:orderbook_updates", json.dumps({
                        "symbol": affected_symbol,
                        "timestamp": time.time(),
                        "type": "refresh"
                    }))
                
                # Publish account updates for affected accounts
                for account_id in affected_accounts:
                    self.redis.publish(f"oes:account:{account_id}:updates", json.dumps({
                        "type": "orders_updated",
                        "timestamp": time.time()
                    }))
                
                # Ensure order list is refreshed globally
                self.redis.publish("oes:updates", json.dumps({
                    "type": "orders_updated",
                    "timestamp": time.time()
                }))
            
            return trades
        except Exception as e:
            logger.error(f"Error matching orders via Lua script: {e}")
            # Fall back to Python implementation
            logger.info(f"Falling back to Python matching implementation for {symbol}")
            return await self._match_orders_python(symbol)
    
    async def _match_orders_python(self, symbol: str) -> List[Dict[str, Any]]:
        """Match orders for a given symbol using Python implementation."""
        logger.info(f"Using Python fallback to match orders for {symbol}")
        trades = []
        
        try:
            # Get all orders for the symbol
            buy_orders, sell_orders = await self._get_orders_for_symbol(symbol)
            
            # If either buy_orders or sell_orders is empty, return empty trades list
            if not buy_orders or not sell_orders:
                return trades
            
            # Sort buy orders by price (desc) and time (asc)
            buy_orders.sort(key=lambda x: (-float(x['price']), float(x['timestamp'])))
            
            # Sort sell orders by price (asc) and time (asc)
            sell_orders.sort(key=lambda x: (float(x['price']), float(x['timestamp'])))
            
            # Iterate through buy and sell orders to find matches
            for buy_order in buy_orders:
                # Skip if buy order is already filled
                if buy_order['status'] == 'filled':
                    continue
                
                buy_account = buy_order['account_id']
                buy_quantity = float(buy_order['quantity'])
                buy_filled = float(buy_order['filled_quantity'])
                buy_remaining = buy_quantity - buy_filled
                
                for sell_order in sell_orders:
                    # Skip if sell order is already filled
                    if sell_order['status'] == 'filled':
                        continue
                    
                    # Skip if sell order belongs to the same account (prevent self-trading)
                    sell_account = sell_order['account_id']
                    if buy_account == sell_account:
                        continue
                    
                    sell_quantity = float(sell_order['quantity'])
                    sell_filled = float(sell_order['filled_quantity'])
                    sell_remaining = sell_quantity - sell_filled
                    
                    # Check if prices are compatible
                    buy_price = float(buy_order['price'])
                    sell_price = float(sell_order['price'])
                    
                    if buy_price < sell_price:
                        break  # No more matches possible
                    
                    # Match orders
                    match_quantity = min(buy_remaining, sell_remaining)
                    trade_price = sell_price  # Use the earlier order's price
                    
                    if buy_order['timestamp'] < sell_order['timestamp']:
                        trade_price = buy_price
                    
                    # Update filled quantities
                    new_buy_filled = buy_filled + match_quantity
                    new_sell_filled = sell_filled + match_quantity
                    
                    buy_status = 'filled' if new_buy_filled >= buy_quantity else 'partially_filled'
                    sell_status = 'filled' if new_sell_filled >= sell_quantity else 'partially_filled'
                    
                    # Update orders in Redis
                    await self.redis.update_order_field(buy_order['order_id'], 'filled_quantity', str(new_buy_filled))
                    await self.redis.update_order_field(buy_order['order_id'], 'status', buy_status)
                    await self.redis.update_order_field(sell_order['order_id'], 'filled_quantity', str(new_sell_filled))
                    await self.redis.update_order_field(sell_order['order_id'], 'status', sell_status)
                    
                    # Create and record the trade
                    trade = {
                        'trade_id': str(uuid.uuid4()),
                        'symbol': symbol,
                        'buy_order_id': buy_order['order_id'],
                        'sell_order_id': sell_order['order_id'],
                        'buy_account_id': buy_account,
                        'sell_account_id': sell_account,
                        'price': str(trade_price),
                        'quantity': str(match_quantity),
                        'timestamp': str(time.time())
                    }
                    
                    # Record the trade in Redis
                    await self.redis.record_trade(trade)
                    trades.append(trade)
                    
                    # Create a single notification for the trade
                    trade_notification = {
                        'type': 'trade_executed',
                        'message': f"Order matched! {match_quantity} {symbol} @ ${trade_price}",
                        'trade_id': trade['trade_id'],
                        'timestamp': time.time(),
                        'symbol': symbol,
                        'price': trade_price,
                        'quantity': match_quantity,
                        'buy_account_id': buy_account,
                        'sell_account_id': sell_account,
                        'toast': {  # Include toast data in the trade notification
                            'title': 'Order Matched',
                            'message': f"Order matched! {match_quantity} {symbol} @ ${trade_price}",
                            'variant': 'success',
                            'duration': 5000
                        }
                    }
                    
                    # Publish to main notifications channel only
                    await self.redis.publish_notification(trade_notification, channel="oes:notifications")
                    
                    # Store in account-specific channels without creating new notifications
                    if buy_account:
                        await self.redis.publish_notification(trade_notification, channel=f"oes:account:{buy_account}:notifications")
                    if sell_account:
                        await self.redis.publish_notification(trade_notification, channel=f"oes:account:{sell_account}:notifications")
                    
                    # Remove filled orders from the order lists
                    if buy_status == 'filled':
                        await self.redis.srem(f"oes:symbol:{symbol}:orders", buy_order['order_id'])
                    
                    if sell_status == 'filled':
                        await self.redis.srem(f"oes:symbol:{symbol}:orders", sell_order['order_id'])
                    
                    # Update buy order for next iteration
                    buy_filled = new_buy_filled
                    buy_remaining = buy_quantity - buy_filled
                    buy_order['status'] = buy_status
                    buy_order['filled_quantity'] = str(new_buy_filled)
                    
                    # If buy order is filled, move to the next buy order
                    if buy_status == 'filled':
                        break
        
        except Exception as e:
            logger.error(f"Python matching error for {symbol}: {str(e)}")
        
        return trades
    
    def get_account_orders(self, account_id: str) -> List[Dict[str, Any]]:
        """
        Get all orders for an account.
        
        Args:
            account_id: Account ID
            
        Returns:
            List of all orders for the account
        """
        orders = []
        
        # Get all order IDs for this account
        account_orders_key = f"oes:account:{account_id}:orders"
        order_ids = self.redis.smembers(account_orders_key)
        
        if not order_ids:
            logger.info(f"No orders found for account {account_id}")
            return []
        
        # Retrieve each order
        for order_id in order_ids:
            order_key = f"oes:order:{order_id}"
            order_json = self.redis.get(order_key)
            
            if order_json:
                order = json.loads(order_json)
                orders.append(order)
        
        # Sort by timestamp (newest first)
        orders.sort(key=lambda x: float(x.get('timestamp', 0)), reverse=True)
        
        logger.info(f"Retrieved {len(orders)} orders for account {account_id}")
        return orders
    
    def get_order(self, order_id: str) -> Dict[str, Any]:
        """Get an order by its ID.
        
        Args:
            order_id: The ID of the order
            
        Returns:
            The order data or None if not found
        """
        if not order_id:
            return None
            
        try:
            order_key = f"oes:order:{order_id}"
            order_json = self.redis.get(order_key)
            if not order_json:
                return None
            
            order_data = json.loads(order_json)
            
            # Ensure both id fields exist for compatibility
            if 'order_id' not in order_data and 'id' in order_data:
                order_data['order_id'] = order_data['id']
            if 'id' not in order_data and 'order_id' in order_data:
                order_data['id'] = order_data['order_id']
            
            # Ensure internal_match field is properly set
            if 'internal_match' not in order_data:
                # Check if internal field exists and use that value
                if 'internal' in order_data:
                    order_data['internal_match'] = str(order_data['internal'])
                else:
                    # Default to 'False' if neither field exists
                    order_data['internal_match'] = 'False'
            else:
                # Ensure internal_match is a string for consistency
                order_data['internal_match'] = str(order_data['internal_match'])
                
            return order_data
        except Exception as e:
            logger.error(f"Error getting order {order_id}: {str(e)}")
            return None
    
    def cancel_order(self, order_id: str, account_id: str) -> Tuple[bool, str]:
        """
        Cancel an open order.
        
        Args:
            order_id: ID of the order to cancel
            account_id: Account ID (for authorization)
            
        Returns:
            Tuple of (success, message)
        """
        order = self.get_order(order_id)
        
        if not order:
            return False, "Order not found"
            
        # Verify the order belongs to the account
        if order['account_id'] != account_id:
            return False, "Not authorized to cancel this order"
            
        # Check if the order is already closed
        if order['status'] != 'open':
            return False, f"Order cannot be cancelled - status is {order['status']}"
            
        # Update the order status
        order['status'] = 'cancelled'
        order['cancelled_at'] = datetime.now().isoformat()
        
        # Save the updated order
        order_key = f"oes:order:{order_id}"
        self.redis.set(order_key, json.dumps(order))
        
        return True, "Order cancelled successfully"
    
    async def edit_order(self, order_id: str, updated_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Edit an existing open order.
        
        Args:
            order_id: ID of the order to edit
            updated_data: Dictionary with updated field values (price, quantity)
            
        Returns:
            Updated order data or None if order not found or not editable
        """
        try:
            order = self.get_order(order_id)
            
            if not order:
                logger.warning(f"Order not found: {order_id}")
                return None
            
            # Check if order can be edited (only open/partially_filled)
            if order.get('status') not in ['open', 'partially_filled']:
                logger.warning(f"Cannot edit order with status '{order.get('status')}'")
                return None
            
            # Store the original order details for logging
            original_price = order.get('price')
            original_quantity = order.get('quantity')
            
            # Check if we need to update price and/or quantity
            price_changed = ('price' in updated_data and 
                            str(updated_data.get('price')) != str(original_price))
            
            quantity_changed = ('quantity' in updated_data and 
                               str(updated_data.get('quantity')) != str(original_quantity))
            
            # Exit early if nothing changed
            if not price_changed and not quantity_changed:
                logger.info(f"No changes detected for order {order_id}")
                return order
            
            # Update the allowed fields
            for field in ['price', 'quantity']:
                if field in updated_data:
                    order[field] = str(updated_data[field])  # Convert to string for consistency
            
            # Add metadata about the edit
            order['edited'] = True
            order['last_edited_at'] = datetime.now().isoformat()
            
            # First check if internal_match was passed in updated_data
            if 'internal_match' in updated_data:
                order['internal_match'] = str(updated_data['internal_match'])
            # Then check if internal_match already exists in order
            elif 'internal_match' not in order:
                # Check if internal field exists and use that value
                if 'internal' in order:
                    order['internal_match'] = str(order['internal'])
                else:
                    # Default to 'False' if neither field exists (as a string)
                    order['internal_match'] = 'False'
            else:
                # Ensure internal_match is a string for consistency
                order['internal_match'] = str(order['internal_match'])
                
            # If price changed, we need to update the order book
            if price_changed:
                # First remove the order from the order book
                symbol = order.get('symbol')
                order_type = order.get('type', '').lower()
                is_internal = order.get('internal_match') == 'True'
                
                # Determine the book key
                if order_type == 'buy':
                    book_key = INTERNAL_BUY_ORDERS_KEY if is_internal else BUY_ORDERS_KEY
                else:
                    book_key = INTERNAL_SELL_ORDERS_KEY if is_internal else SELL_ORDERS_KEY
                
                # Try to remove old order from the book
                result = await self.redis.remove_order_from_book(order_id)
                logger.info(f"Removed order {order_id} from book: {result}")
            
            # Save the updated order
            order_key = f"oes:order:{order_id}"
            logger.info(f"Saving updated order to Redis key: {order_key}")
            self.redis.set(order_key, json.dumps(order))
            
            # Make sure the order is in the correct collections
            symbol = order.get('symbol')
            account_id = order.get('account_id')
            
            # Add to global orders
            self.redis.sadd(ORDERS_KEY, order_id)
            
            # Add to symbol orders
            if symbol:
                symbol_key = f"oes:symbol:{symbol}:orders"
                self.redis.sadd(symbol_key, order_id)
            
            # Add to account orders
            if account_id:
                account_key = f"oes:account:{account_id}:orders"
                self.redis.sadd(account_key, order_id)
            
            # If price changed, add back to the order book
            if price_changed and symbol:
                # Add it back to the book with the new price
                await self.redis.add_order_to_book(order)
                logger.info(f"Added order {order_id} back to the order book with updated price")
                
                # Notify subscribers of the update
                await self.redis.publish_notification({
                    'type': 'order_updated',
                    'order_id': order_id,
                    'symbol': symbol,
                    'price': order['price'],
                    'quantity': order['quantity'],
                    'account_id': account_id
                })
            
            logger.info(f"Order {order_id} edited: price={original_price}->{order['price']}, quantity={original_quantity}->{order['quantity']}, internal_match={order['internal_match']}")
            
            # Try to match orders after editing
            if symbol:
                logger.info(f"Attempting to match orders for symbol {symbol}")
                # This should be run as a separate task to prevent blocking
                asyncio.create_task(self.match_orders(symbol))
            
            return order
        except Exception as e:
            logger.error(f"Error editing order {order_id}: {str(e)}")
            return None

    async def auto_match_orders(self) -> List[Dict[str, Any]]:
        """
        Automatically match all compatible orders across all symbols.
        This function runs continually to ensure orders are matched as soon as they become compatible.
        
        Returns:
            List of all executed trades
        """
        # We'll delegate to match_all_symbols for a more robust implementation
        return await self.match_all_symbols()
    
    async def match_all_symbols(self) -> List[Dict[str, Any]]:
        """
        Match orders across all symbols.
        This is an alias for auto_match_orders for compatibility with existing code.
        
        Returns:
            List of all executed trades
        """
        all_trades = []
        try:
            # Get all unique symbols
            symbol_pattern = "oes:symbol:*:orders"
            symbol_keys = self.redis.keys(symbol_pattern)
            
            for symbol_key in symbol_keys:
                # Extract symbol from key pattern
                symbol = symbol_key.split(":")[2]
                
                try:
                    # First attempt to use Lua script
                    trades = self.redis.match_orders_lua(symbol)
                    
                    if trades:
                        # Log the trades
                        logger.info(f"Successfully matched {len(trades)} trades for {symbol} using Lua script")
                        
                        # Process each trade
                        for trade in trades:
                            # Extract trade details
                            buy_account_id = trade['buy_account_id']
                            sell_account_id = trade['sell_account_id']
                            trade_quantity = float(trade.get('buy_quantity', trade.get('quantity', 0)))
                            trade_price = float(trade['price'])
                            buy_order_id = trade.get('buy_order_id', trade.get('id', None))
                            sell_order_id = trade.get('sell_order_id', trade.get('id', None))
                            
                            # Update account balances
                            self.account_mgr.update_after_trade(
                                buy_account_id=buy_account_id,
                                sell_account_id=sell_account_id,
                                symbol=symbol,
                                quantity=trade_quantity,
                                price=trade_price
                            )
                            
                            # Get order statuses to check if they're filled
                            buy_order = self.get_order(buy_order_id) if buy_order_id else None
                            sell_order = self.get_order(sell_order_id) if sell_order_id else None
                            
                            # If an order is filled, remove it from the orders collections
                            if buy_order and buy_order.get('status') == 'filled':
                                # Remove from global ORDERS_KEY
                                self.redis.srem(ORDERS_KEY, buy_order_id)
                                # Remove from account-specific orders list
                                self.redis.srem(f"oes:account:{buy_account_id}:orders", buy_order_id)
                                # Remove from symbol-specific orders list (already done in Lua script but double-check)
                                self.redis.srem(f"oes:symbol:{symbol}:orders", buy_order_id)
                                logger.info(f"Removed filled buy order {buy_order_id} from orders lists")
                                
                            if sell_order and sell_order.get('status') == 'filled':
                                # Remove from global ORDERS_KEY
                                self.redis.srem(ORDERS_KEY, sell_order_id)
                                # Remove from account-specific orders list
                                self.redis.srem(f"oes:account:{sell_account_id}:orders", sell_order_id)
                                # Remove from symbol-specific orders list (already done in Lua script but double-check)
                                self.redis.srem(f"oes:symbol:{symbol}:orders", sell_order_id)
                                logger.info(f"Removed filled sell order {sell_order_id} from orders lists")
                            
                        all_trades.extend(trades)
                except Exception as e:
                    logger.error(f"Lua script failed for symbol {symbol}: {e}")
                    
                    # Fall back to Python implementation
                    logger.info(f"Falling back to Python implementation for {symbol}")
                    python_trades = await self._match_orders_python(symbol)
                    all_trades.extend(python_trades)
                    
                    if python_trades:
                        logger.info(f"Successfully matched {len(python_trades)} trades for {symbol} using Python fallback")
        except Exception as e:
            logger.error(f"Error in match_all_symbols: {e}")
            
        return all_trades
        
    async def force_cleanup_filled_orders(self):
        """
        Aggressively clean up any orders that are filled but still in the order lists.
        This is an additional safeguard to ensure the UI stays in sync.
        """
        try:
            cleaned_count = 0
            
            # First pass: Check all symbol pattern keys for filled orders
            symbol_pattern = "oes:symbol:*:orders"
            symbol_keys = self.redis.keys(symbol_pattern)
            
            for symbol_key in symbol_keys:
                symbol = symbol_key.split(":")[2]
                symbol_order_ids = self.redis.smembers(symbol_key)
                
                for order_id in symbol_order_ids:
                    order_key = f"oes:order:{order_id}"
                    order_json = self.redis.get(order_key)
                    
                    if not order_json:
                        # Remove dangling reference
                        self.redis.srem(symbol_key, order_id)
                        logger.info(f"Removed dangling reference to missing order {order_id} from {symbol_key}")
                        cleaned_count += 1
                        continue
                        
                    try:
                        order = json.loads(order_json)
                        
                        # If order is filled or cancelled, remove from symbol list
                        if order.get('status') == 'filled' or order.get('status') == 'cancelled':
                            self.redis.srem(symbol_key, order_id)
                            logger.info(f"Removed filled/cancelled order {order_id} from symbol list {symbol_key}")
                            cleaned_count += 1
                            
                            # Also remove from main orders list and account list
                            self.redis.srem(ORDERS_KEY, order_id)
                            
                            account_id = order.get('account_id')
                            if account_id:
                                self.redis.srem(f"oes:account:{account_id}:orders", order_id)
                    except Exception as e:
                        logger.error(f"Error processing order {order_id} in symbol list: {e}")
                        continue
            
            # Second pass: Check all account pattern keys for filled orders
            account_pattern = "oes:account:*:orders"
            account_keys = self.redis.keys(account_pattern)
            
            for account_key in account_keys:
                account_id = account_key.split(":")[2]
                account_order_ids = self.redis.smembers(account_key)
                
                for order_id in account_order_ids:
                    order_key = f"oes:order:{order_id}"
                    order_json = self.redis.get(order_key)
                    
                    if not order_json:
                        # Remove dangling reference
                        self.redis.srem(account_key, order_id)
                        logger.info(f"Removed dangling reference to missing order {order_id} from {account_key}")
                        cleaned_count += 1
                        continue
                        
                    try:
                        order = json.loads(order_json)
                        
                        # If order is filled or cancelled, remove from account list
                        if order.get('status') == 'filled' or order.get('status') == 'cancelled':
                            self.redis.srem(account_key, order_id)
                            logger.info(f"Removed filled/cancelled order {order_id} from account list {account_key}")
                            cleaned_count += 1
                            
                            # Also remove from main orders list and symbol list
                            self.redis.srem(ORDERS_KEY, order_id)
                            
                            symbol = order.get('symbol')
                            if symbol:
                                self.redis.srem(f"oes:symbol:{symbol}:orders", order_id)
                    except Exception as e:
                        logger.error(f"Error processing order {order_id} in account list: {e}")
                        continue
            
            # Third pass: Check the main orders list
            all_order_ids = self.redis.smembers(ORDERS_KEY)
            if all_order_ids:
                for order_id in all_order_ids:
                    order_key = f"oes:order:{order_id}"
                    order_json = self.redis.get(order_key)
                    
                    if not order_json:
                        # Clean up dangling references
                        self.redis.srem(ORDERS_KEY, order_id)
                        logger.info(f"Removed dangling reference to missing order {order_id} from main orders list")
                        cleaned_count += 1
                        continue
                    
                    try:
                        order = json.loads(order_json)
                        
                        # Double-check if this order is filled or cancelled
                        if order.get('status') == 'filled' or order.get('status') == 'cancelled':
                            # Remove from main orders list
                            self.redis.srem(ORDERS_KEY, order_id)
                            logger.info(f"Removed filled/cancelled order {order_id} from main orders list")
                            cleaned_count += 1
                            
                            # Also ensure it's removed from symbol and account collections
                            symbol = order.get('symbol')
                            if symbol:
                                self.redis.srem(f"oes:symbol:{symbol}:orders", order_id)
                            
                            account_id = order.get('account_id')
                            if account_id:
                                self.redis.srem(f"oes:account:{account_id}:orders", order_id)
                    except Exception as e:
                        logger.error(f"Error processing order {order_id} in main list: {e}")
                        continue
                    
            if cleaned_count > 0:
                logger.info(f"Force-cleaned {cleaned_count} filled/cancelled/missing orders from all lists")
                
        except Exception as e:
            logger.error(f"Error in force_cleanup_filled_orders: {e}")

    async def start_auto_matching(self, interval_seconds=0.05):
        """
        Start the automatic order matching process.
        
        Args:
            interval_seconds: How frequently to run the matching algorithm (default: 0.05s = 50ms)
        """
        logger.info(f"Starting aggressive automatic order matching service (interval: {interval_seconds}s)")
        
        while True:
            try:
                # First, clean up any filled orders that might still be in the lists
                await self.force_cleanup_filled_orders()
                
                # Then try to match new orders
                trades = await self.auto_match_orders()
                if trades:
                    logger.info(f"Auto-matched {len(trades)} trades across all symbols")
                    
                    # Force a more aggressive clean-up of filled orders
                    symbol_pattern = "oes:symbol:*:orders"
                    symbol_keys = self.redis.keys(symbol_pattern)
                    
                    for symbol_key in symbol_keys:
                        symbol = symbol_key.split(":")[2]
                        # Update the order book to refresh UI state
                        self.get_order_book(symbol)
                        
            except Exception as e:
                logger.error(f"Error in auto-matching: {e}")
                
            # Very short wait before next matching cycle
            await asyncio.sleep(interval_seconds)

    def get_order_book(self, symbol: str, depth: int = 10) -> Dict[str, Any]:
        """
        Get the current order book for a symbol.
        
        Args:
            symbol: Trading symbol
            depth: Maximum number of price levels to return
            
        Returns:
            Order book with bids and asks
        """
        # Get all orders for this symbol
        symbol_orders_key = f"oes:symbol:{symbol}:orders"
        order_ids = self.redis.smembers(symbol_orders_key)
        
        # Retrieve and categorize orders
        bids = []
        asks = []
        cleaned_orders = 0
        
        for order_id in order_ids:
            order_key = f"oes:order:{order_id}"
            order_json = self.redis.get(order_key)
            
            if not order_json:
                # Clean up references to missing orders
                self.redis.srem(symbol_orders_key, order_id)
                self.redis.srem(ORDERS_KEY, order_id)
                cleaned_orders += 1
                continue
                
            order = json.loads(order_json)
            
            # Include all orders regardless of status
            if order['type'].lower() == 'buy':
                bids.append(order)
            else:
                asks.append(order)
        
        # Sort bids by price (highest first)
        bids.sort(key=lambda x: float(x['price']), reverse=True)
        
        # Sort asks by price (lowest first)
        asks.sort(key=lambda x: float(x['price']))
        
        # Limit to specified depth
        bids = bids[:depth]
        asks = asks[:depth]
        
        if cleaned_orders > 0:
            logger.info(f"Cleaned up {cleaned_orders} missing orders from symbol {symbol} order book")
            
        return {
            'bids': bids,
            'asks': asks,
            'symbol': symbol,
            'timestamp': time.time()
        }
        
    def get_all_orders(self) -> List[Dict[str, Any]]:
        """
        Get all orders from all accounts regardless of status.
        
        Returns:
            List of all orders
        """
        try:
            # Get all order IDs
            all_order_ids = self.redis.smembers(ORDERS_KEY)
            if not all_order_ids:
                logger.debug("No orders found in Redis")
                return []
            
            all_orders = []
            removed_count = 0
            
            # Retrieve each order
            for order_id in all_order_ids:
                order_key = f"oes:order:{order_id}"
                order_json = self.redis.get(order_key)
                
                if not order_json:
                    # Order reference exists but actual order doesn't - clean up
                    logger.warning(f"Found reference to order {order_id} in ORDERS_KEY but order doesn't exist, removing reference")
                    self.redis.srem(ORDERS_KEY, order_id)
                    removed_count += 1
                    continue
                    
                try:
                    order = json.loads(order_json)
                    # Include all orders in the results regardless of status
                    all_orders.append(order)
                except Exception as e:
                    logger.error(f"Error parsing order JSON for {order_id}: {e}")
                    continue
                
            # Sort by timestamp (newest first)
            all_orders.sort(key=lambda x: float(x.get('timestamp', 0)), reverse=True)
            
            if removed_count > 0:
                logger.info(f"Cleaned up {removed_count} invalid orders from orders lists")
                
            logger.info(f"Retrieved {len(all_orders)} total orders")
            return all_orders
        except Exception as e:
            logger.error(f"Error getting all orders: {e}")
            return []
        
    def get_all_active_orders(self) -> List[Dict[str, Any]]:
        """
        Get all active (open) orders from all accounts.
        
        Returns:
            List of all active orders
        """
        try:
            # Get all orders
            all_orders = self.get_all_orders()
            
            # Filter to only open or partially filled orders
            active_orders = [order for order in all_orders if order.get('status') == 'open' or order.get('status') == 'partially_filled']
            
            # Debug info
            logger.info(f"Retrieved {len(active_orders)} active orders out of {len(all_orders)} total orders")
            if len(all_orders) > len(active_orders):
                logger.info(f"Filtered out {len(all_orders) - len(active_orders)} non-active orders with statuses: {set(order.get('status') for order in all_orders if order.get('status') != 'open' and order.get('status') != 'partially_filled')}")
            
            return active_orders
        except Exception as e:
            logger.error(f"Error getting active orders: {e}")
            return []

    async def _get_orders_for_symbol(self, symbol: str) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Get all buy and sell orders for a given symbol.
        
        Args:
            symbol: The trading symbol
            
        Returns:
            Tuple of (buy_orders, sell_orders)
        """
        buy_orders = []
        sell_orders = []
        
        try:
            # Get all orders for this symbol
            symbol_orders_key = f"oes:symbol:{symbol}:orders"
            order_ids = self.redis.smembers(symbol_orders_key)
            
            for order_id in order_ids:
                order_key = f"oes:order:{order_id}"
                order_json = self.redis.get(order_key)
                
                if not order_json:
                    continue
                
                order = json.loads(order_json)
                
                # Make sure required fields exist
                if 'filled_quantity' not in order:
                    order['filled_quantity'] = '0'
                
                # Add order to appropriate list based on type (include all orders regardless of status)
                if order['type'].lower() == 'buy':
                    buy_orders.append(order)
                elif order['type'].lower() == 'sell':
                    sell_orders.append(order)
            
            logger.info(f"Retrieved {len(buy_orders)} buy orders and {len(sell_orders)} sell orders for {symbol}")
            
        except Exception as e:
            logger.error(f"Error getting orders for symbol {symbol}: {e}")
        
        return buy_orders, sell_orders

    async def process_market_order(self, order_id: str) -> Dict[str, Any]:
        """
        Process a market order by finding the best available price and executing immediately.
        
        Args:
            order_id: The ID of the market order to process
            
        Returns:
            The processed order data
        """
        try:
            # Get the order details
            order_key = f"oes:order:{order_id}"
            order_json = self.redis.get(order_key)
            
            if not order_json:
                logger.error(f"Market order {order_id} not found")
                return None
                
            order = json.loads(order_json)
            
            # Make sure it's a market order
            if order.get('order_type') != 'market':
                logger.warning(f"Order {order_id} is not a market order")
                return order
                
            # Get the symbol and order side
            symbol = order.get('symbol')
            is_buy = order.get('type', '').lower() == 'buy'
            quantity = float(order.get('quantity', 0))
            account_id = order.get('account_id')
            
            if not symbol or not account_id or quantity <= 0:
                logger.error(f"Market order {order_id} is missing required fields: {order}")
                return order
                
            logger.info(f"Processing market order {order_id} for {symbol}: {'BUY' if is_buy else 'SELL'} {quantity}")
            
            # Find matching orders on the opposite side
            opposite_side = 'sell' if is_buy else 'buy'
            
            # Get all orders for this symbol
            all_orders = self.get_all_orders_for_symbol(symbol)
            
            # Filter to get only active orders on the opposite side
            matching_orders = [
                o for o in all_orders 
                if o.get('type', '').lower() == opposite_side and 
                o.get('status', '') == 'open' and
                o.get('account_id') != account_id  # Don't match with own orders
            ]
            
            # For a buy market order, sort by price (ascending)
            # For a sell market order, sort by price (descending)
            if is_buy:
                matching_orders.sort(key=lambda o: float(o.get('price', 0)))
            else:
                matching_orders.sort(key=lambda o: float(o.get('price', 0)), reverse=True)
                
            if not matching_orders:
                logger.warning(f"No matching orders found for market order {order_id}")
                # Update order status to indicate no matches
                order['status'] = 'pending'
                self.redis.set(order_key, json.dumps(order))
                return order
                
            # Execute the market order against the best available price(s)
            remaining_quantity = quantity
            trades = []
            
            for match_order in matching_orders:
                if remaining_quantity <= 0:
                    break
                    
                match_order_id = match_order.get('id')
                match_price = float(match_order.get('price', 0))
                match_quantity = float(match_order.get('quantity', 0))
                match_filled = float(match_order.get('filled_quantity', 0))
                match_available = match_quantity - match_filled
                
                if match_available <= 0:
                    continue
                    
                # Determine the quantity to match
                match_quantity = min(remaining_quantity, match_available)
                
                # Create a trade
                trade = {
                    'id': f"T-{uuid.uuid4()}",
                    'buy_order_id': order_id if is_buy else match_order_id,
                    'sell_order_id': match_order_id if is_buy else order_id,
                    'buy_account_id': account_id if is_buy else match_order.get('account_id'),
                    'sell_account_id': match_order.get('account_id') if is_buy else account_id,
                    'symbol': symbol,
                    'price': match_price,
                    'quantity': match_quantity,
                    'timestamp': time.time()
                }
                
                # Record the trade
                self.redis.set(f"oes:trade:{trade['id']}", json.dumps(trade))
                self.redis.sadd(TRADES_KEY, trade['id'])
                
                # Update the market order
                order['filled_quantity'] = float(order.get('filled_quantity', 0)) + match_quantity
                if float(order['filled_quantity']) >= quantity:
                    order['status'] = 'filled'
                else:
                    order['status'] = 'partially_filled'
                    
                # Set the executed price for the market order
                if 'execution_price' not in order:
                    order['execution_price'] = match_price
                else:
                    # Calculate VWAP if multiple executions
                    prev_exec_qty = float(order['filled_quantity']) - match_quantity
                    prev_exec_price = float(order['execution_price'])
                    new_exec_price = ((prev_exec_price * prev_exec_qty) + (match_price * match_quantity)) / float(order['filled_quantity'])
                    order['execution_price'] = new_exec_price
                
                # Update the matched order
                match_order['filled_quantity'] = float(match_order.get('filled_quantity', 0)) + match_quantity
                if float(match_order['filled_quantity']) >= float(match_order['quantity']):
                    match_order['status'] = 'filled'
                else:
                    match_order['status'] = 'partially_filled'
                    
                # Save updates to Redis
                self.redis.set(order_key, json.dumps(order))
                self.redis.set(f"oes:order:{match_order_id}", json.dumps(match_order))
                
                # Record in trades list
                trades.append(trade)
                
                # Update remaining quantity
                remaining_quantity -= match_quantity
                
                logger.info(f"Market order {order_id} matched with {match_order_id} for {match_quantity} at ${match_price}")
                
                if remaining_quantity <= 0:
                    break
            
            # If there are still remaining shares, update the order status
            if remaining_quantity > 0 and float(order.get('filled_quantity', 0)) > 0:
                order['status'] = 'partially_filled'
                self.redis.set(order_key, json.dumps(order))
            elif remaining_quantity > 0:
                order['status'] = 'pending'  # No matches found
                self.redis.set(order_key, json.dumps(order))
                
            # Return the updated order
            return order
            
        except Exception as e:
            logger.error(f"Error processing market order {order_id}: {e}", exc_info=True)
            return None
            
    def get_all_orders_for_symbol(self, symbol: str) -> List[Dict[str, Any]]:
        """
        Get all orders for a specific symbol.
        
        Args:
            symbol: The trading symbol
            
        Returns:
            List of all orders for the symbol
        """
        try:
            # Get all order IDs for this symbol
            order_ids = self.redis.smembers(f"oes:symbol:{symbol}:orders")
            
            orders = []
            for order_id in order_ids:
                order_json = self.redis.get(f"oes:order:{order_id}")
                if order_json:
                    try:
                        order = json.loads(order_json)
                        orders.append(order)
                    except:
                        continue
                        
            return orders
        except Exception as e:
            logger.error(f"Error getting orders for symbol {symbol}: {e}")
            return []

# Create singleton instance
matching_engine = MatchingEngine() 
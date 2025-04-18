import os
import redis
import logging
from redis.connection import BlockingConnectionPool
from redis.exceptions import ConnectionError
import time
import json
import random
from datetime import datetime
from typing import Optional, List, Dict, Any
import sys
import uuid

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oes.redis")

# Redis connection configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Redis key constants for order books
# External order books (public exchange data)
BUY_ORDERS_KEY = "oes:orders:buy"
SELL_ORDERS_KEY = "oes:orders:sell"
TRADES_KEY = "oes:trades"

# Internal order books (dark pool / hedge fund internal)
INTERNAL_BUY_ORDERS_KEY = "oes:internal:orders:buy"
INTERNAL_SELL_ORDERS_KEY = "oes:internal:orders:sell"
INTERNAL_TRADES_KEY = "oes:internal:trades"

# Feature flags
DARK_POOL_ENABLED = True

# Historical date for external order book
HISTORICAL_DATE = "2023-12-15"

# Top 100 NYSE tickers (imported from market.py)
TOP_100_NYSE_TICKERS = [
    "AAPL", "MSFT", "AMZN", "GOOGL", "META", "TSLA", "NVDA", "BRK.A", "V", "UNH", 
    "WMT", "JPM", "AVGO", "PG", "MA", "JNJ", "XOM", "HD", "CVX", "LLY", 
    "MRK", "PEP", "KO", "ABBV", "COST", "ORCL", "MCD", "BAC", "TMO", "ADBE", 
    "CSCO", "CRM", "PFE", "DIS", "NFLX", "ABT", "VZ", "CMCSA", "AMD", "NKE", 
    "TMUS", "INTC", "INTU", "PM", "WFC", "TXN", "DHR", "UPS", "RTX", "NEE", 
    "LOW", "IBM", "AMGN", "QCOM", "BA", "LIN", "SPGI", "CAT", "GS", "HON", 
    "BLK", "AMAT", "SBUX", "UNP", "ELV", "T", "ISRG", "GE", "PLD", "MS", 
    "MDLZ", "BMY", "MDT", "GILD", "AXP", "DE", "SYK", "CVS", "ADI", "BKNG", 
    "MMC", "VRTX", "TJX", "AMT", "C", "COP", "CI", "REGN", "NOW", "PYPL", 
    "MO", "SO", "LRCX", "PANW", "ZTS", "BSX", "KLAC", "ADP", "SLB", "CB"
]

# Add this near the top of the file, where other Redis keys are defined
MATCH_ORDERS_SCRIPT = """
local symbol = ARGV[1]
local symbol_orders_key = "oes:symbol:" .. symbol .. ":orders"
local main_orders_key = "oes:orders"
local trades_key = "oes:trades"
local executed_trades = {}

-- Get all order IDs for this symbol
local order_ids = redis.call("SMEMBERS", symbol_orders_key)
if #order_ids == 0 then
    return cjson.encode(executed_trades)
end

-- Retrieve and categorize orders
local buy_orders = {}
local sell_orders = {}

for i, order_id in ipairs(order_ids) do
    local order_key = "oes:order:" .. order_id
    local order_json = redis.call("GET", order_key)
    
    if order_json then
        local order = cjson.decode(order_json)
        
        -- Handle field name compatibility - ensure order has order_id field
        if not order.order_id and order.id then
            order.order_id = order.id
        end
        if not order.id and order.order_id then
            order.id = order.order_id
        end
        
        -- Initialize filled_quantity if not present
        if not order.filled_quantity then
            order.filled_quantity = "0"
        end
        
        -- Only consider open orders
        if order.status == "open" or order.status == "partially_filled" then
            if order.type:lower() == "buy" then
                table.insert(buy_orders, order)
            else
                table.insert(sell_orders, order)
            end
        end
    end
end

-- Helper function to sort by price and time
local function sort_buy_orders(a, b)
    if tonumber(a.price) == tonumber(b.price) then
        return tonumber(a.timestamp) < tonumber(b.timestamp)
    end
    return tonumber(a.price) > tonumber(b.price)
end

local function sort_sell_orders(a, b)
    if tonumber(a.price) == tonumber(b.price) then
        return tonumber(a.timestamp) < tonumber(b.timestamp)
    end
    return tonumber(a.price) < tonumber(b.price)
end

-- Sort orders by price and time
table.sort(buy_orders, sort_buy_orders)
table.sort(sell_orders, sort_sell_orders)

-- Match orders
local buy_idx = 1
local sell_idx = 1

while buy_idx <= #buy_orders and sell_idx <= #sell_orders do
    local buy_order = buy_orders[buy_idx]
    local sell_order = sell_orders[sell_idx]
    
    -- Ensure both id fields are set
    local buy_id = buy_order.order_id or buy_order.id
    local sell_id = sell_order.order_id or sell_order.id
    
    local buy_price = tonumber(buy_order.price)
    local sell_price = tonumber(sell_order.price)
    
    -- Check if prices cross (buy >= sell)
    if buy_price < sell_price then
        break  -- No more matches possible
    end
    
    -- Prevent self-trading (same account)
    if buy_order.account_id == sell_order.account_id then
        -- Skip newer order
        if tonumber(buy_order.timestamp) > tonumber(sell_order.timestamp) then
            buy_idx = buy_idx + 1
        else
            sell_idx = sell_idx + 1
        end
    else
        -- Calculate remaining quantities based on filled_quantity
        local buy_quantity = tonumber(buy_order.quantity)
        local sell_quantity = tonumber(sell_order.quantity)
        local buy_filled = tonumber(buy_order.filled_quantity or "0")
        local sell_filled = tonumber(sell_order.filled_quantity or "0")
        local buy_remaining = buy_quantity - buy_filled
        local sell_remaining = sell_quantity - sell_filled
        
        -- Determine trade quantity (min of remaining quantities)
        local trade_quantity = math.min(buy_remaining, sell_remaining)
        
        -- Execute the trade
        local trade_price = sell_price  -- Using sell price for trade
        local timestamp = redis.call("TIME")[1]  -- Current time
        local trade_id = "T-" .. timestamp .. "-" .. buy_id .. "-" .. sell_id
        
        -- Create trade record
        local trade = {
            id = trade_id,
            trade_id = trade_id,
            buy_order_id = buy_id,
            sell_order_id = sell_id,
            buy_account_id = buy_order.account_id,
            sell_account_id = sell_order.account_id,
            price = trade_price,
            quantity = trade_quantity,
            buy_quantity = trade_quantity,
            sell_quantity = trade_quantity,
            symbol = symbol,
            timestamp = tonumber(timestamp),
            created_at = tostring(timestamp)
        }
        
        -- Store the trade
        local trade_key = "oes:trade:" .. trade_id
        redis.call("SET", trade_key, cjson.encode(trade))
        
        -- Add to trades collection
        redis.call("SADD", trades_key, trade_id)
        
        -- Add to account-specific trade indices
        redis.call("SADD", "oes:account:" .. buy_order.account_id .. ":trades", trade_id)
        redis.call("SADD", "oes:account:" .. sell_order.account_id .. ":trades", trade_id)
        
        -- Create notification for the trade
        local notification = {
            type = "trade_executed",
            message = "Order matched! " .. trade_quantity .. " " .. symbol .. " @ $" .. trade_price,
            trade_id = trade_id,
            symbol = symbol,
            price = trade_price,
            quantity = trade_quantity,
            timestamp = tonumber(timestamp)
        }
        
        -- Store in notifications list for each account
        local buyer_notif_key = "oes:notifications:" .. buy_order.account_id
        local seller_notif_key = "oes:notifications:" .. sell_order.account_id
        redis.call("LPUSH", buyer_notif_key, cjson.encode(notification))
        redis.call("LPUSH", seller_notif_key, cjson.encode(notification))
        
        -- Publish to the notification channels - but only once to the main channel
        -- to avoid duplicate notifications
        redis.call("PUBLISH", "oes:notifications", cjson.encode(notification))
        
        -- Account-specific notifications still needed for filtering
        redis.call("PUBLISH", "oes:account:" .. buy_order.account_id .. ":notifications", cjson.encode(notification))
        redis.call("PUBLISH", "oes:account:" .. sell_order.account_id .. ":notifications", cjson.encode(notification))
        
        -- Variables to track if orders should be removed from the order list
        local is_buy_filled = false
        local is_sell_filled = false
        
        -- Update buy order filled quantity and status
        local new_buy_filled = buy_filled + trade_quantity
        if new_buy_filled >= buy_quantity then
            -- Order is fully filled
            buy_order.status = "filled"
            buy_order.filled_quantity = tostring(buy_quantity)
            buy_order.closed_at = tostring(timestamp)
            
            -- Remove filled buy order from all collections
            redis.call("SREM", symbol_orders_key, buy_id)
            redis.call("SREM", main_orders_key, buy_id)
            redis.call("SREM", "oes:account:" .. buy_order.account_id .. ":orders", buy_id)
            
            is_buy_filled = true
            
            buy_idx = buy_idx + 1
        else
            -- Order is partially filled
            buy_order.status = "partially_filled"
            buy_order.filled_quantity = tostring(new_buy_filled)
        end
        redis.call("SET", "oes:order:" .. buy_id, cjson.encode(buy_order))
        
        -- Update sell order filled quantity and status
        local new_sell_filled = sell_filled + trade_quantity
        if new_sell_filled >= sell_quantity then
            -- Order is fully filled
            sell_order.status = "filled"
            sell_order.filled_quantity = tostring(sell_quantity)
            sell_order.closed_at = tostring(timestamp)
            
            -- Remove filled sell order from all collections
            redis.call("SREM", symbol_orders_key, sell_id)
            redis.call("SREM", main_orders_key, sell_id)
            redis.call("SREM", "oes:account:" .. sell_order.account_id .. ":orders", sell_id)
            
            is_sell_filled = true
            
            sell_idx = sell_idx + 1
        else
            -- Order is partially filled
            sell_order.status = "partially_filled"
            sell_order.filled_quantity = tostring(new_sell_filled)
        end
        redis.call("SET", "oes:order:" .. sell_id, cjson.encode(sell_order))
        
        -- Add trade to results
        table.insert(executed_trades, trade)
    end
end

return cjson.encode(executed_trades)
"""

class RedisClient:
    def __init__(self):
        """Initialize Redis client."""
        try:
            self.redis = redis.Redis(
                host=REDIS_HOST,
                port=REDIS_PORT,
                password=REDIS_PASSWORD,
                db=REDIS_DB,
                decode_responses=True
            )
            
            # Register Lua scripts
            self.match_orders_script = self.redis.register_script(MATCH_ORDERS_SCRIPT)
            
            # Test connection
            self.redis.ping()
            logger.info(f"Connected to Redis at {REDIS_HOST}:{REDIS_PORT}")
        except redis.ConnectionError as e:
            logger.error(f"Failed to connect to Redis: {e}")
            sys.exit(1)

    def clear_all_orders(self):
        """Clear all orders from Redis."""
        logger.info("Clearing all orders from Redis")
        # Clear external orders
        self.redis.delete(BUY_ORDERS_KEY)
        self.redis.delete(SELL_ORDERS_KEY)
        
        # Clear internal orders
        self.redis.delete(INTERNAL_BUY_ORDERS_KEY)
        self.redis.delete(INTERNAL_SELL_ORDERS_KEY)
        
        # Clear order history
        self.redis.delete(TRADES_KEY)
        self.redis.delete(INTERNAL_TRADES_KEY)
        
        # Clear any other order-related keys
        for key in self.redis.scan_iter("oes:orders:*"):
            self.redis.delete(key)
        for key in self.redis.scan_iter("oes:internal:orders:*"):
            self.redis.delete(key)
        for key in self.redis.scan_iter("oes:order:*"):
            self.redis.delete(key)
        for key in self.redis.scan_iter("oes:account:*:orders"):
            self.redis.delete(key)
        for key in self.redis.scan_iter("oes:symbol:*:orders"):
            self.redis.delete(key)
        
        logger.info("All orders cleared successfully")

    def ping(self):
        """Ping Redis to check connection."""
        return self.redis.ping()

    def zadd(self, key, mapping):
        """Add to a sorted set."""
        return self.redis.zadd(key, mapping)

    def zrem(self, key, member):
        """Remove from a sorted set."""
        return self.redis.zrem(key, member)

    def zrange(self, key, start, stop, withscores=False):
        """Get range from sorted set."""
        return self.redis.zrange(key, start, stop, withscores=withscores)

    def zrevrange(self, key, start, stop, withscores=False):
        """Get range from sorted set in reverse order."""
        return self.redis.zrevrange(key, start, stop, withscores=withscores)

    def lpush(self, key, value):
        """Push to list."""
        return self.redis.lpush(key, value)

    def lrange(self, key, start, stop):
        """Get range from list."""
        return self.redis.lrange(key, start, stop)

    def delete(self, key):
        """Delete a key."""
        return self.redis.delete(key)

    def keys(self, pattern):
        """Get keys matching pattern."""
        return self.redis.keys(pattern)

    def scan_iter(self, pattern):
        """Scan for keys matching pattern."""
        return self.redis.scan_iter(pattern)

    def hget(self, key, field):
        """Get a field from a hash."""
        return self.redis.hget(key, field)

    def hset(self, key, field, value):
        """Set a field in a hash."""
        return self.redis.hset(key, field, value)

    def hgetall(self, key):
        """Get all fields and values in a hash."""
        return self.redis.hgetall(key)

    def get(self, key: str) -> Optional[str]:
        """Get a string value from Redis."""
        return self.redis.get(key)

    def set(self, key: str, value: str) -> bool:
        """Set a string value in Redis."""
        return self.redis.set(key, value)

    def sadd(self, key: str, member: str) -> int:
        """Add a member to a set."""
        return self.redis.sadd(key, member)

    def srem(self, key: str, member: str) -> int:
        """Remove a member from a set."""
        return self.redis.srem(key, member)

    def smembers(self, key: str) -> set:
        """Get all members in a set."""
        return self.redis.smembers(key)

    async def match_orders(self, include_internal=False):
        """Match orders from the order books based on price-time priority."""
        executed_trades = []
        
        try:
            # Get the best buy and sell orders
            best_buy = self.zrevrange(BUY_ORDERS_KEY, 0, 0, withscores=True)
            best_sell = self.zrange(SELL_ORDERS_KEY, 0, 0, withscores=True)
            
            # If there are matching orders
            if best_buy and best_sell:
                buy_order_json, buy_price_neg = best_buy[0]
                sell_order_json, sell_price = best_sell[0]
                
                # Convert price to actual price (remember buy prices are stored negatively)
                buy_price = -buy_price_neg
                
                # Parse the order JSON
                buy_order = json.loads(buy_order_json)
                sell_order = json.loads(sell_order_json)
                
                # Check if prices cross (buy >= sell)
                if buy_price >= sell_price:
                    # Orders match - execute trade
                    trade_quantity = min(float(buy_order['quantity']), float(sell_order['quantity']))
                    trade_price = sell_price  # Using the sell price for simplicity
                    
                    # Create trade record
                    trade_id = f"T-{int(time.time())}-{buy_order['id']}-{sell_order['id']}"
                    trade = {
                        'id': trade_id,
                        'buy_order_id': buy_order['id'],
                        'sell_order_id': sell_order['id'],
                        'price': trade_price,
                        'quantity': trade_quantity,
                        'timestamp': time.time(),
                        'symbol': buy_order['symbol'],
                        'asset_type': buy_order['asset_type'],
                        'buyer_id': buy_order['trader_id'],
                        'seller_id': sell_order['trader_id'],
                        'internal_match': "False"
                    }
                    
                    # Add to trades list
                    self.lpush(TRADES_KEY, json.dumps(trade))
                    
                    # Update order quantities
                    remaining_buy_qty = float(buy_order['quantity']) - trade_quantity
                    remaining_sell_qty = float(sell_order['quantity']) - trade_quantity
                    
                    # Remove the original orders
                    self.zrem(BUY_ORDERS_KEY, buy_order_json)
                    self.zrem(SELL_ORDERS_KEY, sell_order_json)
                    
                    # If there are remaining quantities, add updated orders
                    if remaining_buy_qty > 0:
                        buy_order['quantity'] = remaining_buy_qty
                        self.zadd(BUY_ORDERS_KEY, {json.dumps(buy_order): buy_price_neg})
                    else:
                        buy_order['status'] = 'filled'
                    
                    if remaining_sell_qty > 0:
                        sell_order['quantity'] = remaining_sell_qty
                        self.zadd(SELL_ORDERS_KEY, {json.dumps(sell_order): sell_price})
                    else:
                        sell_order['status'] = 'filled'
                    
                    # Add the executed trade to our result list
                    executed_trades.append(trade)
            
            # If internal matching is enabled, do the same for internal orders
            if include_internal and DARK_POOL_ENABLED:
                best_internal_buy = self.zrevrange(INTERNAL_BUY_ORDERS_KEY, 0, 0, withscores=True)
                best_internal_sell = self.zrange(INTERNAL_SELL_ORDERS_KEY, 0, 0, withscores=True)
                
                if best_internal_buy and best_internal_sell:
                    buy_order_json, buy_price_neg = best_internal_buy[0]
                    sell_order_json, sell_price = best_internal_sell[0]
                    
                    # Convert price to actual price
                    buy_price = -buy_price_neg
                    
                    # Parse the order JSON
                    buy_order = json.loads(buy_order_json)
                    sell_order = json.loads(sell_order_json)
                    
                    # Check if prices cross (buy >= sell)
                    if buy_price >= sell_price:
                        # Orders match - execute trade
                        trade_quantity = min(float(buy_order['quantity']), float(sell_order['quantity']))
                        trade_price = (buy_price + sell_price) / 2  # Mid-price for internal trades
                        
                        # Create trade record
                        trade_id = f"INT-T-{int(time.time())}-{buy_order['id']}-{sell_order['id']}"
                        trade = {
                            'id': trade_id,
                            'buy_order_id': buy_order['id'],
                            'sell_order_id': sell_order['id'],
                            'price': trade_price,
                            'quantity': trade_quantity,
                            'timestamp': time.time(),
                            'symbol': buy_order['symbol'],
                            'asset_type': buy_order['asset_type'],
                            'buyer_id': buy_order['trader_id'],
                            'buyer_name': buy_order.get('trader_name', 'Unknown'),
                            'seller_id': sell_order['trader_id'],
                            'seller_name': sell_order.get('trader_name', 'Unknown'),
                            'internal_match': "True"
                        }
                        
                        # Add to internal trades list
                        self.lpush(INTERNAL_TRADES_KEY, json.dumps(trade))
                        
                        # Update order quantities
                        remaining_buy_qty = float(buy_order['quantity']) - trade_quantity
                        remaining_sell_qty = float(sell_order['quantity']) - trade_quantity
                        
                        # Remove the original orders
                        self.zrem(INTERNAL_BUY_ORDERS_KEY, buy_order_json)
                        self.zrem(INTERNAL_SELL_ORDERS_KEY, sell_order_json)
                        
                        # If there are remaining quantities, add updated orders
                        if remaining_buy_qty > 0:
                            buy_order['quantity'] = remaining_buy_qty
                            self.zadd(INTERNAL_BUY_ORDERS_KEY, {json.dumps(buy_order): buy_price_neg})
                        else:
                            buy_order['status'] = 'filled'
                        
                        if remaining_sell_qty > 0:
                            sell_order['quantity'] = remaining_sell_qty
                            self.zadd(INTERNAL_SELL_ORDERS_KEY, {json.dumps(sell_order): sell_price})
                        else:
                            sell_order['status'] = 'filled'
                        
                        # Add the executed trade to our result list
                        executed_trades.append(trade)
        
        except Exception as e:
            logger.error(f"Error matching orders: {e}")
        
        return executed_trades

    def seed_sample_data(self, enable_seeding=False):
        """Seeds sample order data into Redis if enabled and no existing orders are found."""
        if not enable_seeding:
            logger.info("Sample data seeding is disabled")
            return

        # Check if we already have orders
        existing_orders = self.redis.keys("oes:orders:*")
        if existing_orders:
            logger.info(f"Found {len(existing_orders)} existing order book keys, skipping seeding")
            return

    def close(self):
        """Close the Redis connection."""
        try:
            # For Redis library compatibility during shutdown
            self.redis.connection_pool.disconnect()
            logger.info("Redis connection closed")
        except Exception as e:
            logger.error(f"Error closing Redis connection: {e}")

    def match_orders_lua(self, symbol):
        """
        Execute the Lua script to match orders for a symbol.
        
        Args:
            symbol: Trading symbol to match orders for
            
        Returns:
            List of executed trades
        """
        try:
            result = self.match_orders_script(args=[symbol])
            return json.loads(result)
        except Exception as e:
            logger.error(f"Error executing Lua match_orders script: {e}")
            return []

    async def get_all_orders_for_account(self, account_id: str) -> List[Dict[str, Any]]:
        """
        Get all orders for a specific account.
        """
        pattern = f"oes:orders:*:{account_id}:*"
        orders = []
        
        for key in await self.redis.keys(pattern):
            order_data = await self.redis.hgetall(key)
            if order_data:
                orders.append(self._decode_order(order_data))
        
        return orders

    async def publish_notification(self, notification: Dict[str, Any], channel: str = "oes:notifications") -> bool:
        """
        Publish a notification to Redis.
        
        Args:
            notification: Dictionary containing notification data
            channel: The channel to publish to (default: oes:notifications)
            
        Returns:
            True if published successfully, False otherwise
        """
        try:
            # Convert notification to JSON
            notification_json = json.dumps(notification)
            
            # Publish to the specified channel
            self.redis.publish(channel, notification_json)
            
            # Store in account-specific notifications if an account_id is present
            account_id = notification.get('account_id')
            if account_id:
                notifications_key = f"oes:notifications:{account_id}"
                self.redis.lpush(notifications_key, notification_json)
                self.redis.ltrim(notifications_key, 0, 99)  # Keep only the 100 most recent notifications
                
            logger.debug(f"Published notification to {channel}: {notification.get('type')}")
            return True
            
        except Exception as e:
            logger.error(f"Error publishing notification: {e}")
            return False

    async def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        """Get an order by its ID."""
        try:
            order_key = f"oes:order:{order_id}"
            order_json = self.redis.get(order_key)
            
            if not order_json:
                logger.error(f"Order {order_id} not found")
                return None
                
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
            else:
                # Ensure internal_match is a string for consistency
                order['internal_match'] = str(order['internal_match'])
                
            return order
        except Exception as e:
            logger.error(f"Error getting order {order_id}: {str(e)}")
            return None

    async def update_order_field(self, order_id: str, field: str, value: str) -> bool:
        """
        Update a field in an order document.
        
        Args:
            order_id: The ID of the order to update
            field: The field name to update
            value: The new value for the field
            
        Returns:
            True if the update was successful, False otherwise
        """
        try:
            order_key = f"oes:order:{order_id}"
            order_json = self.redis.get(order_key)
            
            if not order_json:
                logger.error(f"Order {order_id} not found")
                return False
                
            order = json.loads(order_json)
            order[field] = value
            
            # If the status is changing to 'filled', add a closed_at timestamp
            if field == 'status' and value in ['filled', 'cancelled']:
                order['closed_at'] = datetime.now().isoformat()
                
            self.redis.set(order_key, json.dumps(order))
            logger.info(f"Updated order {order_id} field {field} to {value}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating order field: {e}")
            return False

    async def update_order(self, order_id: str, updated_order: dict) -> bool:
        """Update an existing order in Redis"""
        try:
            # Log the update operation details
            logger.info(f"Updating order {order_id} with new values: price={updated_order.get('price')}, quantity={updated_order.get('quantity')}")
            
            # First get the current order to compare
            current_order_json = self.redis.get(f"oes:order:{order_id}")
            if not current_order_json:
                logger.error(f"Order {order_id} not found during update")
                return False
                
            current_order = json.loads(current_order_json)
            
            # Check if we need to update the order book
            price_changed = ('price' in updated_order and 
                            str(updated_order.get('price')) != str(current_order.get('price')))
            
            # If price changed, we need to remove from the old book position and add to a new one
            if price_changed:
                logger.info(f"Price changed for order {order_id}, removing from order book")
                await self.remove_order_from_book(order_id)
            
            # First, update all current_order fields from updated_order
            for key, value in updated_order.items():
                current_order[key] = value
                
            # Add metadata about the edit
            current_order['edited'] = True
            current_order['last_edited_at'] = datetime.now().isoformat()
            
            # Convert the order to JSON
            order_json = json.dumps(current_order)
            
            # Update the order in Redis
            logger.info(f"Saving updated order to Redis key: oes:order:{order_id}")
            await self.redis.set(f"oes:order:{order_id}", order_json)
            
            # Update the order in order indices if needed
            account_id = current_order.get("account_id")
            if account_id:
                # Make sure the order is still in the account's order list
                logger.info(f"Adding order {order_id} to account {account_id} orders set")
                await self.redis.sadd(f"oes:account:{account_id}:orders", order_id)
                
                # Make sure it's in the symbol set too
                symbol = current_order.get("symbol")
                if symbol:
                    await self.redis.sadd(f"oes:symbol:{symbol}:orders", order_id)
            
            # If price changed, add back to the order book at the new price
            if price_changed:
                logger.info(f"Adding updated order {order_id} back to the order book")
                await self.add_order_to_book(current_order)
            
            # Verify the order was updated correctly
            updated_json = self.redis.get(f"oes:order:{order_id}")
            if updated_json:
                logger.info(f"Order {order_id} was successfully updated in Redis")
            else:
                logger.error(f"Order {order_id} update verification failed - order not found after update")
            
            return True
        except Exception as e:
            logger.error(f"Error updating order in Redis: {str(e)}")
            return False

    async def record_trade(self, trade: Dict[str, Any]) -> bool:
        """
        Record a trade in Redis.
        
        Args:
            trade: Dictionary containing trade data
            
        Returns:
            True if the trade was recorded successfully, False otherwise
        """
        try:
            # Create a unique key for the trade
            trade_id = trade.get('trade_id', str(uuid.uuid4()))
            trade_key = f"oes:trade:{trade_id}"
            
            # Store the trade in Redis
            self.redis.set(trade_key, json.dumps(trade))
            
            # Add to the trades collection
            self.redis.sadd(TRADES_KEY, trade_id)
            
            # Add to account-specific trade indices
            buy_account_id = trade.get('buy_account_id')
            sell_account_id = trade.get('sell_account_id')
            
            if buy_account_id:
                self.redis.sadd(f"oes:account:{buy_account_id}:trades", trade_id)
                
            if sell_account_id:
                self.redis.sadd(f"oes:account:{sell_account_id}:trades", trade_id)
                
            logger.info(f"Recorded trade {trade_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error recording trade: {e}")
            return False

    async def remove_order_from_book(self, order_id: str) -> bool:
        """Remove an order from the order book"""
        try:
            # Get the order first
            order = await self.get_order(order_id)
            if not order:
                logger.warning(f"Order {order_id} not found when trying to remove from book")
                return False
            
            # Get order details needed for the book
            symbol = order.get("symbol")
            order_type = order.get("type", "").lower()
            
            if not symbol or not order_type:
                logger.warning(f"Order {order_id} missing symbol or type: {symbol}, {order_type}")
                return False
            
            # Determine the appropriate sorted set name
            book_key = f"orderbook:{symbol}:{order_type}s"
            logger.info(f"Removing order {order_id} from book: {book_key}")
            
            # We need to get all members and find the one with matching ID
            # since the members are JSON strings, not just IDs
            all_members = await self.redis.zrange(book_key, 0, -1)
            
            for member in all_members:
                try:
                    member_data = json.loads(member)
                    if member_data.get("id") == order_id or member_data.get("order_id") == order_id:
                        # We found the matching order, remove it
                        logger.info(f"Found matching order in book, removing: {member_data.get('id')}")
                        await self.redis.zrem(book_key, member)
                        return True
                except Exception as e:
                    logger.error(f"Error parsing order JSON: {e}")
                    pass  # Skip invalid JSON
            
            logger.warning(f"Order {order_id} not found in book {book_key}")
            return False
        except Exception as e:
            logger.error(f"Error removing order from book: {str(e)}")
            return False
        
    async def add_order_to_book(self, order: dict) -> bool:
        """Add an order to the order book"""
        try:
            # Extract order details
            order_id = order.get("id")
            symbol = order.get("symbol")
            order_type = order.get("type", "").lower()
            price = float(order.get("price", 0))
            
            if not order_id or not symbol or not order_type:
                logger.warning(f"Cannot add order to book - missing required fields: id={order_id}, symbol={symbol}, type={order_type}")
                return False
            
            # Determine the appropriate sorted set name
            book_key = f"orderbook:{symbol}:{order_type}s"
            logger.info(f"Adding order {order_id} to book {book_key} with price {price}")
            
            # For buy orders, we want higher prices to have priority (negative score)
            # For sell orders, we want lower prices to have priority (positive score)
            score = price
            if order_type == "buy":
                score = -price
            
            # Add to the sorted set - use the entire order JSON as the member
            order_json = json.dumps(order)
            result = await self.redis.zadd(book_key, {order_json: score})
            logger.info(f"Added order {order_id} to book {book_key}, result: {result}")
            return True
        except Exception as e:
            logger.error(f"Error adding order to book: {str(e)}")
            return False

def seed_historical_data():
    """
    Seed the Redis database with historical order book data for the external book.
    This creates realistic market data for a specific day in the past.
    """
    try:
        client = get_redis_client()
        
        # First check if we already have data (avoid re-seeding)
        existing_keys = client.redis.keys("oes:orders:*")
        if existing_keys:
            logger.info(f"Found {len(existing_keys)} existing order book keys, skipping seeding")
            return
        
        logger.info(f"Seeding historical order book data for {HISTORICAL_DATE}")
        
        # Process each ticker from the top 100
        for ticker in TOP_100_NYSE_TICKERS:
            # Generate a realistic base price for this ticker
            base_price = random.uniform(50, 500)
            
            # Create buy orders (bids)
            # Lower prices, higher volume at the bottom of the book
            for i in range(1, 21):  # 20 price levels
                price = round(base_price * (1 - (i * 0.001)), 2)  # Progressive price decrease
                
                # Multiple orders at each price level
                for j in range(random.randint(1, 5)):
                    order_id = f"EXT-{ticker}-B-{i}-{j}-{int(time.time())}"
                    quantity = round(random.uniform(100, 10000), 0)
                    timestamp = time.time() - random.uniform(0, 3600)  # Random time in the last hour
                    
                    # Create order data
                    order_data = {
                        "id": order_id,
                        "symbol": ticker,
                        "price": price,
                        "quantity": quantity,
                        "timestamp": timestamp,
                        "type": "buy",
                        "trader_id": f"EXT-TRADER-{random.randint(1000, 9999)}",
                        "status": "open",
                        "asset_type": "stocks",
                        "created_at": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                        "internal_match": "False"
                    }
                    
                    # Add to Redis sorted set
                    # For buy orders, we use negative price for descending sort
                    client.redis.zadd(BUY_ORDERS_KEY, {json.dumps(order_data): -price})
            
            # Create sell orders (asks)
            # Higher prices, lower volume at the top of the book
            for i in range(1, 21):  # 20 price levels
                price = round(base_price * (1 + (i * 0.001)), 2)  # Progressive price increase
                
                # Multiple orders at each price level
                for j in range(random.randint(1, 5)):
                    order_id = f"EXT-{ticker}-S-{i}-{j}-{int(time.time())}"
                    quantity = round(random.uniform(100, 10000), 0)
                    timestamp = time.time() - random.uniform(0, 3600)  # Random time in the last hour
                    
                    # Create order data
                    order_data = {
                        "id": order_id,
                        "symbol": ticker,
                        "price": price,
                        "quantity": quantity,
                        "timestamp": timestamp,
                        "type": "sell",
                        "trader_id": f"EXT-TRADER-{random.randint(1000, 9999)}",
                        "status": "open",
                        "asset_type": "stocks",
                        "created_at": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                        "internal_match": "False"
                    }
                    
                    # Add to Redis sorted set
                    # For sell orders, we use positive price for ascending sort
                    client.redis.zadd(SELL_ORDERS_KEY, {json.dumps(order_data): price})
        
        # Create some historical trades
        for ticker in TOP_100_NYSE_TICKERS[:20]:  # Only seed trades for top 20 tickers
            # Generate some trades near the base price
            base_price = random.uniform(50, 500)
            
            for i in range(random.randint(5, 15)):  # 5-15 trades per ticker
                price = round(base_price * (1 + random.uniform(-0.005, 0.005)), 2)
                quantity = round(random.uniform(100, 5000), 0)
                timestamp = time.time() - random.uniform(0, 86400)  # Random time in the last 24 hours
                
                trade_data = {
                    "id": f"TRADE-{ticker}-{i}-{int(time.time())}",
                    "symbol": ticker,
                    "price": price,
                    "quantity": quantity,
                    "timestamp": timestamp,
                    "buyer_id": f"EXT-TRADER-{random.randint(1000, 9999)}",
                    "seller_id": f"EXT-TRADER-{random.randint(1000, 9999)}",
                    "asset_type": "stocks",
                    "created_at": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                    "internal_match": "False"
                }
                
                # Add to trades list
                client.redis.lpush(TRADES_KEY, json.dumps(trade_data))
        
        logger.info("Historical data seeding completed successfully")
    
    except Exception as e:
        logger.error(f"Error seeding historical data: {e}")
        raise

def seed_internal_book():
    """
    Seed the Redis database with internal order book data (dark pool).
    These are orders created by traders within the hedge fund.
    """
    try:
        client = get_redis_client()
        
        # First check if we already have data (avoid re-seeding)
        existing_keys = client.redis.keys("oes:internal:orders:*")
        if existing_keys:
            logger.info(f"Found {len(existing_keys)} existing internal order book keys, skipping seeding")
            return
        
        logger.info("Seeding internal order book data (dark pool)")
        
        # Internal traders - these would normally be authenticated users
        internal_traders = [
            {"id": "TRADER-001", "name": "John Smith"},
            {"id": "TRADER-002", "name": "Emma Wilson"},
            {"id": "TRADER-003", "name": "Michael Chen"},
            {"id": "TRADER-004", "name": "Sofia Rodriguez"},
            {"id": "TRADER-005", "name": "David Kim"}
        ]
        
        # Process each ticker from the top 50 (internal traders focus on most liquid stocks)
        for ticker in TOP_100_NYSE_TICKERS[:50]:
            # Generate a realistic base price for this ticker
            base_price = random.uniform(50, 500)
            
            # Number of internal orders should be smaller than external
            num_buy_levels = random.randint(3, 8)
            num_sell_levels = random.randint(3, 8)
            
            # Create buy orders (bids)
            for i in range(1, num_buy_levels + 1):
                price = round(base_price * (1 - (i * 0.0008)), 2)  # Slightly better prices than external
                
                # Multiple orders at each price level
                for j in range(random.randint(1, 3)):
                    order_id = f"INT-{ticker}-B-{i}-{j}-{int(time.time())}"
                    quantity = round(random.uniform(500, 20000), 0)  # Larger sizes for institutional orders
                    timestamp = time.time() - random.uniform(0, 7200)  # Random time in the last 2 hours
                    trader = random.choice(internal_traders)
                    
                    # Create order data
                    order_data = {
                        "id": order_id,
                        "symbol": ticker,
                        "price": price,
                        "quantity": quantity,
                        "timestamp": timestamp,
                        "type": "buy",
                        "trader_id": trader["id"],
                        "trader_name": trader["name"],
                        "status": "open",
                        "asset_type": "stocks",
                        "created_at": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                        "internal_match": "True",
                        "edited": "False"
                    }
                    
                    # Add to Redis sorted set
                    # For buy orders, we use negative price for descending sort
                    client.redis.zadd(INTERNAL_BUY_ORDERS_KEY, {json.dumps(order_data): -price})
            
            # Create sell orders (asks)
            for i in range(1, num_sell_levels + 1):
                price = round(base_price * (1 + (i * 0.0008)), 2)  # Slightly better prices than external
                
                # Multiple orders at each price level
                for j in range(random.randint(1, 3)):
                    order_id = f"INT-{ticker}-S-{i}-{j}-{int(time.time())}"
                    quantity = round(random.uniform(500, 20000), 0)  # Larger sizes for institutional orders
                    timestamp = time.time() - random.uniform(0, 7200)  # Random time in the last 2 hours
                    trader = random.choice(internal_traders)
                    
                    # Create order data
                    order_data = {
                        "id": order_id,
                        "symbol": ticker,
                        "price": price,
                        "quantity": quantity,
                        "timestamp": timestamp,
                        "type": "sell",
                        "trader_id": trader["id"],
                        "trader_name": trader["name"],
                        "status": "open",
                        "asset_type": "stocks",
                        "created_at": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                        "internal_match": "True",
                        "edited": "False"
                    }
                    
                    # Add to Redis sorted set
                    # For sell orders, we use positive price for ascending sort
                    client.redis.zadd(INTERNAL_SELL_ORDERS_KEY, {json.dumps(order_data): price})
        
        # Create some internal trades
        for ticker in TOP_100_NYSE_TICKERS[:15]:  # Only seed trades for top 15 tickers for internal
            # Generate some trades near the base price
            base_price = random.uniform(50, 500)
            
            for i in range(random.randint(2, 8)):  # 2-8 trades per ticker
                price = round(base_price * (1 + random.uniform(-0.003, 0.003)), 2)
                quantity = round(random.uniform(1000, 10000), 0)
                timestamp = time.time() - random.uniform(0, 43200)  # Random time in the last 12 hours
                buyer = random.choice(internal_traders)
                seller = random.choice(internal_traders)
                
                trade_data = {
                    "id": f"INT-TRADE-{ticker}-{i}-{int(time.time())}",
                    "symbol": ticker,
                    "price": price,
                    "quantity": quantity,
                    "timestamp": timestamp,
                    "buyer_id": buyer["id"],
                    "buyer_name": buyer["name"],
                    "seller_id": seller["id"],
                    "seller_name": seller["name"],
                    "asset_type": "stocks",
                    "created_at": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
                    "internal_match": "True"
                }
                
                # Add to internal trades list
                client.redis.lpush(INTERNAL_TRADES_KEY, json.dumps(trade_data))
        
        logger.info("Internal order book data seeding completed successfully")
    
    except Exception as e:
        logger.error(f"Error seeding internal order book data: {e}")
        raise

# Create a singleton instance
redis_client = RedisClient()

# Function to get the Redis client instance
def get_redis_client():
    """Return the Redis client singleton instance."""
    return redis_client 
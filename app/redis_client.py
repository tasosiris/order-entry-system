import os
import redis
import logging
from redis.connection import BlockingConnectionPool
from redis.exceptions import ConnectionError
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oes.redis")

# Redis connection configuration
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 0))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)

# Create a connection pool for better performance with multiple concurrent requests
connection_pool = BlockingConnectionPool(
    host=REDIS_HOST,
    port=REDIS_PORT,
    db=REDIS_DB,
    password=REDIS_PASSWORD,
    decode_responses=True,
    max_connections=100,  # Adjust based on expected concurrent connections
    timeout=5  # Connection timeout in seconds
)

def get_redis_client():
    """Return a Redis client from the connection pool with retries and backoff."""
    max_retries = 3
    retry_delay = 1  # Start with 1 second delay
    
    for attempt in range(max_retries):
        try:
            client = redis.Redis(connection_pool=connection_pool)
            # Test the connection
            client.ping()
            logger.info("Successfully connected to Redis")
            return client
        except ConnectionError as e:
            # Log the failure
            logger.warning(f"Failed to connect to Redis (attempt {attempt+1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                # Only wait if we're going to retry
                logger.info(f"Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
                # Exponential backoff
                retry_delay *= 2
            else:
                # Final attempt failed
                logger.error(f"Failed to connect to Redis after {max_retries} attempts: {e}")
                raise

# Redis keys for regular market
BUY_ORDERS_KEY = "orders:buy"
SELL_ORDERS_KEY = "orders:sell"
TRADES_KEY = "trades"

# Redis keys for Dark Pool
INTERNAL_BUY_ORDERS_KEY = "darkpool:buy"
INTERNAL_SELL_ORDERS_KEY = "darkpool:sell"
INTERNAL_TRADES_KEY = "darkpool:trades"

# Define a flag for whether to use dark pool matching first
DARK_POOL_ENABLED = os.getenv("DARK_POOL_ENABLED", "true").lower() == "true"

# Enhanced Lua scripts for order matching with dark pool support
MATCH_ORDERS_SCRIPT = """
-- Order matching Lua script for Redis
-- This script atomically matches buy and sell orders based on price-time priority
-- Enhanced to support internalization of orders (Dark Pool)

local buy_orders_key = KEYS[1]  -- Sorted set of buy orders
local sell_orders_key = KEYS[2] -- Sorted set of sell orders
local trades_key = KEYS[3]      -- List to store executed trades
local internal_buy_key = KEYS[4] -- Internal dark pool buy orders
local internal_sell_key = KEYS[5] -- Internal dark pool sell orders
local internal_trades_key = KEYS[6] -- Internal dark pool trades

-- Dark pool flag: whether to try internal matching first
local use_dark_pool = tonumber(ARGV[1]) == 1

-- Helper function to convert Redis hash to Lua table
local function hash_to_table(hash)
    local result = {}
    for i = 1, #hash, 2 do
        result[hash[i]] = hash[i + 1]
    end
    return result
end

-- Helper function for internal matching between two orders
local function match_orders(buy_id, sell_id, buy_orders_key, sell_orders_key, is_internal)
    -- Get full order details from hashes
    local buy_order = redis.call('HGETALL', 'order:' .. buy_id)
    local sell_order = redis.call('HGETALL', 'order:' .. sell_id)
    
    -- Convert to tables
    local buy = hash_to_table(buy_order)
    local sell = hash_to_table(sell_order)
    
    -- Check if price matches (buy price >= sell price)
    if tonumber(buy.price) >= tonumber(sell.price) then
        -- Calculate trade quantity (minimum of available quantities)
        local trade_qty = math.min(tonumber(buy.quantity), tonumber(sell.quantity))
        
        -- Use sell price as execution price (price-time priority)
        local exec_price = sell.price
        
        -- Record the trade
        local trade_id = redis.call('INCR', 'trade_id_counter')
        
        -- Add internal flag to trade details
        local dark_pool_flag = 0
        if is_internal then
            dark_pool_flag = 1
        end
        
        -- Store trade details
        redis.call('HMSET', 'trade:' .. trade_id, 
            'trade_id', trade_id,
            'buy_order_id', buy_id,
            'sell_order_id', sell_id,
            'price', exec_price,
            'quantity', trade_qty,
            'timestamp', redis.call('TIME')[1],  -- Current Unix timestamp
            'internal_match', dark_pool_flag     -- Flag for dark pool trades
        )
        
        -- Add to trade history (either dark pool or regular)
        local target_trades_key = is_internal and internal_trades_key or trades_key
        redis.call('LPUSH', target_trades_key, trade_id)
        
        -- Update or remove orders based on fill status
        local updated_buy_qty = tonumber(buy.quantity) - trade_qty
        local updated_sell_qty = tonumber(sell.quantity) - trade_qty
        
        -- Handle buy order
        if updated_buy_qty <= 0 then
            -- Fully filled, remove buy order
            redis.call('ZREM', buy_orders_key, buy_id)
            redis.call('DEL', 'order:' .. buy_id)
        else
            -- Partially filled, update buy order
            redis.call('HSET', 'order:' .. buy_id, 'quantity', updated_buy_qty)
        end
        
        -- Handle sell order
        if updated_sell_qty <= 0 then
            -- Fully filled, remove sell order
            redis.call('ZREM', sell_orders_key, sell_id)
            redis.call('DEL', 'order:' .. sell_id)
        else
            -- Partially filled, update sell order
            redis.call('HSET', 'order:' .. sell_id, 'quantity', updated_sell_qty)
        end
        
        return {trade_id, buy_id, sell_id, exec_price, trade_qty, updated_buy_qty, updated_sell_qty, dark_pool_flag}
    end
    
    -- No match found
    return false
end

-- First try internal dark pool matching if enabled
if use_dark_pool then
    -- Get top internal buy order (highest price first)
    local internal_top_buys = redis.call('ZRANGE', internal_buy_key, 0, 0, 'WITHSCORES')
    
    -- Get top internal sell order (lowest price first)
    local internal_top_sells = redis.call('ZRANGE', internal_sell_key, 0, 0, 'WITHSCORES')
    
    -- Check if we have both internal buy and sell orders
    if #internal_top_buys > 0 and #internal_top_sells > 0 then
        local buy_id = internal_top_buys[1]
        local sell_id = internal_top_sells[1]
        
        -- Try to match internal orders
        local result = match_orders(buy_id, sell_id, internal_buy_key, internal_sell_key, true)
        if result then
            return result
        end
    end
    
    -- If no internal match, try cross-matching (internal buy with external sell)
    if #internal_top_buys > 0 and #redis.call('ZRANGE', sell_orders_key, 0, 0) > 0 then
        local buy_id = internal_top_buys[1]
        local sell_id = redis.call('ZRANGE', sell_orders_key, 0, 0)[1]
        
        local result = match_orders(buy_id, sell_id, internal_buy_key, sell_orders_key, true)
        if result then
            return result
        end
    end
    
    -- Try cross-matching (external buy with internal sell)
    if #redis.call('ZRANGE', buy_orders_key, 0, 0) > 0 and #internal_top_sells > 0 then
        local buy_id = redis.call('ZRANGE', buy_orders_key, 0, 0)[1]
        local sell_id = internal_top_sells[1]
        
        local result = match_orders(buy_id, sell_id, buy_orders_key, internal_sell_key, true)
        if result then
            return result
        end
    end
end

-- If no internal matches or dark pool is disabled, try regular market matching
-- Get top buy order (highest price first)
local top_buys = redis.call('ZRANGE', buy_orders_key, 0, 0, 'WITHSCORES')
if #top_buys == 0 then return false end  -- No buy orders

-- Get top sell order (lowest price first)
local top_sells = redis.call('ZRANGE', sell_orders_key, 0, 0, 'WITHSCORES')
if #top_sells == 0 then return false end -- No sell orders

local buy_id = top_buys[1]
local sell_id = top_sells[1]

-- Try regular matching
return match_orders(buy_id, sell_id, buy_orders_key, sell_orders_key, false)
"""

# Attempt to get a Redis client and register the Lua script
try:
    # DEBUG: Log that we are starting the Redis client initialization process
    print('[DEBUG] Starting Redis client initialization...')
    
    # Get the Redis client
    redis_client = get_redis_client()
    print('[DEBUG] Redis client obtained:', redis_client)
    
    # Register the Lua script for order matching
    match_orders = redis_client.register_script(MATCH_ORDERS_SCRIPT)
    print('[DEBUG] Lua script for order matching registered successfully.')
    
    # Optionally, log a success message using logger if available
    logger.info('Successfully registered Lua script for order matching')
except Exception as e:
    # Log detailed error information if an exception occurs
    print('[DEBUG] Error while initializing Redis client or registering Lua script:', e)
    logger.error(f"Error initializing Redis client: {e}")
    # Create placeholders so that the application can show appropriate errors when trying to use these
    redis_client = None
    match_orders = None 
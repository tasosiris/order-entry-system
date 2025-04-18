#!/usr/bin/env python
"""
Script to populate Redis with realistic market data for AAPL (external order book)
"""

import sys
import os
import json
import uuid
import time
import random
import logging
from datetime import datetime

# Add parent directory to path so we can import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import app modules
from app.redis_client import redis_client, BUY_ORDERS_KEY, SELL_ORDERS_KEY

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("oes.market_data")

# Constants
SYMBOL = "AAPL"
BASE_PRICE = 175.00  # Realistic AAPL price

def clear_existing_market_data():
    """Clear existing market data in Redis"""
    # Clear buy orders
    keys = redis_client.keys(f"{BUY_ORDERS_KEY}*")
    if keys:
        for key in keys:
            redis_client.delete(key)
    
    # Clear sell orders
    keys = redis_client.keys(f"{SELL_ORDERS_KEY}*")
    if keys:
        for key in keys:
            redis_client.delete(key)
    
    logger.info("Cleared existing market data")

def generate_market_data():
    """Generate realistic market data for AAPL"""
    # Generate buy orders (bids)
    buy_orders = []
    
    # Tier 1: Very close to market (tight spread)
    for i in range(5):
        price = round(BASE_PRICE - random.uniform(0.01, 0.10) - (i * 0.02), 2)
        quantity = random.randint(10000, 50000)
        buy_orders.append(create_market_order("buy", price, quantity))
    
    # Tier 2: Close to market
    for i in range(7):
        price = round(BASE_PRICE - random.uniform(0.15, 0.50) - (i * 0.05), 2)
        quantity = random.randint(50000, 200000)
        buy_orders.append(create_market_order("buy", price, quantity))
    
    # Tier 3: Deeper book
    for i in range(8):
        price = round(BASE_PRICE - random.uniform(0.60, 1.50) - (i * 0.15), 2)
        quantity = random.randint(100000, 500000)
        buy_orders.append(create_market_order("buy", price, quantity))
    
    # Generate sell orders (asks)
    sell_orders = []
    
    # Tier 1: Very close to market (tight spread)
    for i in range(5):
        price = round(BASE_PRICE + random.uniform(0.01, 0.10) + (i * 0.02), 2)
        quantity = random.randint(10000, 50000)
        sell_orders.append(create_market_order("sell", price, quantity))
    
    # Tier 2: Close to market
    for i in range(7):
        price = round(BASE_PRICE + random.uniform(0.15, 0.50) + (i * 0.05), 2)
        quantity = random.randint(50000, 200000)
        sell_orders.append(create_market_order("sell", price, quantity))
    
    # Tier 3: Deeper book
    for i in range(8):
        price = round(BASE_PRICE + random.uniform(0.60, 1.50) + (i * 0.15), 2)
        quantity = random.randint(100000, 500000)
        sell_orders.append(create_market_order("sell", price, quantity))
    
    return buy_orders, sell_orders

def create_market_order(order_type, price, quantity):
    """Create a market order object"""
    order_id = str(uuid.uuid4())
    timestamp = time.time()
    
    order = {
        "id": order_id,
        "order_id": order_id,
        "symbol": SYMBOL,
        "type": order_type,
        "price": price,
        "quantity": quantity,
        "timestamp": timestamp,
        "exchange": "NASDAQ",
        "total": price * quantity  # Pre-calculate total for convenience
    }
    
    return order

def save_market_data_to_redis(buy_orders, sell_orders):
    """Save market data to Redis"""
    # Sort buy orders by price (descending)
    buy_orders.sort(key=lambda x: x["price"], reverse=True)
    
    # Sort sell orders by price (ascending)
    sell_orders.sort(key=lambda x: x["price"])
    
    # For buy orders, we store with negative price for proper sorting
    for order in buy_orders:
        price_neg = -float(order["price"])
        redis_client.zadd(BUY_ORDERS_KEY, {json.dumps(order): price_neg})
    
    # For sell orders, we store with positive price
    for order in sell_orders:
        price = float(order["price"])
        redis_client.zadd(SELL_ORDERS_KEY, {json.dumps(order): price})
    
    logger.info(f"Added {len(buy_orders)} buy orders and {len(sell_orders)} sell orders to market data")

def main():
    """Main function to populate market data"""
    # Clear existing market data
    clear_existing_market_data()
    
    # Generate new market data
    logger.info(f"Generating realistic market data for {SYMBOL}...")
    buy_orders, sell_orders = generate_market_data()
    
    # Save market data to Redis
    logger.info("Saving market data to Redis...")
    save_market_data_to_redis(buy_orders, sell_orders)
    
    logger.info("Done! Redis has been populated with realistic market data.")
    logger.info(f"Total market orders: {len(buy_orders) + len(sell_orders)}")
    
    # Log bid-ask spread
    bid = buy_orders[0]["price"] if buy_orders else 0
    ask = sell_orders[0]["price"] if sell_orders else 0
    spread = round(ask - bid, 2)
    logger.info(f"Bid: ${bid} - Ask: ${ask} - Spread: ${spread}")

if __name__ == "__main__":
    main() 
#!/usr/bin/env python
"""
Script to populate Redis with multiple AAPL orders at realistic hedge fund quantities
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
from app.redis_client import redis_client
from app.accounts import account_manager

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("oes.populate")

# Constants
SYMBOL = "AAPL"
RISK_NOTIFICATIONS = [
    {"type": "risk_alert", "severity": "high", "account_id": "", "message": "Excessive position size for AAPL exceeds 10% of account value", "timestamp": time.time()},
    {"type": "risk_alert", "severity": "medium", "account_id": "", "message": "Concentrated exposure in technology sector detected", "timestamp": time.time()},
    {"type": "risk_alert", "severity": "low", "account_id": "", "message": "Unusual trading pattern detected for AAPL", "timestamp": time.time()},
    {"type": "risk_alert", "severity": "high", "account_id": "", "message": "Margin call warning: Account approaching minimum maintenance requirement", "timestamp": time.time()},
    {"type": "risk_alert", "severity": "medium", "account_id": "", "message": "AAPL position size growing rapidly in last 24 hours", "timestamp": time.time()}
]

def generate_orders(account_id):
    """Generate multiple realistic AAPL orders for a hedge fund"""
    # Current realistic AAPL price range
    base_price = 175.00
    
    # Generate buy orders (bids)
    buy_orders = []
    # Tier 1: Very close to market price (small spread)
    for i in range(1):
        price = round(base_price - random.uniform(0.05, 0.20), 2)
        quantity = random.randint(5000, 15000)
        buy_orders.append(create_order(account_id, "buy", price, quantity))
        
    # Tier 2: Slightly below market
    for i in range(1):
        price = round(base_price - random.uniform(0.30, 1.00), 2)
        quantity = random.randint(10000, 25000)
        buy_orders.append(create_order(account_id, "buy", price, quantity))
    
    # Tier 3: Strategic deeper bids
    for i in range(1):
        price = round(base_price - random.uniform(1.50, 3.00), 2)
        quantity = random.randint(20000, 50000)
        buy_orders.append(create_order(account_id, "buy", price, quantity))
    
    # Generate sell orders (asks)
    sell_orders = []
    # Tier 1: Very close to market price (small spread)
    for i in range(1):
        price = round(base_price + random.uniform(0.05, 0.20), 2)
        quantity = random.randint(5000, 15000)
        sell_orders.append(create_order(account_id, "sell", price, quantity))
        
    # Tier 2: Slightly above market
    for i in range(1):
        price = round(base_price + random.uniform(0.30, 1.00), 2)
        quantity = random.randint(10000, 25000)
        sell_orders.append(create_order(account_id, "sell", price, quantity))
    
    # Tier 3: Strategic higher asks
    for i in range(1):
        price = round(base_price + random.uniform(1.50, 3.00), 2)
        quantity = random.randint(20000, 50000)
        sell_orders.append(create_order(account_id, "sell", price, quantity))
    
    return buy_orders, sell_orders

def create_order(account_id, order_type, price, quantity):
    """Create a single order object"""
    order_id = f"order-{uuid.uuid4()}"
    timestamp = time.time()
    
    order = {
        "id": order_id,
        "order_id": order_id,
        "account_id": account_id,
        "symbol": SYMBOL,
        "type": order_type,
        "price": str(price),
        "quantity": str(quantity),
        "status": "open",
        "asset_type": "stocks",
        "filled_quantity": "0",
        "timestamp": str(timestamp),
        "created_at": datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S"),
        "internal_match": "True"
    }
    
    # Calculate total value for convenience
    order["total"] = float(price) * float(quantity)
    
    return order

def save_order_to_redis(order):
    """Save an order to Redis and relevant indices"""
    order_id = order["order_id"]
    account_id = order["account_id"]
    symbol = order["symbol"]
    
    # Main order key
    order_key = f"oes:order:{order_id}"
    order_json = json.dumps(order)
    redis_client.set(order_key, order_json)
    
    # Add to the main orders collection
    redis_client.sadd("oes:orders", order_id)
    
    # Add to account-specific order index
    account_orders_key = f"oes:account:{account_id}:orders"
    redis_client.sadd(account_orders_key, order_id)
    
    # Add to symbol-specific order index
    symbol_orders_key = f"oes:symbol:{symbol}:orders"
    redis_client.sadd(symbol_orders_key, order_id)
    
    # Log the operation
    logger.info(f"Added {order['type']} order: {quantity_str(order['quantity'])} {symbol} @ ${order['price']} (ID: {order_id})")
    
    return order

def quantity_str(quantity):
    """Format quantity for logging"""
    qty = int(float(quantity))
    if qty >= 1000:
        return f"{qty/1000:.1f}K"
    return str(qty)

def clear_existing_orders():
    """Clear existing orders in Redis"""
    # Find all order IDs in the main orders set
    order_ids = redis_client.smembers("oes:orders")
    
    if not order_ids:
        logger.info("No existing orders found")
        return
    
    # Delete each order and remove from indices
    for order_id in order_ids:
        # Get the order to find its account and symbol
        order_key = f"oes:order:{order_id}"
        order_json = redis_client.get(order_key)
        
        if order_json:
            try:
                order = json.loads(order_json)
                account_id = order.get("account_id")
                symbol = order.get("symbol")
                
                # Remove from account-specific order index
                if account_id:
                    account_orders_key = f"oes:account:{account_id}:orders"
                    redis_client.srem(account_orders_key, order_id)
                
                # Remove from symbol-specific order index
                if symbol:
                    symbol_orders_key = f"oes:symbol:{symbol}:orders"
                    redis_client.srem(symbol_orders_key, order_id)
                
                # Delete the order itself
                redis_client.delete(order_key)
            except:
                # Just delete the key if we can't parse it
                redis_client.delete(order_key)
    
    # Clear the main orders set
    redis_client.delete("oes:orders")
    
    logger.info(f"Cleared {len(order_ids)} existing orders")

def create_risk_notifications(account_ids):
    """Create risk notifications for the accounts"""
    notifications_key = "oes:risk:notifications"
    
    # Clear existing notifications
    redis_client.delete(notifications_key)
    
    # Create new notifications for each account
    for account_id in account_ids:
        for notification in RISK_NOTIFICATIONS:
            # Create a copy and set the account ID
            notification_copy = notification.copy()
            notification_copy["account_id"] = account_id
            notification_copy["id"] = str(uuid.uuid4())
            notification_copy["timestamp"] = time.time()
            
            # Save the notification
            redis_client.lpush(notifications_key, json.dumps(notification_copy))
            logger.info(f"Added risk notification for account {account_id}: {notification_copy['message']}")

def main():
    """Main function to populate Redis with orders"""
    # Clear existing orders
    logger.info("Clearing existing orders...")
    clear_existing_orders()
    
    # Get all account IDs
    accounts = account_manager.get_all_accounts()
    if not accounts:
        logger.error("No accounts found. Please run the application first to create accounts.")
        return
    
    account_ids = [account.account_id for account in accounts]
    
    # Create orders for each account
    logger.info(f"Generating orders for {len(accounts)} accounts...")
    all_orders = []
    
    for account in accounts:
        buy_orders, sell_orders = generate_orders(account.account_id)
        all_orders.extend(buy_orders)
        all_orders.extend(sell_orders)
        
        logger.info(f"Generated {len(buy_orders)} buy orders and {len(sell_orders)} sell orders for account {account.name}")
    
    # Save all orders to Redis
    logger.info(f"Saving {len(all_orders)} orders to Redis...")
    for order in all_orders:
        save_order_to_redis(order)
    
    # Create risk notifications
    logger.info("Creating risk notifications...")
    create_risk_notifications(account_ids)
    
    logger.info("Done! Redis has been populated with realistic AAPL orders.")
    logger.info(f"Total orders added: {len(all_orders)}")

if __name__ == "__main__":
    main() 
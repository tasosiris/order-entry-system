import asyncio
import sys
import json
import logging
from app.matching_engine import matching_engine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("test_matching")

async def run_test():
    logger.info("Starting matching engine test")
    
    # Get all active orders to check status before matching
    active_orders = matching_engine.get_all_active_orders()
    logger.info(f"Before matching: {len(active_orders)} active orders")
    
    # Attempt to match orders for AAPL
    trades = await matching_engine.match_orders("AAPL")
    
    if trades:
        logger.info(f"Successfully matched {len(trades)} trades")
        for i, trade in enumerate(trades):
            logger.info(f"Trade {i+1}: {json.dumps(trade, indent=2)}")
    else:
        logger.info("No trades were matched")
    
    # Get all active orders again to check status after matching
    active_orders = matching_engine.get_all_active_orders()
    logger.info(f"After matching: {len(active_orders)} active orders")
    
    # If there are still orders, let's check what they are
    if active_orders:
        logger.info("Remaining active orders:")
        for order in active_orders:
            logger.info(f"Order ID: {order.get('id')}, Type: {order.get('type')}, Status: {order.get('status')}")
    
    logger.info("Test completed")

if __name__ == "__main__":
    asyncio.run(run_test()) 
"""
Order Entry System (OES) - Main Application

This module serves as the entry point for the Order Entry System, a high-performance
trading platform designed for hedge funds. It provides real-time order book management,
WebSocket communication, and comprehensive trading functionality.

The application is built with FastAPI and features:
- Real-time WebSocket updates for order book and trades
- Background tasks for order matching and broadcasting
- REST API endpoints for trading operations
- System monitoring and latency tracking
- Multiple trading account management
"""

# Standard library imports
import os
import json
import time
import asyncio
from typing import Dict, List, Any, Optional
import logging

# FastAPI and web-related imports
from fastapi import (
    FastAPI, 
    WebSocket, 
    WebSocketDisconnect, 
    Request, 
    Body, 
    HTTPException, 
    Depends, 
    Form
)
from fastapi.responses import (
    HTMLResponse, 
    JSONResponse, 
    Response, 
    RedirectResponse
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Application-specific imports
from app.order_book import order_book, seed_historical_data
from app.websocket import connection_manager
from app.api import orders_router, accounts_router, risk_router
from app.redis_client import redis_client
from app.matching_engine import matching_engine
from app.accounts import account_manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oes")

# Create FastAPI application
app = FastAPI(
    title="Order Entry System (OES)",
    description="High-performance order entry system for hedge funds",
    version="1.0.0"
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.mount("/css", StaticFiles(directory="app/static/css"), name="css")
app.mount("/js", StaticFiles(directory="app/static/js"), name="js")

# Include routers
app.include_router(orders_router)
app.include_router(accounts_router)
app.include_router(risk_router)

# Configure templates
templates = Jinja2Templates(directory="app/templates")

# Background task for matching orders
matching_task = None

# Background task for periodic order book broadcasts
broadcast_task = None 

# Background task for latency measurements
latency_task = None

def seed_internal_book():
    """
    Seed the internal order book with some initial data.
    This is a placeholder function that can be expanded later.
    """
    try:
        # For now, we'll just return True as we don't need internal orders seeded
        return True
    except Exception as e:
        logger.error(f"Error seeding internal book: {str(e)}")
        return False

@app.on_event("startup")
async def startup_event():
    """Initialize the application on startup."""
    try:
        # Check if we should skip clearing orders
        should_clear_orders = os.environ.get("OES_NO_CLEAR_DATA") != "1"
        
        # Clear all orders from Redis if needed
        if should_clear_orders:
            logger.info("Clearing all orders from Redis")
            redis_client.clear_all_orders()
            logger.info("All orders cleared successfully")
        else:
            logger.info("Skipping order clearing due to --no-clear flag")
        
        # Seed historical data
        if not seed_historical_data():
            logger.warning("Failed to seed order book data")
        
        # Seed internal book
        if not seed_internal_book():
            logger.warning("Failed to seed internal book")
        
        # Start the order matching background task
        global matching_task
        matching_task = asyncio.create_task(periodic_order_matching())
        logger.info("Started primary order matching task")
        
        # Start the automatic order matching service with very short interval
        logger.info("Starting automatic order matching service")
        auto_matching_task = asyncio.create_task(matching_engine.start_auto_matching(interval_seconds=0.05))
        
        # Start the order book broadcast task
        global broadcast_task
        broadcast_task = asyncio.create_task(periodic_order_book_broadcast())
        
        # Start the latency measurement task
        global latency_task
        latency_task = asyncio.create_task(periodic_latency_broadcast())
        
        # Start the notification listener
        asyncio.create_task(listen_for_notifications())
        
        print("Order Entry System started successfully.")
        logger.info("Order Entry System initialized with aggressive order matching")
    except Exception as e:
        logger.error(f"Error during startup: {str(e)}")
        raise

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown."""
    try:
        # Cancel background tasks
        if matching_task:
            matching_task.cancel()
            try:
                await matching_task
            except asyncio.CancelledError:
                pass
            
        if broadcast_task:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass
            
        if latency_task:
            latency_task.cancel()
            try:
                await latency_task
            except asyncio.CancelledError:
                pass

        # Close all WebSocket connections
        for connection in connection_manager.active_connections:
            await connection.close()
        
        # Clear connection manager
        connection_manager.active_connections.clear()
        
        # Close Redis connections
        redis_client.close()
        
        logger.info("Application shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")

async def periodic_order_matching():
    """Background task to periodically match orders."""
    logger.info("Starting aggressive order matching task")
    while True:
        try:
            # Match orders using the enhanced matching engine
            trades = await matching_engine.match_all_symbols()
            
            # Process legacy order book matches
            legacy_trades = await order_book.match_orders()
            
            # Combine trades from both systems
            all_trades = trades + legacy_trades
            
            if all_trades:
                logger.info(f"Successfully matched {len(all_trades)} trades")
            
            # If trades were executed, broadcast them and update order books
            for trade in all_trades:
                # Broadcast trade
                await connection_manager.broadcast(
                    {"type": "trade", "data": trade},
                    channel="trades"
                )
                
                # Also broadcast to symbol-specific channel
                if "symbol" in trade:
                    symbol_channel = f"trades:{trade['symbol']}"
                    await connection_manager.broadcast(
                        {"type": "trade", "data": trade},
                        channel=symbol_channel
                    )
                    
                    # Get and broadcast updated order book for this symbol
                    book = await get_order_book(trade['symbol'], depth=15)
                    await connection_manager.broadcast(
                        {
                            "type": "orderbook",
                            "symbol": trade['symbol'],
                            "data": book,
                            "timestamp": time.time()
                        },
                        channel=f"orderbook:{trade['symbol']}"
                    )
            
            # Very short delay to prevent CPU hogging but allow for very frequent matching
            await asyncio.sleep(0.001)  # 1ms delay between matching attempts
            
        except asyncio.CancelledError:
            # Task is being cancelled
            break
        except Exception as e:
            logger.error(f"Error in order matching: {e}")
            # Shorter delay on error
            await asyncio.sleep(0.1)

async def periodic_order_book_broadcast():
    """Background task to periodically broadcast the order book."""
    while True:
        try:
            # Get current order books for all active symbols
            active_symbols = set()
            for connection in connection_manager.active_connections:
                if hasattr(connection, 'subscribed_symbol'):
                    active_symbols.add(connection.subscribed_symbol)
            
            for symbol in active_symbols:
                # Get order book for this symbol
                book = await get_order_book(symbol, depth=15)
                
                # Broadcast to symbol-specific channel
                await connection_manager.broadcast(
                    {
                        "type": "orderbook",
                        "symbol": symbol,
                        "data": book,
                        "timestamp": time.time()
                    },
                    channel=f"orderbook:{symbol}"
                )
            
            # Wait before next broadcast
            await asyncio.sleep(0.1)  # 100ms between broadcasts for smooth updates
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in order book broadcast: {e}")
            await asyncio.sleep(1)

async def periodic_latency_broadcast():
    """Background task to periodically measure and broadcast system latency."""
    while True:
        try:
            # Measure Redis latency
            start_time = time.time()
            redis_client.ping()
            redis_latency = (time.time() - start_time) * 1000  # ms
            
            # Create latency data
            latency_data = {
                "redis_latency": round(redis_latency, 2),
                "timestamp": time.time()
            }
            
            # Broadcast to all clients
            await connection_manager.broadcast(
                {"type": "latency", "data": latency_data},
                channel="system"
            )
            
            # Wait before next measurement
            await asyncio.sleep(5)  # 5 seconds between latency measurements
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            print(f"Error in latency measurement: {e}")
            await asyncio.sleep(5)

async def listen_for_notifications():
    """
    Listen for notifications published to Redis and broadcast them to connected clients.
    This enables real-time trade notifications and order updates.
    """
    try:
        # Create a Redis connection for PubSub
        pubsub = redis_client.redis.pubsub()
        
        # Subscribe to the notifications channel
        pubsub.subscribe("oes:notifications")
        
        logger.info("Listening for notifications on Redis PubSub channel")
        
        # Track seen trade IDs to prevent duplicate notifications
        seen_trade_ids = {}
        
        # Listen for messages and broadcast them
        while True:
            # Use get_message with a timeout instead of await
            message = pubsub.get_message(ignore_subscribe_messages=True, timeout=0.01)
            if message:
                try:
                    # Get the message data
                    data = message.get('data')
                    if isinstance(data, bytes):
                        data = data.decode('utf-8')
                        
                    # Parse the JSON data
                    notification = json.loads(data)
                    
                    # Add 'notification' type if not present
                    if 'type' not in notification:
                        notification['type'] = 'notification'
                    
                    # Broadcast to all connected clients
                    await connection_manager.broadcast(notification)
                    
                    # If it's a trade notification, also broadcast on the trades channel
                    if notification.get('type') == 'trade_executed':
                        await connection_manager.broadcast(notification, channel='trades')
                        
                        # Only send toast notification if we haven't seen this trade ID recently
                        trade_id = notification.get('trade_id')
                        current_time = time.time()
                        
                        if trade_id:
                            # Check if we've seen this trade ID in the last 5 seconds
                            if (trade_id not in seen_trade_ids or 
                                current_time - seen_trade_ids[trade_id] > 5):
                                
                                # Record that we've seen this trade ID
                                seen_trade_ids[trade_id] = current_time
                                
                                # Use the toast data from the trade notification
                                if 'toast' in notification:
                                    toast = {
                                        'type': 'toast',
                                        **notification['toast'],
                                        'timestamp': current_time
                                    }
                                    await connection_manager.broadcast(toast)
                                
                                # Limit the size of seen_trade_ids by removing old entries
                                if len(seen_trade_ids) > 1000:
                                    # Remove entries older than 30 seconds
                                    old_time = current_time - 30
                                    seen_trade_ids = {
                                        tid: ts for tid, ts in seen_trade_ids.items() 
                                        if ts > old_time
                                    }
                    
                except Exception as e:
                    logger.error(f"Error processing notification: {e}")
            
            # Short delay to avoid CPU spinning
            await asyncio.sleep(0.01)
    except Exception as e:
        logger.error(f"Error in notification listener: {e}")
        # Try to reconnect after a delay
        await asyncio.sleep(5)
        asyncio.create_task(listen_for_notifications())

@app.get("/api/status")
async def get_status():
    """Get system status."""
    return {"status": "online", "timestamp": time.time()}

@app.get("/")
async def get_home(request: Request):
    """Render the home page."""
    return templates.TemplateResponse("pages/home.html", {"request": request})

@app.get("/stocks", response_class=HTMLResponse)
async def get_stocks(request: Request):
    """Render the stocks trading page."""
    return templates.TemplateResponse("pages/stocks.html", {"request": request})

@app.get("/risk-manager", response_class=HTMLResponse)
async def get_risk_manager(request: Request):
    """Render the risk manager page."""
    return templates.TemplateResponse("pages/risk-manager.html", {"request": request})

@app.get("/accounts", response_class=HTMLResponse)
async def get_accounts(request: Request):
    """Render the accounts management page."""
    return templates.TemplateResponse("pages/accounts.html", {"request": request})

@app.get("/{path:path}.map")
async def handle_sourcemap_requests(path: str):
    """Handle requests for sourcemaps (for development only)."""
    return Response(status_code=404)

@app.get("/api/orderbook/{symbol}")
async def get_order_book(symbol: str, depth: int = 10, asset_type: str = "stocks"):
    """
    Get the current order book for a symbol.
    
    Args:
        symbol: Trading symbol
        depth: Maximum number of price levels to return
        asset_type: Asset type (stocks, futures, etc.)
    
    Returns:
        Order book with bids and asks
    """
    # First try to get from matching engine (for multi-account orders)
    matching_book = matching_engine.get_order_book(symbol, depth)
    
    # Then get from the legacy order book
    legacy_book = order_book.get_order_book(
        depth=depth, 
        include_internal=False,
        asset_type=asset_type,
        symbol=symbol
    )
    
    # Combine the two order books
    combined_book = {
        "bids": matching_book.get("bids", []) + legacy_book.get("bids", []),
        "asks": matching_book.get("asks", []) + legacy_book.get("asks", []),
        "timestamp": time.time(),
        "symbol": symbol
    }
    
    # Sort bids in descending order (highest first)
    combined_book["bids"] = sorted(
        combined_book["bids"], 
        key=lambda x: float(x.get("price", 0)), 
        reverse=True
    )[:depth]
    
    # Sort asks in ascending order (lowest first)
    combined_book["asks"] = sorted(
        combined_book["asks"], 
        key=lambda x: float(x.get("price", 0))
    )[:depth]
    
    return combined_book

@app.get("/api/orderbook/{symbol}/internal")
async def get_internal_order_book(symbol: str, depth: int = 10, asset_type: str = "stocks"):
    """
    Get the internal (dark pool) order book for a symbol.
    
    Args:
        symbol: Trading symbol
        depth: Maximum number of price levels to return
        asset_type: Asset type (stocks, futures, etc.)
    
    Returns:
        Internal order book with bids and asks
    """
    # Get internal book from legacy system
    internal_book = order_book.get_order_book(
        depth=depth, 
        include_internal=True,
        asset_type=asset_type,
        symbol=symbol
    )
    
    return internal_book

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time updates."""
    await connection_manager.connect(websocket)
    try:
        while True:
            # Wait for messages from the client
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                message_type = message.get("type", "")
                
                if message_type == "subscribe":
                    # Client is subscribing to a channel
                    channel = message.get("channel", "")
                    
                    if channel:
                        # Set the subscription on the connection
                        if ":" in channel:
                            _, symbol = channel.split(":", 1)
                            websocket.subscribed_symbol = symbol
                            
                        # Add the connection to the channel
                        connection_manager.subscribe(websocket, channel)
                        
                        # Send confirmation
                        await websocket.send_json({
                            "type": "subscription",
                            "status": "success",
                            "channel": channel
                        })
                        
                elif message_type == "unsubscribe":
                    # Client is unsubscribing from a channel
                    channel = message.get("channel", "")
                    
                    if channel:
                        # Remove the connection from the channel
                        connection_manager.unsubscribe(websocket, channel)
                        
                        # Send confirmation
                        await websocket.send_json({
                            "type": "subscription",
                            "status": "unsubscribed",
                            "channel": channel
                        })
                        
                elif message_type == "ping":
                    # Client is sending a ping
                    await websocket.send_json({
                        "type": "pong",
                        "timestamp": time.time()
                    })
                    
            except json.JSONDecodeError:
                # Could not parse the message as JSON
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON message"
                })
                
    except WebSocketDisconnect:
        # Client disconnected
        connection_manager.disconnect(websocket)
    except Exception as e:
        # Other error
        logger.error(f"WebSocket error: {str(e)}")
        connection_manager.disconnect(websocket)
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
"""

# Standard library imports
import os
import json
import time
import asyncio
from typing import Dict, List, Any, Optional

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
from .order_book import order_book
from .websocket import connection_manager
from .api import (
    orders_router,
    orderbook_router,
    darkpool_router,
    market_router,
    positions_router
)
from .api.chatbot import router as chatbot_router

# Create FastAPI application
app = FastAPI(
    title="Order Entry System (OES)",
    description="High-performance order entry system for hedge funds",
    version="1.0.0"
)

# Mount static files
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Include routers
app.include_router(orders_router)
app.include_router(orderbook_router)
app.include_router(darkpool_router)
app.include_router(market_router)
app.include_router(positions_router)
app.include_router(chatbot_router, prefix="/api", tags=["chatbot"])

# Configure templates
templates = Jinja2Templates(directory="app/templates")

# Background task for matching orders
matching_task = None

# Background task for periodic order book broadcasts
broadcast_task = None 

# Background task for latency measurements
latency_task = None

@app.on_event("startup")
async def startup_event():
    """Initialize the application on startup."""
    # Start the order matching background task
    global matching_task
    matching_task = asyncio.create_task(periodic_order_matching())
    
    # Start the order book broadcast task
    global broadcast_task
    broadcast_task = asyncio.create_task(periodic_order_book_broadcast())
    
    # Start the latency measurement task
    global latency_task
    latency_task = asyncio.create_task(periodic_latency_broadcast())
    
    print("Order Entry System started successfully.")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on application shutdown."""
    # Cancel background tasks
    if matching_task:
        matching_task.cancel()
        
    if broadcast_task:
        broadcast_task.cancel()
        
    if latency_task:
        latency_task.cancel()

async def periodic_order_matching():
    """Background task to periodically match orders."""
    while True:
        try:
            # Match orders
            trades = await order_book.match_orders()
            
            # If trades were executed, broadcast them
            for trade in trades:
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
            
            # Small delay to prevent CPU hogging
            await asyncio.sleep(0.01)  # 10ms delay between matching attempts
            
        except asyncio.CancelledError:
            # Task is being cancelled
            break
        except Exception as e:
            print(f"Error in order matching: {e}")
            await asyncio.sleep(1)  # Longer delay on error

async def periodic_order_book_broadcast():
    """Background task to periodically broadcast the order book."""
    while True:
        try:
            # Get current order book
            book = order_book.get_order_book()
            
            # Broadcast to orderbook channel
            await connection_manager.broadcast(
                {"type": "orderbook", "data": book},
                channel="orderbook"
            )
            
            # Wait before next broadcast
            await asyncio.sleep(0.5)  # 500ms between broadcasts
            
        except asyncio.CancelledError:
            # Task is being cancelled
            break
        except Exception as e:
            print(f"Error in order book broadcast: {e}")
            await asyncio.sleep(1)  # Longer delay on error

async def periodic_latency_broadcast():
    """Background task to measure and broadcast system latency."""
    # Store last 10 latency measurements to calculate moving average
    latency_history = []
    max_history = 10
    
    while True:
        try:
            # Measure latency between API and database
            start_time = time.time() * 1000  # Convert to milliseconds
            
            # Make a simple Redis operation to measure round-trip time
            _ = order_book.redis.ping()
            
            end_time = time.time() * 1000  # Convert to milliseconds
            latency = end_time - start_time
            
            # Add to history and maintain max length
            latency_history.append(latency)
            if len(latency_history) > max_history:
                latency_history.pop(0)
                
            # Calculate average latency
            avg_latency = round(sum(latency_history) / len(latency_history), 3)
            
            # Broadcast to all websocket clients
            await connection_manager.broadcast({
                "type": "latency",
                "value": avg_latency
            })
            
            # Wait before next measurement
            await asyncio.sleep(1)  # 1 second between measurements
            
        except asyncio.CancelledError:
            # Task is being cancelled
            break
        except Exception as e:
            print(f"Error in latency broadcast: {e}")
            await asyncio.sleep(1)  # Longer delay on error

# API endpoints

@app.get("/api/status")
async def get_status():
    """API endpoint to check system status for connection monitoring."""
    return {"status": "online", "timestamp": time.time()}

@app.get("/")
async def get_home(request: Request):
    """Render the home page."""
    return templates.TemplateResponse("pages/home.html", {"request": request})

# Main routes

@app.get("/stocks", response_class=HTMLResponse)
async def get_stocks(request: Request):
    """Render the stocks trading page."""
    return templates.TemplateResponse("pages/stocks.html", {"request": request})

@app.get("/options", response_class=HTMLResponse)
async def get_options(request: Request):
    """Render the options trading page."""
    return templates.TemplateResponse("pages/options.html", {"request": request})

@app.get("/crypto", response_class=HTMLResponse)
async def get_crypto(request: Request):
    """Render the crypto trading page."""
    return templates.TemplateResponse("pages/crypto.html", {"request": request})

@app.get("/risk-manager", response_class=HTMLResponse)
async def get_risk_manager(request: Request):
    """Render the risk manager page."""
    return templates.TemplateResponse("pages/risk-manager.html", {"request": request})

@app.get("/{path:path}.map")
async def handle_sourcemap_requests(path: str):
    return Response(status_code=204)

# WebSocket endpoint for real-time updates
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await connection_manager.connect(websocket)
    print(f"[WS] New connection from {websocket.client}")
    
    try:
        # Send initial order book snapshot
        try:
            print("[WS] Fetching initial order book")
            book = order_book.get_order_book()
            print("[WS] Sending order book:", book)
            await websocket.send_json({
                "type": "orderbook",
                "data": book
            })
        except Exception as e:
            print(f"[WS] Error sending initial order book: {e}")
            await websocket.send_json({
                "type": "error",
                "message": "Failed to load initial order book"
            })
        
        # Process incoming messages
        while True:
            try:
                data = await websocket.receive_text()
                print("[WS] Received message:", data)
                
                # First check if it's HTML content
                if data.strip().startswith('<tr>'):
                    print("[WS] Detected HTML content, sending as text")
                    await websocket.send_text(data)
                    continue
                
                # Otherwise, treat as JSON
                print("[WS] Parsing as JSON")
                message = json.loads(data)
                print("[WS] Parsed JSON:", message)
                
                if message.get("action") == "subscribe":
                    channel = message.get("channel")
                    if channel:
                        await connection_manager.subscribe(websocket, channel)
                elif message.get("action") == "unsubscribe":
                    channel = message.get("channel")
                    if channel:
                        await connection_manager.unsubscribe(websocket, channel)
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Unknown action"
                    })
                    
            except json.JSONDecodeError as je:
                print(f"[WS] JSON decode error: {je}")
                print(f"[WS] Raw data causing error: {data}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid JSON message received"
                })
            except Exception as e:
                print(f"[WS] Error processing message: {e}")
                print(f"[WS] Error type: {type(e)}")
                print(f"[WS] Error details: {str(e)}")
                await websocket.send_json({
                    "type": "error",
                    "message": f"Error processing message: {str(e)}"
                })
                
    except WebSocketDisconnect:
        print(f"WebSocket disconnected: {websocket.client}")
    except Exception as e:
        print(f"Unexpected WebSocket error: {e}")
        try:
            await websocket.send_json({
                "type": "error",
                "message": "Internal server error"
            })
        except:
            pass
    finally:
        # Always clean up the connection
        connection_manager.disconnect(websocket)
        print(f"INFO:     connection closed")
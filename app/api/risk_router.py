from fastapi import APIRouter, HTTPException, status, Request, Query
from typing import List, Dict, Any, Optional
from fastapi.responses import HTMLResponse
import json
import logging
import time
from datetime import datetime

from app.matching_engine import matching_engine
from app.accounts import account_manager
from app.redis_client import redis_client

# Configure logging
logger = logging.getLogger(__name__)

risk_router = APIRouter(
    prefix="/api/risk",
    tags=["risk"],
)

@risk_router.get("/orders", response_class=HTMLResponse)
async def get_orders(asset_type: Optional[str] = None):
    """
    Get all orders for risk management, optionally filtered by asset type.
    Returns HTML for direct display in the risk manager table.
    """
    try:
        orders = []
        
        # Get all accounts to add trader information
        accounts_dict = {}
        for account in account_manager.get_all_accounts():
            accounts_dict[account.account_id] = account.to_dict()
        
        # Get all active orders from the matching engine
        all_active_orders = matching_engine.get_all_active_orders()
        
        # Add account data to orders
        for order in all_active_orders:
            account_id = order.get("account_id")
            
            # Create a copy of the order with additional fields
            order_with_trader = order.copy()
            
            # Add trader info if account exists
            if account_id in accounts_dict:
                account = accounts_dict[account_id]
                order_with_trader["trader"] = account.get("name", "Unknown")
            else:
                order_with_trader["trader"] = "Unknown"
            
            # Convert timestamp to readable format
            timestamp = order.get("timestamp", time.time())
            order_with_trader["time_display"] = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            
            orders.append(order_with_trader)
        
        # Check if we need to get orders from redis directly (backup approach)
        if len(orders) == 0:
            # Get all order IDs from Redis
            order_ids = []
            for key in redis_client.keys("oes:order:*"):
                order_id = key.split(":")[-1]
                order_ids.append(order_id)
            
            # Get order data for each ID
            for order_id in order_ids:
                order_key = f"oes:order:{order_id}"
                order_json = redis_client.get(order_key)
                if order_json:
                    try:
                        order = json.loads(order_json)
                        # Skip orders that aren't active
                        if order.get("status") not in ["open", "partially_filled"]:
                            continue
                            
                        # Add trader info
                        account_id = order.get("account_id")
                        if account_id in accounts_dict:
                            account = accounts_dict[account_id]
                            order["trader"] = account.get("name", "Unknown")
                        else:
                            order["trader"] = "Unknown"
                        
                        # Format timestamp
                        timestamp = order.get("timestamp", time.time())
                        order["time_display"] = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
                        
                        orders.append(order)
                    except json.JSONDecodeError:
                        continue
        
        # Filter by asset type if provided
        if asset_type and asset_type not in ["all"]:
            orders = [order for order in orders if order.get("asset_type") == asset_type]
        
        # Format orders into HTML table rows
        orders_html = ""
        for order in orders:
            cancel_button = f'<button class="btn btn-danger" onclick="cancelOrder(\'{order["id"]}\')">Cancel</button>' if order["status"] == "open" else ""
            
            orders_html += f"""
            <tr id="order-row-{order["id"]}">
                <td>{order["id"]}</td>
                <td>{order["symbol"]}</td>
                <td>{order.get("side", order.get("type", "Unknown"))}</td>
                <td>${order["price"]:.2f}</td>
                <td>{order["quantity"]}</td>
                <td>{order["status"]}</td>
                <td>{order.get("created_at", order.get("time_display", "Unknown"))}</td>
                <td>{order.get("account_name", order.get("trader", "Unknown"))}</td>
                <td>{cancel_button}</td>
            </tr>
            """
        
        # If no orders, show a message
        if not orders:
            orders_html = "<tr><td colspan='9'>No orders found</td></tr>"
            
        return orders_html
    except Exception as e:
        logger.error(f"Error getting orders for risk management: {str(e)}", exc_info=True)
        return "<tr><td colspan='9'>Error loading orders</td></tr>"

@risk_router.get("/alerts", response_class=HTMLResponse)
async def get_risk_alerts():
    """
    Get risk alerts for the risk manager.
    Returns HTML for direct display in the risk alerts container.
    """
    try:
        # You can implement more sophisticated risk alerting here
        # For now, we'll return some sample alerts
        current_time = time.time()
        
        alerts = [
            {
                "id": "alert-1",
                "level": "info",
                "timestamp": current_time - 300,
                "title": "Daily Loss Limit Warning",
                "description": "Account ACCT001 is approaching 80% of daily loss limit."
            },
            {
                "id": "alert-2",
                "level": "warning",
                "timestamp": current_time - 1200,
                "title": "Large Order Detected",
                "description": "Order for 5,000 shares of AAPL exceeds normal size for this account."
            },
            {
                "id": "alert-3",
                "level": "critical",
                "timestamp": current_time - 3600,
                "title": "Position Limit Exceeded",
                "description": "Account ACCT003 has exceeded position limit for TSLA."
            }
        ]
        
        # Sort alerts by timestamp (most recent first)
        alerts.sort(key=lambda x: x["timestamp"], reverse=True)
        
        # Generate HTML for alerts
        html = ""
        for alert in alerts:
            alert_id = alert.get("id")
            level = alert.get("level", "info")
            timestamp = alert.get("timestamp")
            title = alert.get("title", "Alert")
            description = alert.get("description", "")
            
            # Format timestamp
            time_display = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
            
            # Format the HTML
            html += f"""
            <div class="alert-item {level}" id="{alert_id}">
                <div class="alert-timestamp">{time_display}</div>
                <div class="alert-title">{title}</div>
                <div class="alert-description">{description}</div>
            </div>
            """
        
        # If no alerts, show a message
        if not alerts:
            html = "<div class='alert-item info'>No alerts at this time</div>"
            
        return html
    except Exception as e:
        logger.error(f"Error getting risk alerts: {str(e)}", exc_info=True)
        return "<div class='alert-item warning'>Error loading alerts</div>" 
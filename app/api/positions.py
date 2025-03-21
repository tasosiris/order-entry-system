"""
Positions API Endpoints

Provides endpoints for retrieving and managing trading positions across different asset types.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Any, Optional
import time
import random

router = APIRouter(
    prefix="/api/positions",
    tags=["positions"],
    responses={404: {"description": "Not found"}},
)

# Sample positions data for each asset type
POSITIONS = {
    "stocks": [
        {"id": "pos-1", "symbol": "AAPL", "quantity": 100, "entry_price": 182.52, "current_price": 185.45, "pnl": 293.00, "pnl_percent": 1.60},
        {"id": "pos-2", "symbol": "MSFT", "quantity": 50, "entry_price": 415.75, "current_price": 417.32, "pnl": 78.50, "pnl_percent": 0.38},
        {"id": "pos-3", "symbol": "GOOGL", "quantity": 30, "entry_price": 174.80, "current_price": 176.35, "pnl": 46.50, "pnl_percent": 0.89}
    ],
    "futures": [
        {"id": "pos-4", "symbol": "ES", "quantity": 2, "entry_price": 5218.50, "current_price": 5235.25, "pnl": 335.00, "pnl_percent": 0.32},
        {"id": "pos-5", "symbol": "NQ", "quantity": 1, "entry_price": 18245.75, "current_price": 18322.50, "pnl": 76.75, "pnl_percent": 0.42},
        {"id": "pos-6", "symbol": "CL", "quantity": 3, "entry_price": 78.35, "current_price": 77.92, "pnl": -129.00, "pnl_percent": -0.55}
    ],
    "options": [
        {"id": "pos-7", "symbol": "AAPL 190 Call", "quantity": 10, "entry_price": 3.25, "current_price": 3.50, "pnl": 250.00, "pnl_percent": 7.69},
        {"id": "pos-8", "symbol": "SPY 450 Put", "quantity": 5, "entry_price": 2.45, "current_price": 2.15, "pnl": -150.00, "pnl_percent": -12.24}
    ],
    "crypto": [
        {"id": "pos-9", "symbol": "BTC/USD", "quantity": 0.5, "entry_price": 61250.00, "current_price": 62415.75, "pnl": 582.88, "pnl_percent": 1.90},
        {"id": "pos-10", "symbol": "ETH/USD", "quantity": 2.5, "entry_price": 3275.50, "current_price": 3450.25, "pnl": 436.88, "pnl_percent": 5.33}
    ]
}

@router.get("/{asset_type}")
async def get_positions(asset_type: str):
    """
    Get current positions for a specific asset type.
    
    Args:
        asset_type: One of "stocks", "futures", "options", or "crypto"
    
    Returns:
        HTML formatted table rows for positions of the specified asset type.
    """
    if asset_type not in POSITIONS:
        return f"<tr><td colspan='6'>No {asset_type} positions found</td></tr>"
    
    # Add some small random changes to simulate live data
    positions = []
    for position in POSITIONS[asset_type]:
        pos_copy = position.copy()
        
        # Add minor price movements
        price_change_pct = random.uniform(-0.25, 0.25) / 100  # ±0.25% change
        orig_price = pos_copy["current_price"]
        new_price = round(orig_price * (1 + price_change_pct), 2)
        pos_copy["current_price"] = new_price
        
        # Recalculate P&L
        price_diff = new_price - pos_copy["entry_price"]
        pos_copy["pnl"] = round(price_diff * pos_copy["quantity"], 2)
        pos_copy["pnl_percent"] = round((price_diff / pos_copy["entry_price"]) * 100, 2)
        
        positions.append(pos_copy)
    
    # Create HTML response for HTMX
    html_rows = ""
    for pos in positions:
        pnl_class = "positive" if pos["pnl"] >= 0 else "negative"
        pnl_sign = "+" if pos["pnl"] > 0 else ""
        
        html_rows += f"""
        <tr>
            <td>{pos["symbol"]}</td>
            <td>{pos["quantity"]}</td>
            <td>${pos["entry_price"]}</td>
            <td>${pos["current_price"]}</td>
            <td class="{pnl_class}">{pnl_sign}${abs(pos["pnl"])}</td>
            <td class="{pnl_class}">{pnl_sign}{pos["pnl_percent"]}%</td>
            <td>
                <button class="btn-close-position" data-position-id="{pos["id"]}">Close</button>
            </td>
        </tr>
        """
    
    return html_rows 
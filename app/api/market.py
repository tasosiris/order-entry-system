"""
Market Data API Endpoints

Provides endpoints for retrieving market data for various asset types.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Any, Optional
import time
import random
from app.utils.logging import log_request_response

router = APIRouter(
    prefix="/api/market",
    tags=["market data"],
    responses={404: {"description": "Not found"}},
)

# Sample market data for crypto
CRYPTO_MARKET_DATA = [
    {
        "symbol": "BTC/USD",
        "price": 62451.18,
        "change_24h": 3.04,
        "volume_24h": 32500000000,
        "market_cap": 1228000000000
    },
    {
        "symbol": "ETH/USD",
        "price": 3456.78,
        "change_24h": 2.15,
        "volume_24h": 18900000000,
        "market_cap": 420000000000
    },
    {
        "symbol": "XRP/USD",
        "price": 0.59,
        "change_24h": -1.24,
        "volume_24h": 2100000000,
        "market_cap": 30000000000
    },
    {
        "symbol": "SOL/USD",
        "price": 124.35,
        "change_24h": 4.78,
        "volume_24h": 3400000000,
        "market_cap": 52500000000
    },
    {
        "symbol": "DOT/USD",
        "price": 7.84,
        "change_24h": -0.32,
        "volume_24h": 850000000,
        "market_cap": 9800000000
    },
    {
        "symbol": "ADA/USD",
        "price": 0.42,
        "change_24h": 1.18,
        "volume_24h": 720000000,
        "market_cap": 15300000000
    },
    {
        "symbol": "DOGE/USD",
        "price": 0.125,
        "change_24h": 5.67,
        "volume_24h": 1600000000,
        "market_cap": 18000000000
    }
]

@router.get("/crypto")
async def get_crypto_market_data() -> List[Dict[str, Any]]:
    """
    Get current market data for cryptocurrencies.
    
    This endpoint returns price, 24h change, volume, and market cap for popular crypto pairs.
    Values are slightly randomized on each request to simulate market movement.
    
    Returns:
        List of cryptocurrency market data objects
    """
    # Create a copy of the data with slight randomization to simulate live market data
    result = []
    timestamp = time.time()
    
    for crypto in CRYPTO_MARKET_DATA:
        # Add small random changes to simulate live data
        price_change = random.uniform(-0.5, 0.5) / 100  # ±0.5% change
        
        crypto_copy = crypto.copy()
        crypto_copy["price"] = round(crypto["price"] * (1 + price_change), 2)
        crypto_copy["change_24h"] = round(crypto["change_24h"] + random.uniform(-0.2, 0.2), 2)
        crypto_copy["timestamp"] = timestamp
        
        result.append(crypto_copy)
    
    # HTML response for HTMX
    html_rows = ""
    for crypto in result:
        change_class = "positive" if crypto["change_24h"] > 0 else "negative"
        change_sign = "+" if crypto["change_24h"] > 0 else ""
        
        html_rows += f"""
        <tr>
            <td>{crypto["symbol"]}</td>
            <td>${crypto["price"]}</td>
            <td class="{change_class}">{change_sign}{crypto["change_24h"]}%</td>
            <td>${int(crypto["volume_24h"]/1000000)}M</td>
            <td>${int(crypto["market_cap"]/1000000000)}B</td>
        </tr>
        """
    
    # Only use the logging utility, remove direct prints
    log_request_response("GET", "/api/market/crypto", 200, len(html_rows))
    
    return html_rows 
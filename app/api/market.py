"""
Market Data API Endpoints

Provides endpoints for retrieving market data for various asset types.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Any, Optional
import time
import random
import json
import os
import aiohttp
import asyncio
from datetime import datetime
from app.utils.logging import log_request_response

router = APIRouter(
    prefix="/api/market",
    tags=["market data"],
    responses={404: {"description": "Not found"}},
)

# Cache for stock market data to prevent excessive API calls
STOCK_MARKET_CACHE = {
    "last_updated": 0,
    "cache_duration": 3600,  # 1 hour cache
    "data": {}
}

# Top 100 NYSE company tickers by market cap
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

# Historical date for external order book data
HISTORICAL_DATE = "2023-12-15"  # Format: YYYY-MM-DD

async def fetch_stock_data():
    """
    Fetch stock data from a free API for the top 100 NYSE companies.
    Uses Alpha Vantage API (limited to 5 API calls per minute on free tier).
    """
    current_time = time.time()
    
    # Return cached data if it's still fresh
    if (current_time - STOCK_MARKET_CACHE["last_updated"] < STOCK_MARKET_CACHE["cache_duration"] and
            STOCK_MARKET_CACHE["data"]):
        return STOCK_MARKET_CACHE["data"]
    
    # API key should be in environment variables
    api_key = os.getenv("ALPHA_VANTAGE_API_KEY", "demo")
    
    # This would be the production code, but it's limited by API rate limits
    # Instead we'll generate mock data for most tickers and use the API sparingly
    
    # Get data for a few tickers from the API to have some real data
    api_tickers = TOP_100_NYSE_TICKERS[:5]  # First 5 tickers
    
    all_stock_data = {}
    
    # Generate mock data for all tickers first
    for ticker in TOP_100_NYSE_TICKERS:
        base_price = random.uniform(50, 500)
        change_percent = random.uniform(-5, 5)
        volume = random.randint(100000, 10000000)
        
        all_stock_data[ticker] = {
            "symbol": ticker,
            "price": round(base_price, 2),
            "change_percent": round(change_percent, 2),
            "volume": volume,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "is_mock": True
        }
    
    # Now try to get real data for a few tickers if possible
    try:
        async with aiohttp.ClientSession() as session:
            for ticker in api_tickers:
                # Only make API calls if we haven't updated recently to avoid hitting rate limits
                if current_time - STOCK_MARKET_CACHE["last_updated"] > 300:  # 5 minutes
                    try:
                        # Global quote endpoint is more efficient for just current price
                        url = f"https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol={ticker}&apikey={api_key}"
                        async with session.get(url) as response:
                            if response.status == 200:
                                data = await response.json()
                                
                                # Check if we got valid data
                                if "Global Quote" in data and data["Global Quote"]:
                                    quote = data["Global Quote"]
                                    
                                    price = float(quote.get("05. price", 0))
                                    prev_close = float(quote.get("08. previous close", 0))
                                    change_percent = 0
                                    
                                    if prev_close > 0:
                                        change_percent = round(((price - prev_close) / prev_close) * 100, 2)
                                    
                                    all_stock_data[ticker] = {
                                        "symbol": ticker,
                                        "price": price,
                                        "change_percent": change_percent,
                                        "volume": int(quote.get("06. volume", 0)),
                                        "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                        "is_mock": False
                                    }
                                    
                                    # Add a delay to avoid hitting API rate limits
                                    await asyncio.sleep(12)  # Wait 12 seconds between calls
                    except Exception as e:
                        log_request_response("API", f"Alpha Vantage API for {ticker}", 500, str(e))
    except Exception as e:
        log_request_response("API", "Alpha Vantage API session", 500, str(e))
    
    # Update cache
    STOCK_MARKET_CACHE["data"] = all_stock_data
    STOCK_MARKET_CACHE["last_updated"] = current_time
    
    return all_stock_data

@router.get("/stocks")
async def get_stock_market_data() -> Dict[str, Any]:
    """
    Get current market data for stocks.
    
    This endpoint returns price, change percentage, and volume for top NYSE stocks.
    Some data may be mock data due to API rate limitations.
    
    Returns:
        Dictionary with stock market data
    """
    try:
        stock_data = await fetch_stock_data()
        
        # Logging the request
        log_request_response("GET", "/api/market/stocks", 200, f"Returned data for {len(stock_data)} stocks")
        
        return {
            "stocks": list(stock_data.values()),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        log_request_response("GET", "/api/market/stocks", 500, str(e))
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/tickers")
async def get_stock_tickers() -> Dict[str, Any]:
    """
    Get list of top 100 NYSE stock tickers for autocomplete.
    
    Returns:
        Dictionary with ticker symbols
    """
    return {
        "tickers": TOP_100_NYSE_TICKERS
    }

@router.get("/historical/{ticker}")
async def get_historical_data(ticker: str) -> Dict[str, Any]:
    """
    Get historical data for a specific stock ticker on the historical date.
    
    Returns:
        Dictionary with historical stock data
    """
    # Generate mock historical data
    if ticker not in TOP_100_NYSE_TICKERS:
        raise HTTPException(status_code=404, detail=f"Ticker {ticker} not found in top 100 NYSE stocks")
    
    # Generate mock data for the historical date
    base_price = random.uniform(50, 500)
    open_price = base_price * (1 + random.uniform(-0.01, 0.01))
    high_price = base_price * (1 + random.uniform(0.01, 0.05))
    low_price = base_price * (1 - random.uniform(0.01, 0.05))
    close_price = base_price * (1 + random.uniform(-0.03, 0.03))
    volume = random.randint(100000, 10000000)
    
    return {
        "symbol": ticker,
        "date": HISTORICAL_DATE,
        "open": round(open_price, 2),
        "high": round(high_price, 2),
        "low": round(low_price, 2),
        "close": round(close_price, 2),
        "volume": volume
    }

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
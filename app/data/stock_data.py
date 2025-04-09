"""
Local stock data with natural language processing support.
"""
from datetime import datetime
from fuzzywuzzy import fuzz
import logging

# Configure logging
logger = logging.getLogger("oes.data.stocks")

# Local stock data
STOCK_DATA = {
    "AAPL": {
        "name": "Apple Inc.",
        "current_price": 175.50,
        "52_week_high": 199.62,
        "52_week_low": 124.17,
        "market_cap": 2.7e12,
        "pe_ratio": 28.5,
        "dividend_yield": 0.52,
        "beta": 1.28,
        "risk_level": "Medium",
        "sector": "Technology",
        "industry": "Consumer Electronics",
        "volume": 55000000,
        "avg_volume": 58000000,
        "day_change": 0.75,
        "analysts_rating": "Buy"
    },
    "MSFT": {
        "name": "Microsoft Corporation",
        "current_price": 415.22,
        "52_week_high": 420.82,
        "52_week_low": 275.37,
        "market_cap": 3.1e12,
        "pe_ratio": 36.8,
        "dividend_yield": 0.73,
        "beta": 0.95,
        "risk_level": "Low",
        "sector": "Technology",
        "industry": "Software",
        "volume": 22000000,
        "avg_volume": 25000000,
        "day_change": 1.2,
        "analysts_rating": "Strong_buy"
    },
    "GOOGL": {
        "name": "Alphabet Inc.",
        "current_price": 142.65,
        "52_week_high": 153.78,
        "52_week_low": 88.92,
        "market_cap": 1.8e12,
        "pe_ratio": 24.2,
        "dividend_yield": 0.0,
        "beta": 1.05,
        "risk_level": "Medium",
        "sector": "Technology",
        "industry": "Internet Services",
        "volume": 28000000,
        "avg_volume": 30000000,
        "day_change": -0.5,
        "analysts_rating": "Buy"
    }
}

# Company name to ticker mapping for fuzzy matching
COMPANY_TO_TICKER = {
    "Apple": "AAPL",
    "Microsoft": "MSFT",
    "Alphabet": "GOOGL",
    "Google": "GOOGL",
    "Amazon": "AMZN",
    "Meta": "META",
    "Facebook": "META",
    "Tesla": "TSLA",
    "NVIDIA": "NVDA",
    "Netflix": "NFLX",
    "Adobe": "ADBE",
    "Intel": "INTC",
    "AMD": "AMD",
    "Cisco": "CSCO",
    "Oracle": "ORCL",
}

def get_best_ticker_match(query):
    """Find the best matching ticker symbol for a given company name."""
    best_match = None
    highest_ratio = 0
    
    # Check direct ticker match first
    if query.upper() in STOCK_DATA:
        return query.upper()
    
    # Try fuzzy matching against company names
    for company, ticker in COMPANY_TO_TICKER.items():
        ratio = fuzz.ratio(query.lower(), company.lower())
        if ratio > highest_ratio and ratio > 60:  # Minimum threshold of 60%
            highest_ratio = ratio
            best_match = ticker
    
    return best_match

def get_stock_info(symbol_or_name):
    """
    Get stock information for a given symbol or company name from local data.
    """
    try:
        # Try to find the best matching ticker
        ticker = get_best_ticker_match(symbol_or_name)
        if not ticker or ticker not in STOCK_DATA:
            return None

        # Get data from local database
        data = STOCK_DATA[ticker].copy()
        data["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data["data_source"] = "local"
        return data

    except Exception as e:
        logger.error(f"Error in get_stock_info for {symbol_or_name}: {str(e)}")
        return None

def format_stock_info(symbol_or_name):
    """Format stock information into a readable string with natural language."""
    info = get_stock_info(symbol_or_name)
    if not info:
        return f"Sorry, I couldn't find information for '{symbol_or_name}'. Please try a different company name or ticker symbol."
    
    # Format market cap in billions/trillions
    market_cap = info["market_cap"]
    if market_cap >= 1e12:
        market_cap_str = f"${market_cap/1e12:.2f}T"
    else:
        market_cap_str = f"${market_cap/1e9:.2f}B"
    
    # Handle PE ratio formatting
    pe_ratio = info['pe_ratio']
    if pe_ratio is None:
        pe_ratio_str = 'N/A'
    else:
        pe_ratio_str = f"{pe_ratio:.2f}"
    
    # Create a natural language response
    response = f"""
Here's the latest information for {info['name']} ({symbol_or_name.upper() if len(symbol_or_name) <= 5 else ''}):

📈 Current Trading:
• Price: ${info['current_price']:.2f}
• Today's Change: {info['day_change']:.2f}%
• Volume: {info['volume']:,} (Avg: {info['avg_volume']:,})

📊 Key Statistics:
• Market Cap: {market_cap_str}
• P/E Ratio: {pe_ratio_str}
• 52-Week Range: ${info['52_week_low']:.2f} - ${info['52_week_high']:.2f}
• Beta: {info['beta']:.2f}
• Risk Level: {info['risk_level']}

💰 Investment Info:
• Dividend Yield: {info['dividend_yield']:.2f}%
• Analyst Rating: {info['analysts_rating']}

🏢 Company Info:
• Sector: {info['sector']}
• Industry: {info['industry']}

Last Updated: {info['last_updated']}
Data Source: {info.get('data_source', 'Unknown')}
"""
    return response

# Example usage:
# print(format_stock_info("apple"))  # Works with company name
# print(format_stock_info("AAPL"))   # Works with ticker
# print(format_stock_info("microsoft"))  # Case insensitive 
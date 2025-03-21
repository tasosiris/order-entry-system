import os
import time
import logging
from typing import Dict, Any, Tuple, Optional

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("oes.risk")

# Risk parameters
MAX_ORDER_SIZE = float(os.getenv("MAX_ORDER_SIZE", "1000000"))  # Maximum order size
MIN_ORDER_SIZE = float(os.getenv("MIN_ORDER_SIZE", "0.01"))     # Minimum order size
MAX_PRICE = float(os.getenv("MAX_PRICE", "1000000"))           # Maximum price
MIN_PRICE = float(os.getenv("MIN_PRICE", "0.01"))              # Minimum price
PRICE_DEVIATION_PCT = float(os.getenv("PRICE_DEVIATION_PCT", "10.0"))  # Maximum deviation % from last price

class RiskManager:
    """Risk management system for the Order Entry System."""
    
    def __init__(self):
        self.last_trade_prices = {}  # Symbol -> last trade price
    
    def update_last_price(self, symbol: str, price: float):
        """Update the last trade price for a symbol."""
        self.last_trade_prices[symbol] = price
        
    def validate_order(self, order: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validate an order against risk parameters.
        
        Args:
            order: The order to validate containing symbol, price, quantity
            
        Returns:
            Tuple of (is_valid, reason)
        """
        symbol = order.get("symbol", "")
        price = float(order.get("price", 0))
        quantity = float(order.get("quantity", 0))
        order_type = order.get("type", "")
        
        # Log the order for auditing
        logger.info(f"Validating order: {order}")
        
        # Check order size limits
        if quantity <= 0:
            return False, "Order quantity must be positive"
        
        if quantity < MIN_ORDER_SIZE:
            return False, f"Order quantity {quantity} is below minimum {MIN_ORDER_SIZE}"
            
        if quantity > MAX_ORDER_SIZE:
            return False, f"Order quantity {quantity} exceeds maximum {MAX_ORDER_SIZE}"
        
        # For limit orders, check price limits
        if order_type.lower() == "limit":
            if price <= 0:
                return False, "Limit price must be positive"
                
            if price < MIN_PRICE:
                return False, f"Price {price} is below minimum {MIN_PRICE}"
                
            if price > MAX_PRICE:
                return False, f"Price {price} exceeds maximum {MAX_PRICE}"
            
            # Check price deviation from last trade (if available)
            last_price = self.last_trade_prices.get(symbol)
            if last_price:
                deviation_pct = abs(price - last_price) / last_price * 100
                if deviation_pct > PRICE_DEVIATION_PCT:
                    return False, f"Price deviation {deviation_pct:.2f}% exceeds maximum {PRICE_DEVIATION_PCT}%"
        
        # Order passed all risk checks
        return True, None
    
    def log_execution(self, trade: Dict[str, Any]):
        """Log a trade execution for compliance tracking."""
        logger.info(f"EXECUTION: {trade}")
        
        # Update last trade price
        if "symbol" in trade and "price" in trade:
            self.update_last_price(trade["symbol"], float(trade["price"]))

# Create a singleton instance
risk_manager = RiskManager() 
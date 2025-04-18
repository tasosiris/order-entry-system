import os
import time
import logging
from typing import Dict, Any, Tuple, Optional, List

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
        self.max_order_value = 1000000  # $1M max order value
        self.max_order_quantity = 100000  # 100K units max
        self.min_order_quantity = 1  # 1 unit min
        self.min_order_price = 0.01  # $0.01 min price
        
        # Account-specific risk limits
        self.account_limits = {
            "default": {
                "max_position_value": 1000000,  # $1M max position value
                "max_order_value": 100000,      # $100K max order value
                "max_loss_pct": 5.0,            # 5% max daily loss
                "max_leverage": 1.0,            # 1x max leverage (no margin)
                "enabled": True                  # Account active status
            }
        }
        
        # Symbol-specific risk limits
        self.symbol_limits = {
            "default": {
                "price_volatility_limit_pct": 5.0,  # 5% max price volatility
                "max_position_qty": 10000,          # 10K max position quantity
                "enabled": True                     # Symbol trading status
            }
        }
    
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
        account_id = order.get("account_id", "")
        
        # Log the order for auditing
        logger.info(f"Validating order: {order}")
        
        # Check account status
        if not self.is_account_enabled(account_id):
            return False, f"Account {account_id} is disabled or not authorized to trade"
        
        # Check symbol status
        if not self.is_symbol_enabled(symbol):
            return False, f"Trading in {symbol} is currently disabled"
        
        # Check order size limits
        if quantity <= 0:
            return False, "Order quantity must be positive"
        
        if quantity < MIN_ORDER_SIZE:
            return False, f"Order quantity {quantity} is below minimum {MIN_ORDER_SIZE}"
            
        if quantity > MAX_ORDER_SIZE:
            return False, f"Order quantity {quantity} exceeds maximum {MAX_ORDER_SIZE}"
        
        # Check account-specific order quantity limits
        account_max_qty = self.get_account_limit(account_id, "max_position_qty", symbol)
        if quantity > account_max_qty:
            return False, f"Order quantity {quantity} exceeds account limit {account_max_qty}"
        
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
                
                # Get account-specific or default price deviation limit
                max_deviation = self.get_account_limit(account_id, "price_volatility_limit_pct", symbol)
                
                if deviation_pct > max_deviation:
                    return False, f"Price deviation {deviation_pct:.2f}% exceeds maximum {max_deviation}%"
        
        # Check order value limits
        order_value = price * quantity
        max_order_value = self.get_account_limit(account_id, "max_order_value")
        
        if order_value > max_order_value:
            return False, f"Order value ${order_value:.2f} exceeds maximum ${max_order_value:.2f}"
        
        # Order passed all risk checks
        return True, None
    
    def log_execution(self, trade: Dict[str, Any]):
        """Log a trade execution for compliance tracking."""
        logger.info(f"EXECUTION: {trade}")
        
        # Update last trade price
        if "symbol" in trade and "price" in trade:
            self.update_last_price(trade["symbol"], float(trade["price"]))

    def check_order(self, order_data):
        """
        Check if an order passes risk management rules.
        Returns (is_approved, reason)
        """
        try:
            # First check using the more comprehensive validate_order
            if "account_id" in order_data:
                is_valid, reason = self.validate_order(order_data)
                if not is_valid:
                    return False, reason
            
            # Extract order details
            quantity = float(order_data.get('quantity', 0))
            price = float(order_data.get('price', 0))
            
            # Check minimum quantity
            if quantity < self.min_order_quantity:
                return False, f"Order quantity {quantity} is below minimum of {self.min_order_quantity}"
                
            # Check maximum quantity
            if quantity > self.max_order_quantity:
                return False, f"Order quantity {quantity} exceeds maximum of {self.max_order_quantity}"
                
            # Check minimum price for limit orders
            if order_data.get('order_type') == 'limit' and price < self.min_order_price:
                return False, f"Order price ${price} is below minimum of ${self.min_order_price}"
                
            # Check maximum order value
            order_value = quantity * price
            if order_value > self.max_order_value:
                return False, f"Order value ${order_value} exceeds maximum of ${self.max_order_value}"
                
            return True, "Order approved"
            
        except Exception as e:
            return False, f"Error checking order: {str(e)}"
    
    def is_account_enabled(self, account_id: str) -> bool:
        """Check if an account is enabled for trading."""
        # Get account limits or use default
        limits = self.account_limits.get(account_id, self.account_limits.get("default", {}))
        return limits.get("enabled", True)
    
    def is_symbol_enabled(self, symbol: str) -> bool:
        """Check if a symbol is enabled for trading."""
        # Get symbol limits or use default
        limits = self.symbol_limits.get(symbol, self.symbol_limits.get("default", {}))
        return limits.get("enabled", True)
    
    def get_account_limit(self, account_id: str, limit_name: str, symbol: Optional[str] = None) -> float:
        """Get an account-specific limit value."""
        # Get account limits or use default
        account_limits = self.account_limits.get(account_id, self.account_limits.get("default", {}))
        
        # If symbol-specific limit is requested
        if symbol:
            # Check if account has symbol-specific limits
            symbol_overrides = account_limits.get("symbol_overrides", {})
            if symbol in symbol_overrides and limit_name in symbol_overrides[symbol]:
                return float(symbol_overrides[symbol][limit_name])
            
            # Check global symbol limits
            symbol_limits = self.symbol_limits.get(symbol, self.symbol_limits.get("default", {}))
            if limit_name in symbol_limits:
                return float(symbol_limits[limit_name])
        
        # Return account limit or a sensible default
        return float(account_limits.get(limit_name, self.get_default_limit(limit_name)))
    
    def get_default_limit(self, limit_name: str) -> float:
        """Get a default limit value for a given limit type."""
        defaults = {
            "max_position_value": 1000000,
            "max_order_value": 100000,
            "max_loss_pct": 5.0,
            "max_leverage": 1.0,
            "price_volatility_limit_pct": 5.0,
            "max_position_qty": 10000
        }
        return float(defaults.get(limit_name, 0))
    
    def set_account_limit(self, account_id: str, limit_name: str, value: float) -> bool:
        """Set an account-specific risk limit."""
        # Ensure account exists in limits dictionary
        if account_id not in self.account_limits:
            self.account_limits[account_id] = self.account_limits["default"].copy()
        
        # Set the limit
        self.account_limits[account_id][limit_name] = float(value)
        return True
    
    def set_symbol_limit(self, symbol: str, limit_name: str, value: float) -> bool:
        """Set a symbol-specific risk limit."""
        # Ensure symbol exists in limits dictionary
        if symbol not in self.symbol_limits:
            self.symbol_limits[symbol] = self.symbol_limits["default"].copy()
        
        # Set the limit
        self.symbol_limits[symbol][limit_name] = float(value)
        return True
    
    def check_position_limit(self, symbol: str, quantity: float, direction: str, account_id: Optional[str] = None) -> Tuple[bool, str]:
        """Check if a new position would exceed position limits"""
        # Get max position quantity limit
        max_qty = 10000  # Default
        
        if account_id:
            max_qty = self.get_account_limit(account_id, "max_position_qty", symbol)
        
        if quantity > max_qty:
            return False, f"Position size {quantity} exceeds maximum {max_qty}"
        
        return True, "Position limit check passed"
        
    def check_trading_status(self, symbol: str) -> Tuple[bool, str]:
        """Check if trading is allowed for the symbol"""
        if not self.is_symbol_enabled(symbol):
            return False, f"Trading in {symbol} is currently disabled"
        
        return True, "Trading is allowed"
        
    def check_price_bands(self, symbol: str, price: float) -> Tuple[bool, str]:
        """Check if price is within allowed bands"""
        # Get last price
        last_price = self.last_trade_prices.get(symbol)
        if not last_price:
            return True, "No previous price available for comparison"
        
        # Calculate deviation
        deviation_pct = abs(price - last_price) / last_price * 100
        
        # Get volatility limit (default 5%)
        volatility_limit = 5.0
        symbol_limits = self.symbol_limits.get(symbol, self.symbol_limits.get("default", {}))
        if "price_volatility_limit_pct" in symbol_limits:
            volatility_limit = float(symbol_limits["price_volatility_limit_pct"])
        
        # Check if price is within bands
        if deviation_pct > volatility_limit:
            return False, f"Price ${price} deviates by {deviation_pct:.2f}% from last price ${last_price}"
        
        return True, "Price is within bands"
    
    def get_accounts_summary(self) -> List[Dict[str, Any]]:
        """Get a summary of all accounts with their risk limits."""
        accounts = []
        
        for account_id, limits in self.account_limits.items():
            if account_id == "default":
                continue
                
            account_info = {
                "account_id": account_id,
                "limits": limits.copy(),
                "status": "enabled" if limits.get("enabled", True) else "disabled"
            }
            
            accounts.append(account_info)
            
        return accounts
    
    def get_symbols_summary(self) -> List[Dict[str, Any]]:
        """Get a summary of all symbols with their risk limits."""
        symbols = []
        
        for symbol, limits in self.symbol_limits.items():
            if symbol == "default":
                continue
                
            symbol_info = {
                "symbol": symbol,
                "limits": limits.copy(),
                "status": "enabled" if limits.get("enabled", True) else "disabled",
                "last_price": self.last_trade_prices.get(symbol, None)
            }
            
            symbols.append(symbol_info)
            
        return symbols

# Create a singleton instance
risk_manager = RiskManager() 
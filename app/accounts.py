"""
Trading Account Management System

This module implements the trading account management functionality, including:
- Multiple trading accounts with unique identifiers
- Balance management for each account
- Trade authorization based on account balances
- Cross-account trading limitations

Each account has a fixed amount of money and accounts cannot access or trade with
each other's money. Only the risk manager can manage and view all accounts.
"""

import os
import json
import time
import logging
import uuid
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime

# Redis client for persistent storage
from app.redis_client import redis_client

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("oes.accounts")

# Redis keys for account data
ACCOUNTS_KEY = "oes:accounts"
ACCOUNT_TRANSACTIONS_KEY_PREFIX = "oes:accounts:transactions:"
ACCOUNT_POSITIONS_KEY_PREFIX = "oes:accounts:positions:"

class TradingAccount:
    """Trading account model representing a single trader's account."""
    
    def __init__(self, account_id: str, name: str, balance: float, 
                 account_type: str = "standard", risk_level: str = "medium"):
        """
        Initialize a trading account.
        
        Args:
            account_id: Unique identifier for the account
            name: Display name for the account
            balance: Initial balance in USD
            account_type: Account type (standard, institutional, etc.)
            risk_level: Risk tolerance level (low, medium, high)
        """
        self.account_id = account_id
        self.name = name
        self.balance = float(balance)
        self.account_type = account_type
        self.risk_level = risk_level
        self.created_at = datetime.now().isoformat()
        self.updated_at = self.created_at
        self.active = True
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert account to dictionary representation."""
        return {
            "account_id": self.account_id,
            "name": self.name,
            "balance": self.balance,
            "account_type": self.account_type,
            "risk_level": self.risk_level,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "active": self.active
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TradingAccount':
        """Create account instance from dictionary data."""
        account = cls(
            account_id=data["account_id"],
            name=data["name"],
            balance=data["balance"],
            account_type=data.get("account_type", "standard"),
            risk_level=data.get("risk_level", "medium")
        )
        account.created_at = data.get("created_at", account.created_at)
        account.updated_at = data.get("updated_at", account.updated_at)
        account.active = data.get("active", True)
        return account

class AccountManager:
    """Manages all trading accounts in the system."""
    
    def __init__(self):
        """Initialize the account manager."""
        self.redis = redis_client
        
        # Seed sample accounts if none exist
        if not self.get_all_accounts():
            self._seed_sample_accounts()
    
    def create_account(self, name: str, initial_balance: float, 
                      account_type: str = "standard", risk_level: str = "medium") -> TradingAccount:
        """
        Create a new trading account.
        
        Args:
            name: Account name
            initial_balance: Starting balance in USD
            account_type: Type of account
            risk_level: Risk tolerance level
            
        Returns:
            Newly created account
        """
        account_id = f"acc-{uuid.uuid4()}"
        account = TradingAccount(
            account_id=account_id,
            name=name,
            balance=initial_balance,
            account_type=account_type,
            risk_level=risk_level
        )
        
        # Save to Redis
        self._save_account(account)
        
        # Record initial deposit transaction
        self.record_transaction(
            account_id=account_id,
            transaction_type="deposit",
            amount=initial_balance,
            description="Initial account funding"
        )
        
        logger.info(f"Created new account: {account_id} - {name} with balance ${initial_balance}")
        return account
    
    def get_account(self, account_id: str) -> Optional[TradingAccount]:
        """Get an account by ID."""
        account_json = self.redis.hget(ACCOUNTS_KEY, account_id)
        if not account_json:
            return None
        
        account_data = json.loads(account_json)
        return TradingAccount.from_dict(account_data)
    
    def get_all_accounts(self) -> List[TradingAccount]:
        """Get all trading accounts."""
        accounts = []
        account_json_dict = self.redis.hgetall(ACCOUNTS_KEY)
        
        for account_json in account_json_dict.values():
            account_data = json.loads(account_json)
            accounts.append(TradingAccount.from_dict(account_data))
        
        return accounts
    
    def update_account_balance(self, account_id: str, new_balance: float) -> bool:
        """
        Update an account's balance.
        
        Args:
            account_id: Account to update
            new_balance: New balance amount
            
        Returns:
            Success status
        """
        account = self.get_account(account_id)
        if not account:
            return False
        
        old_balance = account.balance
        account.balance = float(new_balance)
        account.updated_at = datetime.now().isoformat()
        
        # Save updated account
        self._save_account(account)
        
        logger.info(f"Updated account {account_id} balance: ${old_balance} -> ${new_balance}")
        return True
    
    def adjust_account_balance(self, account_id: str, amount: float, 
                              transaction_type: str, description: str = "") -> bool:
        """
        Adjust an account's balance and record the transaction.
        
        Args:
            account_id: Account to adjust
            amount: Amount to adjust (positive or negative)
            transaction_type: Type of transaction (trade, deposit, withdrawal, fee)
            description: Description of the transaction
            
        Returns:
            Success status
        """
        account = self.get_account(account_id)
        if not account:
            return False
        
        # Calculate new balance
        old_balance = account.balance
        new_balance = old_balance + amount
        
        # Update account balance
        account.balance = new_balance
        account.updated_at = datetime.now().isoformat()
        
        # Save updated account
        self._save_account(account)
        
        # Record the transaction
        self.record_transaction(
            account_id=account_id,
            transaction_type=transaction_type,
            amount=amount,
            description=description,
            balance_after=new_balance
        )
        
        if amount >= 0:
            log_msg = f"Increased account {account_id} balance by ${amount}: ${old_balance} -> ${new_balance}"
        else:
            log_msg = f"Decreased account {account_id} balance by ${abs(amount)}: ${old_balance} -> ${new_balance}"
            
        logger.info(log_msg)
        return True
    
    def update_after_trade(self, buy_account_id: str, sell_account_id: str, symbol: str, 
                          quantity: float, price: float) -> Tuple[bool, bool]:
        """
        Update both buyer and seller accounts after a trade is executed.
        This handles both the money transfer and position updates.
        
        Args:
            buy_account_id: ID of the buying account
            sell_account_id: ID of the selling account
            symbol: Symbol being traded
            quantity: Quantity being traded
            price: Price of the trade
            
        Returns:
            Tuple of (buyer_success, seller_success)
        """
        trade_value = quantity * price
        
        # Update buyer's balance and position
        buyer_description = f"Buy {quantity} {symbol} @ ${price}"
        buyer_balance_success = self.adjust_account_balance(
            account_id=buy_account_id,
            amount=-trade_value,
            transaction_type='trade',
            description=buyer_description
        )
        
        if buyer_balance_success:
            # Update buyer's position (increase)
            self.update_position(
                account_id=buy_account_id,
                symbol=symbol,
                quantity_change=quantity,
                price=price,
                transaction_type='buy'
            )
        
        # Update seller's balance and position
        seller_description = f"Sell {quantity} {symbol} @ ${price}"
        seller_balance_success = self.adjust_account_balance(
            account_id=sell_account_id,
            amount=trade_value,
            transaction_type='trade',
            description=seller_description
        )
        
        if seller_balance_success:
            # Update seller's position (decrease)
            self.update_position(
                account_id=sell_account_id,
                symbol=symbol,
                quantity_change=-quantity,
                price=price,
                transaction_type='sell'
            )
        
        return (buyer_balance_success, seller_balance_success)
    
    def record_transaction(self, account_id: str, transaction_type: str, 
                          amount: float, description: str = "", balance_after: Optional[float] = None) -> Dict[str, Any]:
        """
        Record a transaction for an account.
        
        Args:
            account_id: Account ID
            transaction_type: Type of transaction
            amount: Transaction amount
            description: Transaction description
            balance_after: Balance after transaction
            
        Returns:
            Transaction record
        """
        transaction_id = f"txn-{uuid.uuid4()}"
        timestamp = time.time()
        
        if balance_after is None:
            account = self.get_account(account_id)
            balance_after = account.balance if account else 0
        
        transaction = {
            "id": transaction_id,
            "account_id": account_id,
            "type": transaction_type,
            "amount": amount,
            "balance_after": balance_after,
            "description": description,
            "timestamp": timestamp,
            "created_at": datetime.fromtimestamp(timestamp).isoformat()
        }
        
        # Store in Redis
        transactions_key = f"{ACCOUNT_TRANSACTIONS_KEY_PREFIX}{account_id}"
        self.redis.lpush(transactions_key, json.dumps(transaction))
        
        return transaction
    
    def get_account_transactions(self, account_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent transactions for an account."""
        transactions_key = f"{ACCOUNT_TRANSACTIONS_KEY_PREFIX}{account_id}"
        transaction_jsons = self.redis.lrange(transactions_key, 0, limit - 1)
        
        transactions = []
        for txn_json in transaction_jsons:
            transactions.append(json.loads(txn_json))
        
        return transactions
    
    def can_trade(self, account_id: str, symbol: str, order_type: str, 
                 price: float, quantity: float) -> Tuple[bool, str]:
        """
        Check if an account has sufficient balance to place a trade.
        
        Args:
            account_id: Account ID
            symbol: Trading symbol
            order_type: buy or sell
            price: Order price
            quantity: Order quantity
            
        Returns:
            Tuple of (can_trade, reason)
        """
        account = self.get_account(account_id)
        if not account:
            return False, "Account not found"
        
        if not account.active:
            return False, "Account is not active"
        
        # For buy orders, check if the account has enough balance
        if order_type.lower() == 'buy':
            order_value = price * quantity
            if order_value > account.balance:
                return False, f"Insufficient funds (${account.balance} available, ${order_value} required)"
        
        # For sell orders, check if the account has the position
        if order_type.lower() == 'sell':
            position = self.get_position(account_id, symbol)
            if not position or position['quantity'] < quantity:
                return False, "Insufficient position to sell"
        
        return True, "Trade authorized"
    
    def update_position(self, account_id: str, symbol: str, quantity_change: float, 
                       price: float, transaction_type: str) -> Dict[str, Any]:
        """
        Update an account's position in a specific symbol.
        
        Args:
            account_id: Account ID
            symbol: Trading symbol
            quantity_change: Change in quantity (positive for buys, negative for sells)
            price: Trade price
            transaction_type: buy or sell
            
        Returns:
            Updated position data
        """
        positions_key = f"{ACCOUNT_POSITIONS_KEY_PREFIX}{account_id}"
        position_json = self.redis.hget(positions_key, symbol)
        
        if position_json:
            position = json.loads(position_json)
            old_quantity = position['quantity']
            avg_price = position['avg_price']
            
            # Update quantity
            new_quantity = old_quantity + quantity_change
            
            # Calculate new average price for buys
            if quantity_change > 0 and transaction_type.lower() == 'buy':
                position_value = old_quantity * avg_price
                new_value = quantity_change * price
                total_value = position_value + new_value
                if new_quantity > 0:
                    avg_price = total_value / new_quantity
                else:
                    avg_price = 0
            
            position['quantity'] = new_quantity
            position['avg_price'] = avg_price
            position['last_updated'] = time.time()
        else:
            # Create new position
            position = {
                'symbol': symbol,
                'quantity': quantity_change,
                'avg_price': price,
                'account_id': account_id,
                'last_updated': time.time()
            }
        
        # Save position
        self.redis.hset(positions_key, symbol, json.dumps(position))
        return position
    
    def get_position(self, account_id: str, symbol: str) -> Optional[Dict[str, Any]]:
        """Get an account's position in a specific symbol."""
        positions_key = f"{ACCOUNT_POSITIONS_KEY_PREFIX}{account_id}"
        position_json = self.redis.hget(positions_key, symbol)
        
        if not position_json:
            return None
        
        return json.loads(position_json)
    
    def get_all_positions(self, account_id: str) -> List[Dict[str, Any]]:
        """Get all positions for an account."""
        positions_key = f"{ACCOUNT_POSITIONS_KEY_PREFIX}{account_id}"
        position_json_dict = self.redis.hgetall(positions_key)
        
        positions = []
        for position_json in position_json_dict.values():
            positions.append(json.loads(position_json))
        
        return positions
    
    def _save_account(self, account: TradingAccount) -> bool:
        """Save account data to Redis."""
        account_json = json.dumps(account.to_dict())
        return self.redis.hset(ACCOUNTS_KEY, account.account_id, account_json)
    
    def _seed_sample_accounts(self) -> None:
        """Seed initial sample accounts."""
        samples = [
            {"name": "Trading Account 1", "balance": 1000000, "type": "institutional", "risk": "high"},
            {"name": "Trading Account 2", "balance": 500000, "type": "standard", "risk": "medium"},
            {"name": "Trading Account 3", "balance": 250000, "type": "standard", "risk": "low"},
            {"name": "Trading Account 4", "balance": 100000, "type": "personal", "risk": "medium"},
            {"name": "Trading Account 5", "balance": 50000, "type": "personal", "risk": "low"},
        ]
        
        for sample in samples:
            self.create_account(
                name=sample["name"],
                initial_balance=sample["balance"],
                account_type=sample["type"],
                risk_level=sample["risk"]
            )
        
        logger.info(f"Seeded {len(samples)} sample accounts")

# Create a singleton instance
account_manager = AccountManager() 
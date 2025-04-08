from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

class OrderResponse(BaseModel):
    """
    Response model for order-related API endpoints
    """
    success: bool
    message: str
    order_id: Optional[str] = None
    
class OrderCreate(BaseModel):
    """
    Model for creating new orders
    """
    symbol: str = Field(..., description="Trading symbol")
    side: str = Field(..., description="Order side (buy/sell)")
    price: float = Field(..., description="Order price")
    quantity: float = Field(..., gt=0, description="Order quantity")
    asset_type: str = "stocks"
    tif: str = "day"
    order_type: str = "limit"
    internal: bool = False
    status: Optional[str] = "open" 
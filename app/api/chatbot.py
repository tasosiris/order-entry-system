from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from ..llm import financial_llm
from ..data.stock_data import get_stock_info, format_stock_info

router = APIRouter()

class ChatMessage(BaseModel):
    message: str

@router.post("/chat")
async def chat(message: ChatMessage):
    try:
        # Check if it's a ticker information request
        if "info" in message.message.lower() or "price" in message.message.lower():
            # Extract ticker symbol
            words = message.message.split()
            for word in words:
                if word.isupper() and len(word) <= 5:  # Basic ticker symbol check
                    # Get information directly from local stock data
                    response = format_stock_info(word)
                    return {"response": response}
            
            return {"response": "Please specify a valid ticker symbol."}
        
        # For other messages, use the LLM directly
        response = financial_llm.generate_response(message.message)
        return {"response": response}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) 
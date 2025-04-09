from transformers import AutoModelForCausalLM, AutoTokenizer
import torch
import json
import os
from .data.stock_data import get_stock_info, format_stock_info

class FinancialLLM:
    def __init__(self):
        self.model = None
        self.tokenizer = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.initialize_model()

    def initialize_model(self):
        """Initialize the local LLM model."""
        try:
            # Using a smaller model that can run locally
            model_name = "gpt2"  # You can replace this with a more suitable model
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            self.model = AutoModelForCausalLM.from_pretrained(model_name)
            self.model.to(self.device)
        except Exception as e:
            print(f"Error initializing model: {e}")
            self.model = None

    def generate_response(self, prompt):
        """Generate a response using the local LLM."""
        if not self.model:
            return "Model not initialized. Please check the logs for errors."

        try:
            inputs = self.tokenizer(prompt, return_tensors="pt").to(self.device)
            outputs = self.model.generate(
                **inputs,
                max_length=200,
                num_return_sequences=1,
                temperature=0.7,
                do_sample=True
            )
            response = self.tokenizer.decode(outputs[0], skip_special_tokens=True)
            return response
        except Exception as e:
            print(f"Error generating response: {e}")
            return "Error generating response. Please try again."

    def get_ticker_info(self, symbol):
        """Get information about a specific ticker symbol."""
        # First try to get information from our local database
        info = get_stock_info(symbol)
        if info:
            return format_stock_info(symbol)
        
        # If not found in local database, use the LLM to generate a response
        prompt = f"Provide a brief financial summary for {symbol} including current price, 52-week high/low, market cap, and P/E ratio. Format the response in a clear, concise way."
        return self.generate_response(prompt)

# Create a singleton instance
financial_llm = FinancialLLM() 
def log_request_response(method: str, endpoint: str, response_status: int, body_length: int):
    """Utility function for consistent API logging"""
    print(f"INFO:root:Request: {method} {endpoint} - Body: Empty")
    print(f"INFO:root:Response: {response_status} - Body length: {body_length} characters") 
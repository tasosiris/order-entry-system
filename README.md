# Order Entry System (OES)

A high-performance order entry system optimized for hedge funds and proprietary trading firms, designed for low-latency execution and real-time order management.

## Features

- **Ultra-low-latency order processing**: Asynchronous request handling with FastAPI
- **Real-time order book management**: Using Redis sorted sets for efficient price-time priority
- **Atomic order matching**: Implemented with Redis Lua scripts
- **Advanced risk management**: Position limits, exposure monitoring, and real-time risk alerts
- **WebSocket API**: For real-time order book and trade updates
- **Modern UI**: Responsive design with real-time updates and interactive order book visualization
- **Order management**: Edit, cancel, and monitor orders in real-time
- **Trade notifications**: Audio and visual alerts for executed trades
- **Account management**: Multiple trading accounts with balance tracking

## Tech Stack

- **Backend**: FastAPI (Python) - Asynchronous API framework
- **Database**: Redis - In-memory data store for ultra-low latency
- **Frontend**: 
  - HTML5 + CSS3 - Modern, responsive design
  - JavaScript (ES6+) - Client-side interactivity
  - WebSocket - Real-time updates
- **Deployment**: Uvicorn - High-performance ASGI server

## Installation

### Prerequisites

- Python 3.8+
- Redis 6.0+
- Node.js 14+ (for development)

### Setup

1. Clone the repository
```bash
git clone https://github.com/yourusername/order-entry-system.git
cd order-entry-system
```

2. Create a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Make sure Redis is running
```bash
# Start Redis locally
redis-server

# Or connect to an existing Redis instance by configuring .env file:
# REDIS_HOST=your-redis-host
# REDIS_PORT=your-redis-port
# REDIS_PASSWORD=your-redis-password
```

## Running the Application

Start the OES with:

```bash
python -m app.run
```

Alternatively, you can use uvicorn directly:

```bash
uvicorn app.main:app --reload --port 8001
```

The application will be available at `http://localhost:8001`.

## Using the System

### Web Interface

1. Open your browser to `http://localhost:8001`
2. Select a trading account from the dropdown
3. Enter a stock symbol (e.g., AAPL) and click Select
4. Use the order entry form to submit trades:
   - Choose between Market or Limit orders
   - Set price (for limit orders)
   - Enter quantity
   - Select time-in-force
   - Click Buy or Sell
5. Monitor your orders in the "My Orders" panel
6. View the real-time order book and trade information

### API Usage

#### Order Submission

```bash
curl -X POST "http://localhost:8001/api/accounts/{account_id}/orders/direct" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "buy",
    "symbol": "AAPL",
    "price": 150.00,
    "quantity": 10,
    "asset_type": "stocks",
    "tif": "day",
    "internal": true
  }'
```

#### Get Account Orders

```bash
curl "http://localhost:8001/api/accounts/{account_id}/orders"
```

#### Get All Orders

```bash
curl "http://localhost:8001/api/accounts/orders/all"
```

#### Edit Order

```bash
curl -X POST "http://localhost:8001/api/orders/{order_id}/edit" \
  -H "Content-Type: application/json" \
  -d '{
    "price": 151.00,
    "quantity": 15
  }'
```

#### Cancel Order

```bash
curl -X POST "http://localhost:8001/api/accounts/{account_id}/orders/{order_id}/cancel"
```

### WebSocket API

Connect to the WebSocket endpoint at `/ws` and send a JSON message to subscribe to updates:

```json
{
  "type": "subscribe",
  "channel": "oes:notifications"
}
```

Available channels:
- `oes:notifications` - All system notifications
- `oes:orderbook` - Order book updates
- `oes:trades` - Trade executions
- `oes:risk` - Risk alerts

## Development

### File Structure

- `app/main.py` - Main application entry point
- `app/order_book.py` - Order book implementation
- `app/matching_engine.py` - Order matching engine
- `app/redis_client.py` - Redis interface
- `app/risk_management.py` - Risk management system
- `app/accounts.py` - Account management
- `app/websocket.py` - WebSocket connection management
- `app/api/` - API endpoint routers
- `app/templates/` - HTML templates
- `app/static/` - Static assets (CSS, JS)
- `app/utils/` - Utility functions

### Adding New Features

1. **New API Endpoints**: Add to existing routers or create new ones in `app/api/`
2. **UI Enhancements**: Modify templates in `app/templates/` and static files in `app/static/`
3. **Order Types**: Extend the matching engine in `app/matching_engine.py`
4. **Risk Rules**: Add to the risk management system in `app/risk_management.py`
5. **Account Features**: Extend `app/accounts.py` for new account functionality

## Performance Tuning

For optimal performance:

1. Increase system file limits
```bash
ulimit -n 65535
```

2. Configure Redis for high throughput in redis.conf:
```
maxclients 10000
maxmemory 4gb
maxmemory-policy allkeys-lru
appendonly no
```

3. Run the application with multiple workers:
```bash
uvicorn app.main:app --workers 4 --host 0.0.0.0 --port 8001
```

## Troubleshooting

- **High Latency**: Check Redis connection and configuration
- **Order Matching Issues**: Enable DEBUG logging to track order flow
- **WebSocket Disconnections**: Verify network settings and proxy configurations
- **Risk Alerts**: Check account positions and exposure limits
- **Order Updates**: Verify WebSocket connection and subscription status

## License

[MIT License](LICENSE)

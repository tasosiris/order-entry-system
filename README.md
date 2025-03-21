<<<<<<< HEAD
# OES
=======
# Order Entry System (OES)

A high-performance order entry system optimized for hedge funds and proprietary trading firms, designed for low-latency execution and real-time order management.

## Features

- **Ultra-low-latency order processing**: Asynchronous request handling with FastAPI
- **Real-time order book management**: Using Redis sorted sets for efficient price-time priority
- **Atomic order matching**: Implemented with Redis Lua scripts
- **Risk management**: Order validation, size limits, and price deviation checks
- **WebSocket API**: For real-time order book and trade updates
- **Responsive UI**: Built with minimal HTML and HTMX for dynamic updates without page reloads

## Tech Stack

- **Backend**: FastAPI (Python) - Asynchronous API framework
- **Database**: Redis - In-memory data store for ultra-low latency
- **Frontend**: HTML + HTMX - Lightweight, no heavy JavaScript frameworks
- **Deployment**: Uvicorn - High-performance ASGI server

## Installation

### Prerequisites

- Python 3.8+
- Redis 6.0+

### Setup

1. Clone the repository
```bash
git clone <repository-url>
cd order-entry-system
```

2. Install dependencies
```bash
pip install -r requirements.txt
```

3. Make sure Redis is running
```bash
# Start Redis locally
redis-server

# Or connect to an existing Redis instance by setting environment variables:
# export REDIS_HOST=your-redis-host
# export REDIS_PORT=your-redis-port
# export REDIS_PASSWORD=your-redis-password
```

## Running the Application

Start the OES with:

```bash
uvicorn app.main:app --reload
```

The application will be available at `http://localhost:8000`.

For production deployments, use multiple workers:

```bash
uvicorn app.main:app --workers 4 --host 0.0.0.0 --port 8000
```

## API Reference

### Order Submission

```
POST /api/orders
```

Example request body:
```json
{
  "type": "buy",
  "symbol": "BTC-USD",
  "price": 50000.00,
  "quantity": 0.5
}
```

### Order Book Retrieval

```
GET /api/orderbook?depth=10
```

### Order Status

```
GET /api/orders/{order_id}
```

### Order Cancellation

```
DELETE /api/orders/{order_id}
```

### Recent Trades

```
GET /api/trades?limit=20
```

## WebSocket API

Connect to the WebSocket endpoint at `/ws` to receive real-time updates.

Subscribe to specific channels:

```json
{
  "action": "subscribe",
  "channel": "orderbook"
}
```

Available channels:
- `orderbook` - Order book updates
- `trades` - All trades
- `trades:{symbol}` - Trades for a specific symbol

## Performance Tuning

For optimal performance:

1. Increase system file limits
```bash
ulimit -n 65535
```

2. Configure Redis for high throughput
```
maxclients 10000
maxmemory 4gb
maxmemory-policy allkeys-lru
appendonly no
```

3. Run Uvicorn with multiple workers (typically CPU cores * 2)

## License

[MIT License](LICENSE) 
>>>>>>> 3dd09ab (Initial commit: Order Entry System)

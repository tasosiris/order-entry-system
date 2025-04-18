/**
 * Order Book Module
 * 
 * Handles displaying and updating both internal and external order books.
 */

export class OrderBook {
    constructor(options = {}) {
        this.symbol = null;
        this.depth = options.depth || 10;
        this.refreshInterval = options.refreshInterval || 5000;
        this.assetType = options.assetType || 'stocks';
        this.showInternal = options.showInternal || false;
        this.autoRefresh = options.autoRefresh || true;
        this.sampleData = options.sampleData || null;
        
        // DOM elements
        this.externalBook = document.getElementById('external-book');
        this.internalBook = document.getElementById('internal-book');
        this.activeOrders = document.getElementById('active-orders-body');
        this.selectedTicker = document.getElementById('selected-ticker');
        this.lastOrderTime = document.getElementById('last-order-time');
        this.symbolInput = document.getElementById('symbol');
        this.tradingSymbolInput = document.getElementById('trading-symbol');
        
        // Initialize WebSocket connection
        this.initializeWebSocket();
        
        // Initialize event listeners
        this.initializeEvents();
        
        // If sample data is provided, use it
        if (this.sampleData) {
            this.useSampleData();
        }
        
        // Clear books initially
        this.clearOrderBooks();
    }
    
    initializeEvents() {
        // Handle symbol input changes
        if (this.symbolInput) {
            this.symbolInput.addEventListener('change', (e) => {
                const symbol = e.target.value.toUpperCase();
                if (symbol) {
                    this.setSymbol(symbol);
                }
            });
            
            // Handle symbol input blur (when user clicks away)
            this.symbolInput.addEventListener('blur', (e) => {
                const symbol = e.target.value.toUpperCase();
                if (symbol) {
                    this.setSymbol(symbol);
                }
            });
            
            // Handle Enter key press
            this.symbolInput.addEventListener('keypress', (e) => {
                if (e.key === 'Enter') {
                    const symbol = e.target.value.toUpperCase();
                    if (symbol) {
                        this.setSymbol(symbol);
                    }
                }
            });
        }
        
        // Listen for order book refresh events (triggered when trades occur)
        window.addEventListener('orderBookRefresh', () => {
            if (this.symbol) {
                console.log('Order book refresh event received, reloading orders for:', this.symbol);
                // Force clear and reload the order book
                this.clearOrderBooks();
                this.loadOrders(this.symbol);
            }
        });
        
        // Listen for specific WebSocket events
        window.addEventListener('tradeUpdate', (event) => {
            const tradeData = event.detail;
            if (Array.isArray(tradeData) && tradeData.length > 0) {
                // Check if any trade matches our current symbol
                const matchingTrade = tradeData.find(trade => trade.symbol === this.symbol);
                if (matchingTrade) {
                    console.log('Trade update for current symbol detected:', matchingTrade);
                    // Force reload orders for this symbol
                    this.loadOrders(this.symbol);
                }
            }
        });
    }
    
    initializeWebSocket() {
        this.ws = new WebSocket(`ws://${window.location.host}/ws`);
        this.ws.onmessage = (event) => this.handleWebSocketMessage(event);
        this.ws.onclose = () => setTimeout(() => this.initializeWebSocket(), 1000);
    }
    
    handleWebSocketMessage(event) {
        try {
            const data = JSON.parse(event.data);
            
            // Handle different types of messages
            if (data.type === 'orderbook' && data.symbol === this.symbol) {
                // Regular order book update
                this.updateOrderBooks(data.data.bids, data.data.asks, 'external');
                this.updateTimestamp();
            } 
            else if (data.type === 'trade' && data.data.symbol === this.symbol) {
                // When a trade occurs, reload the full order book and active orders
                console.log('Trade for current symbol detected, reloading order book');
                this.loadOrders(this.symbol);
            }
            else if (data.type === 'trade_executed' && data.symbol === this.symbol) {
                // When a trade is executed for our symbol, reload everything
                console.log('Trade executed for current symbol, reloading order book');
                this.loadOrders(this.symbol);
            }
            else if (data.type === 'orders_updated') {
                // Generic orders updated notification
                if (this.symbol) {
                    console.log('Orders updated notification received, reloading order book');
                    this.loadOrders(this.symbol);
                }
            }
            else if (data.type === 'orderbook_updates' && data.symbol === this.symbol) {
                // Specific order book update notification
                console.log('Order book update notification received');
                this.loadOrders(this.symbol);
            }
        } catch (error) {
            console.error('Error processing WebSocket message:', error);
        }
    }
    
    useSampleData() {
        if (this.sampleData.bids && this.sampleData.asks) {
            this.updateOrderBooks(this.sampleData.bids, this.sampleData.asks);
        }
    }
    
    setSymbol(symbol) {
        if (!symbol) return;
        
        this.symbol = symbol;
        
        // Update UI elements
        if (this.selectedTicker) {
            this.selectedTicker.textContent = symbol;
        }
        
        if (this.tradingSymbolInput) {
            this.tradingSymbolInput.value = symbol;
        }
        
        // Clear existing orders
        this.clearOrderBooks();
        
        // Load orders immediately
        this.loadOrders(symbol);
        
        // Start auto-refresh if enabled
        if (this.autoRefresh) {
            if (this.refreshTimer) {
                clearInterval(this.refreshTimer);
            }
            this.refreshTimer = setInterval(() => this.loadOrders(symbol), this.refreshInterval);
        }
    }
    
    async loadOrders(symbol) {
        try {
            // Fetch external orders
            const externalResponse = await fetch(`/api/orderbook/${symbol}?depth=${this.depth}&asset_type=${this.assetType}`);
            const externalData = await externalResponse.json();
            
            // Fetch internal orders if enabled
            let internalData = { bids: [], asks: [] };
            if (this.showInternal) {
                const internalResponse = await fetch(`/api/orderbook/${symbol}/internal?depth=${this.depth}&asset_type=${this.assetType}`);
                internalData = await internalResponse.json();
            }
            
            // Update the order books
            this.updateOrderBooks(externalData.bids, externalData.asks, 'external');
            if (this.showInternal) {
                this.updateOrderBooks(internalData.bids, internalData.asks, 'internal');
            }
            
            // Update active orders
            this.loadActiveOrders(symbol);
            
            // Update timestamp
            this.updateTimestamp();
            
        } catch (error) {
            console.error('Error loading orders:', error);
            // If error, use sample data if available
            if (this.sampleData) {
                this.useSampleData();
            }
        }
    }
    
    clearOrderBooks() {
        if (this.externalBook) {
            const bidsBody = this.externalBook.querySelector('.bids-body');
            const asksBody = this.externalBook.querySelector('.asks-body');
            if (bidsBody) bidsBody.innerHTML = '';
            if (asksBody) asksBody.innerHTML = '';
        }
        
        if (this.internalBook) {
            const bidsBody = this.internalBook.querySelector('.bids-body');
            const asksBody = this.internalBook.querySelector('.asks-body');
            if (bidsBody) bidsBody.innerHTML = '';
            if (asksBody) asksBody.innerHTML = '';
        }
        
        if (this.activeOrders) {
            this.activeOrders.innerHTML = '';
        }
    }
    
    updateOrderBooks(bids, asks, bookType = 'external') {
        const book = bookType === 'external' ? this.externalBook : this.internalBook;
        if (!book) return;
        
        const bidsBody = book.querySelector('.bids-body');
        const asksBody = book.querySelector('.asks-body');
        
        if (bidsBody) {
            bidsBody.innerHTML = this.formatOrders(bids, 'bid');
        }
        
        if (asksBody) {
            asksBody.innerHTML = this.formatOrders(asks, 'ask');
        }
    }
    
    formatOrders(orders, side) {
        if (!orders || orders.length === 0) {
            return `<tr><td colspan="4">No ${side === 'bid' ? 'buy' : 'sell'} orders</td></tr>`;
        }
        
        return orders.map(order => {
            const total = (order.price * order.quantity).toFixed(2);
            const time = new Date(order.timestamp).toLocaleTimeString();
            return `
                <tr>
                    <td>$${parseFloat(order.price).toFixed(2)}</td>
                    <td>${order.quantity}</td>
                    <td>$${total}</td>
                    <td>${time}</td>
                </tr>
            `;
        }).join('');
    }
    
    async loadActiveOrders(symbol) {
        try {
            const response = await fetch(`/api/orders/open?asset_type=${this.assetType}&symbol=${symbol}`);
            const orders = await response.json();
            
            if (this.activeOrders) {
                if (!orders || orders.length === 0) {
                    this.activeOrders.innerHTML = '<tr><td colspan="7">No active orders</td></tr>';
                    return;
                }
                
                this.activeOrders.innerHTML = orders.map(order => {
                    const total = (order.price * order.quantity).toFixed(2);
                    const time = new Date(order.timestamp).toLocaleTimeString();
                    return `
                        <tr>
                            <td>${order.id.substring(0, 8)}...</td>
                            <td class="${order.type === 'buy' ? 'buy-price' : 'sell-price'}">${order.type.toUpperCase()}</td>
                            <td>$${parseFloat(order.price).toFixed(2)}</td>
                            <td>${order.quantity}</td>
                            <td>$${total}</td>
                            <td>${time}</td>
                            <td>
                                <button class="edit-btn" onclick="window.orderBook.openEditModal('${order.id}')">Edit</button>
                                <button class="cancel-btn" onclick="window.orderBook.cancelOrder('${order.id}')">Cancel</button>
                            </td>
                        </tr>
                    `;
                }).join('');
            }
        } catch (error) {
            console.error('Error loading active orders:', error);
            if (this.activeOrders) {
                this.activeOrders.innerHTML = '<tr><td colspan="7">Error loading orders</td></tr>';
            }
        }
    }
    
    updateTimestamp() {
        if (this.lastOrderTime) {
            this.lastOrderTime.textContent = new Date().toLocaleTimeString();
        }
    }
    
    async openEditModal(orderId) {
        const modal = document.getElementById('order-modal');
        const orderDetails = document.getElementById('order-details');
        const editForm = document.getElementById('edit-order-form');
        const priceInput = document.getElementById('edit-order-price');
        const quantityInput = document.getElementById('edit-order-quantity');
        const orderIdInput = document.getElementById('edit-order-id');
        
        try {
            const response = await fetch(`/api/orders/${orderId}`);
            const order = await response.json();
            
            orderDetails.innerHTML = `
                <div class="order-detail">Order ID: ${order.id}</div>
                <div class="order-detail">Symbol: ${order.symbol}</div>
                <div class="order-detail">Type: ${order.type.toUpperCase()}</div>
                <div class="order-detail">Current Price: $${parseFloat(order.price).toFixed(2)}</div>
                <div class="order-detail">Current Quantity: ${order.quantity}</div>
            `;
            
            priceInput.value = order.price;
            quantityInput.value = order.quantity;
            orderIdInput.value = order.id;
            
            modal.style.display = 'block';
            
            editForm.onsubmit = async (e) => {
                e.preventDefault();
                await this.updateOrder(order.id, {
                    price: parseFloat(priceInput.value),
                    quantity: parseInt(quantityInput.value)
                });
                modal.style.display = 'none';
            };
            
            document.querySelectorAll('.close-modal').forEach(btn => {
                btn.onclick = () => modal.style.display = 'none';
            });
            
        } catch (error) {
            console.error('Error loading order details:', error);
        }
    }
    
    async updateOrder(orderId, updates) {
        try {
            const response = await fetch(`/api/orders/${orderId}/edit`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updates)
            });
            
            if (response.ok) {
                // Reload both the order book and active orders
                await this.loadOrders(this.symbol);
                // Show success message
                const messageDiv = document.getElementById('edit-order-message');
                if (messageDiv) {
                    messageDiv.className = 'message success';
                    messageDiv.textContent = 'Order updated successfully';
                    setTimeout(() => {
                        messageDiv.textContent = '';
                    }, 3000);
                }
            } else {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to update order');
            }
        } catch (error) {
            console.error('Error updating order:', error);
            // Show error message
            const messageDiv = document.getElementById('edit-order-message');
            if (messageDiv) {
                messageDiv.className = 'message error';
                messageDiv.textContent = error.message || 'Failed to update order';
                setTimeout(() => {
                    messageDiv.textContent = '';
                }, 3000);
            }
        }
    }
    
    async cancelOrder(orderId) {
        try {
            const response = await fetch(`/api/orders/${orderId}/cancel`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' }
            });
            
            if (response.ok) {
                // Reload both the order book and active orders
                await this.loadOrders(this.symbol);
                
                // Show a temporary notification
                const notification = document.createElement('div');
                notification.className = 'notification success';
                notification.textContent = 'Order cancelled successfully';
                document.body.appendChild(notification);
                
                // Remove notification after 3 seconds
                setTimeout(() => {
                    notification.remove();
                }, 3000);
            } else {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to cancel order');
            }
        } catch (error) {
            console.error('Error canceling order:', error);
            
            // Show error notification
            const notification = document.createElement('div');
            notification.className = 'notification error';
            notification.textContent = error.message || 'Failed to cancel order';
            document.body.appendChild(notification);
            
            // Remove notification after 3 seconds
            setTimeout(() => {
                notification.remove();
            }, 3000);
        }
    }

    /**
     * Get current best bid and ask prices
     * @returns {Object} Object with bid and ask prices
     */
    getCurrentPrice() {
        const orderBook = this.lastOrderBookData || { bids: [], asks: [] };
        
        // Get best bid and ask
        const bestBid = orderBook.bids && orderBook.bids.length > 0 ? 
            parseFloat(orderBook.bids[0].price) : null;
            
        const bestAsk = orderBook.asks && orderBook.asks.length > 0 ? 
            parseFloat(orderBook.asks[0].price) : null;
            
        return {
            bid: bestBid,
            ask: bestAsk,
            spread: bestBid && bestAsk ? bestAsk - bestBid : null,
            mid: bestBid && bestAsk ? (bestBid + bestAsk) / 2 : null
        };
    }

    /**
     * Clean up resources
     */
}

export default OrderBook; 
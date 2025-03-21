/**
 * Order Book Module
 * 
 * Handles displaying and updating both internal and external order books.
 */

class OrderBook {
    constructor(options = {}) {
        this.options = Object.assign({
            internalSelector: '#internal-book',
            externalSelector: '#external-book',
            internalEndpoint: '/api/orderbook/internal',
            externalEndpoint: '/api/orderbook/external',
            refreshInterval: 2000, // ms
            maxRows: 15,
            onUpdate: null
        }, options);
        
        this.internalContainer = document.querySelector(this.options.internalSelector);
        this.externalContainer = document.querySelector(this.options.externalSelector);
        
        this.intervalId = null;
        this.lastInternalData = null;
        this.lastExternalData = null;
        
        this.initialize();
    }
    
    initialize() {
        if (this.internalContainer) {
            this.initializeOrderBookDOM(this.internalContainer, 'internal');
        }
        
        if (this.externalContainer) {
            this.initializeOrderBookDOM(this.externalContainer, 'external');
        }
        
        // Initial load
        this.refresh();
        
        // Set up interval for refreshing
        this.intervalId = setInterval(() => this.refresh(), this.options.refreshInterval);
    }
    
    initializeOrderBookDOM(container, type) {
        // Create the order book structure if it doesn't already exist
        if (!container.querySelector('.book-sides')) {
            container.innerHTML = `
                <div class="book-sides">
                    <div class="book-side">
                        <h3>Bids</h3>
                        <table class="bids-table">
                            <thead>
                                <tr>
                                    <th>Price</th>
                                    <th>Quantity</th>
                                    <th>Total</th>
                                </tr>
                            </thead>
                            <tbody class="${type}-bids-body">
                                <tr><td colspan="3">Loading...</td></tr>
                            </tbody>
                        </table>
                    </div>
                    <div class="book-side">
                        <h3>Asks</h3>
                        <table class="asks-table">
                            <thead>
                                <tr>
                                    <th>Price</th>
                                    <th>Quantity</th>
                                    <th>Total</th>
                                </tr>
                            </thead>
                            <tbody class="${type}-asks-body">
                                <tr><td colspan="3">Loading...</td></tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }
    }
    
    refresh() {
        if (this.internalContainer) {
            this.fetchOrderBook('internal');
        }
        
        if (this.externalContainer) {
            this.fetchOrderBook('external');
        }
    }
    
    fetchOrderBook(type) {
        const endpoint = type === 'internal' 
            ? this.options.internalEndpoint 
            : this.options.externalEndpoint;
        
        fetch(endpoint)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`Error ${response.status}: ${response.statusText}`);
                }
                return response.json();
            })
            .then(data => {
                if (type === 'internal') {
                    this.lastInternalData = data;
                } else {
                    this.lastExternalData = data;
                }
                
                this.updateOrderBook(type, data);
                
                // Call the onUpdate callback if provided
                if (typeof this.options.onUpdate === 'function') {
                    this.options.onUpdate(type, data);
                }
            })
            .catch(error => {
                console.error(`Error fetching ${type} order book:`, error);
                const container = type === 'internal' ? this.internalContainer : this.externalContainer;
                
                if (container) {
                    const bidsBody = container.querySelector(`.${type}-bids-body`);
                    const asksBody = container.querySelector(`.${type}-asks-body`);
                    
                    if (bidsBody) {
                        bidsBody.innerHTML = '<tr><td colspan="3">Could not load order book data</td></tr>';
                    }
                    
                    if (asksBody) {
                        asksBody.innerHTML = '<tr><td colspan="3">Could not load order book data</td></tr>';
                    }
                }
            });
    }
    
    updateOrderBook(type, data) {
        const container = type === 'internal' ? this.internalContainer : this.externalContainer;
        
        if (!container) return;
        
        const bidsBody = container.querySelector(`.${type}-bids-body`);
        const asksBody = container.querySelector(`.${type}-asks-body`);
        
        if (bidsBody) {
            this.updateOrdersTable(bidsBody, data.bids || [], 'bid', this.options.maxRows);
        }
        
        if (asksBody) {
            this.updateOrdersTable(asksBody, data.asks || [], 'ask', this.options.maxRows);
        }
    }
    
    updateOrdersTable(tableBody, orders, type, maxRows) {
        tableBody.innerHTML = '';
        
        if (!orders || orders.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = `<td colspan="3">No ${type === 'bid' ? 'buy' : 'sell'} orders</td>`;
            tableBody.appendChild(row);
            return;
        }
        
        // Limit the number of rows
        const displayOrders = orders.slice(0, maxRows);
        
        displayOrders.forEach(order => {
            const row = document.createElement('tr');
            row.className = type;
            
            const price = parseFloat(order.price).toFixed(2);
            const quantity = parseFloat(order.quantity).toFixed(4);
            const total = (parseFloat(order.price) * parseFloat(order.quantity)).toFixed(2);
            
            // If it's an internal match, show a badge
            const internalBadge = order.internal_match ? 
                '<span class="badge internal-badge">DARK</span>' : '';
            
            row.innerHTML = `
                <td class="price">${price} ${internalBadge}</td>
                <td class="quantity">${quantity}</td>
                <td class="total">${total}</td>
            `;
            
            tableBody.appendChild(row);
        });
    }
    
    setSymbol(symbol) {
        // Update the endpoints with the new symbol
        this.options.internalEndpoint = `/api/orderbook/internal?symbol=${symbol}`;
        this.options.externalEndpoint = `/api/orderbook/external?symbol=${symbol}`;
        
        // Refresh the order books
        this.refresh();
    }
    
    stop() {
        if (this.intervalId) {
            clearInterval(this.intervalId);
            this.intervalId = null;
        }
    }
}

export { OrderBook }; 
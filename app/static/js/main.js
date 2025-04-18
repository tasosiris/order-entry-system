/**
 * Main JavaScript file for the Order Entry System
 * 
 * Initializes common functionality across all pages.
 */

document.addEventListener('DOMContentLoaded', function() {
    // Connection status indicator
    initConnectionStatus();
    
    // Tabs functionality
    initTabs();
    
    // Initialize WebSocket
    initWebSocket();
    
    // Hook into form submissions to capture and display latency
    const orderForm = document.getElementById('order-form');
    if (orderForm) {
        orderForm.addEventListener('submit', function(event) {
            // Don't prevent default - let htmx handle the form submission
            
            // Display "measuring..." while waiting for response
            const latencyElement = document.getElementById('latency-value');
            if (latencyElement) {
                latencyElement.textContent = 'measuring...';
                latencyElement.style.color = 'var(--text-dark)';
            }
            
            // The actual latency will be updated when the response comes back
            // This happens in the htmx:afterRequest event below
        });
        
        // Listen for the htmx response event
        document.body.addEventListener('htmx:afterRequest', function(event) {
            if (event.detail.elt && event.detail.elt.id === 'order-form') {
                try {
                    const response = JSON.parse(event.detail.xhr.responseText);
                    if (response && response.latency) {
                        updateLatency(response.latency);
                    }
                } catch (e) {
                    console.error('Error parsing order response for latency:', e);
                }
            }
        });
    }
});

/**
 * Initialize WebSocket connection
 */
function initWebSocket() {
    // Global websocket reference
    let ws = null;
    let reconnectAttempts = 0;
    let reconnectTimeout = null;
    const maxReconnectAttempts = 5;
    const initialBackoff = 1000; // 1 second
    const maxBackoff = 30000; // 30 seconds
    
    function connect() {
        // Clear any existing connection
        if (ws) {
            ws.onclose = null; // Prevent the reconnect from triggering
            ws.close();
        }
        
        // Create new WebSocket connection
        ws = new WebSocket(`ws://${window.location.host}/ws`);
        
        ws.onopen = () => {
            console.log('WebSocket connected');
            document.getElementById('connection-status').textContent = 'Connected';
            document.getElementById('connection-status').style.color = 'var(--success-color)';
            reconnectAttempts = 0;
            
            // Hide any error message
            const errorElement = document.getElementById('websocket-error');
            if (errorElement) {
                errorElement.style.display = 'none';
            }
        };
        
        ws.onclose = (event) => {
            console.log(`WebSocket disconnected (code: ${event.code}, reason: ${event.reason})`);
            document.getElementById('connection-status').textContent = 'Disconnected';
            document.getElementById('connection-status').style.color = 'var(--danger-color)';
            
            // Don't try to reconnect if closed normally or max attempts reached
            if (event.code === 1000 || reconnectAttempts >= maxReconnectAttempts) {
                console.log('WebSocket connection closed permanently');
                return;
            }
            
            // Attempt to reconnect with exponential backoff
            reconnectAttempts++;
            const backoff = Math.min(maxBackoff, initialBackoff * Math.pow(2, reconnectAttempts - 1));
            
            console.log(`Attempting to reconnect in ${backoff/1000} seconds (${reconnectAttempts}/${maxReconnectAttempts})`);
            
            // Show reconnecting message
            const errorElement = document.getElementById('websocket-error');
            if (errorElement) {
                errorElement.style.display = 'block';
                errorElement.textContent = `Connection lost. Reconnecting in ${backoff/1000} seconds...`;
            }
            
            // Schedule reconnect
            clearTimeout(reconnectTimeout);
            reconnectTimeout = setTimeout(() => {
                connect();
            }, backoff);
        };
        
        ws.onerror = (error) => {
            console.error('WebSocket error:', error);
            // The onclose handler will be called after this
        };
        
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                handleWebSocketMessage(data);
            } catch (e) {
                console.error('Error parsing WebSocket message:', e);
            }
        };
        
        // Expose websocket to global scope for other scripts
        window.oes_websocket = ws;
    }
    
    function handleWebSocketMessage(data) {
        switch (data.type) {
            case 'orderbook':
                updateOrderBook(data.data);
                break;
            case 'trade':
                updateTrades(data.data);
                break;
            case 'latency':
                updateLatency(data.value);
                break;
            case 'error':
                showError(data.message);
                break;
            case 'toast':
                showToast(data.title, data.message, data.variant, data.duration);
                break;
            case 'notification':
                console.log('Received notification:', data);
                break;
            case 'trade_executed':
                // Handle trade execution notification
                console.log('Received trade execution notification, updating UI...');
                
                // Show a notification for the trade
                if (data.buy_order_id || data.sell_order_id) {
                    const symbol = data.symbol || '';
                    const price = data.price ? `$${parseFloat(data.price).toFixed(2)}` : '';
                    const quantity = data.quantity || '';
                    const side = data.buy_order_id ? 'Buy' : 'Sell';
                    const tradeValue = price && quantity ? `$${(parseFloat(price.replace('$', '')) * parseFloat(quantity)).toFixed(2)}` : '';
                    
                    // Create custom HTML content for the notification
                    const customTitle = `<div style="display: flex; align-items: center;">
                        <span style="color: var(--success-color); margin-right: 8px;">✓</span>
                        <span>Order Matched!</span>
                    </div>`;
                    
                    const customMessage = `<div style="margin-top: 5px;">
                        <div style="font-weight: bold; font-size: 16px;">${symbol}</div>
                        <div style="display: flex; justify-content: space-between; margin-top: 4px;">
                            <span>${side} ${quantity} shares</span>
                            <span>${price}</span>
                        </div>
                        <div style="color: var(--text-muted); text-align: right; margin-top: 2px; font-size: 12px;">
                            Total: ${tradeValue}
                        </div>
                    </div>`;
                    
                    // Create and show a custom toast
                    const toast = showToast(
                        'Order Matched!', 
                        `${symbol}: ${quantity} shares at ${price}`, 
                        'success', 
                        8000
                    );
                    
                    // Update the toast content with our custom HTML
                    const toastTitle = toast.querySelector('.toast-title');
                    const toastMessage = toast.querySelector('.toast-message');
                    
                    if (toastTitle && toastMessage) {
                        toastTitle.innerHTML = customTitle;
                        toastMessage.innerHTML = customMessage;
                    }
                    
                    // Play notification sound
                    const audio = document.getElementById('order-match-sound');
                    if (audio) {
                        audio.currentTime = 0; // Reset to beginning
                        audio.play().catch(e => console.warn('Could not play notification sound:', e));
                    }
                }
                
                // Update trades list if applicable
                updateTrades([data]);
                
                // Check if the order was removed
                if (data.order_removed) {
                    // Force refresh of all order tables
                    refreshOrderLists();
                }
                break;
            case 'orders_updated':
                // Force refresh all order lists when orders are updated
                refreshOrderLists();
                break;
        }
    }

    function updateLatency(value) {
        const latencyElement = document.getElementById('latency-value');
        if (latencyElement) {
            latencyElement.textContent = `${value}ms`;
            
            // Add color coding based on latency value
            if (value < 10) {
                latencyElement.style.color = 'var(--success-color)'; // Green for low latency
            } else if (value < 50) {
                latencyElement.style.color = 'var(--warning-color)'; // Yellow for medium latency
            } else {
                latencyElement.style.color = 'var(--danger-color)'; // Red for high latency
            }
        }
    }

    function updateOrderBook(data) {
        // Implementation depends on the page
        const orderBookEvent = new CustomEvent('orderBookUpdate', { detail: data });
        window.dispatchEvent(orderBookEvent);
    }

    function updateTrades(data) {
        // Implementation depends on the page
        const tradeEvent = new CustomEvent('tradeUpdate', { detail: data });
        window.dispatchEvent(tradeEvent);
    }

    function showError(message) {
        showToast('Error', message, 'error');
    }
    
    /**
     * Display a toast notification
     * @param {string} title - Toast title
     * @param {string} message - Toast message
     * @param {string} variant - success, error, info, warning
     * @param {number} duration - Duration in ms (default: 5000)
     * @returns {HTMLElement} - The toast element
     */
    function showToast(title, message, variant = 'info', duration = 5000) {
        // Create toast container if it doesn't exist
        let toastContainer = document.getElementById('toast-container');
        if (!toastContainer) {
            toastContainer = document.createElement('div');
            toastContainer.id = 'toast-container';
            toastContainer.style.position = 'fixed';
            toastContainer.style.top = '20px';
            toastContainer.style.right = '20px';
            toastContainer.style.zIndex = '9999';
            toastContainer.style.display = 'flex';
            toastContainer.style.flexDirection = 'column';
            toastContainer.style.gap = '10px';
            document.body.appendChild(toastContainer);
        }
        
        // Create toast element
        const toast = document.createElement('div');
        toast.className = `toast toast-${variant}`;
        toast.style.backgroundColor = 'var(--card-dark)';
        toast.style.color = 'var(--text-dark)';
        toast.style.border = `1px solid var(--${variant}-color, var(--primary-color))`;
        toast.style.borderLeft = `4px solid var(--${variant}-color, var(--primary-color))`;
        toast.style.borderRadius = '0px';
        toast.style.padding = '12px 16px';
        toast.style.minWidth = '300px';
        toast.style.maxWidth = '400px';
        toast.style.boxShadow = '0 4px 12px rgba(0, 0, 0, 0.15)';
        toast.style.display = 'flex';
        toast.style.flexDirection = 'column';
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(20px)';
        toast.style.transition = 'opacity 0.3s, transform 0.3s';
        
        // Toast title
        const toastTitle = document.createElement('div');
        toastTitle.className = 'toast-title';
        toastTitle.textContent = title;
        toastTitle.style.fontWeight = 'bold';
        toastTitle.style.marginBottom = '4px';
        toastTitle.style.color = `var(--${variant}-color, var(--primary-color))`;
        
        // Toast message
        const toastMessage = document.createElement('div');
        toastMessage.className = 'toast-message';
        toastMessage.textContent = message;
        
        // Close button
        const closeBtn = document.createElement('button');
        closeBtn.className = 'toast-close';
        closeBtn.innerHTML = '&times;';
        closeBtn.style.position = 'absolute';
        closeBtn.style.top = '8px';
        closeBtn.style.right = '8px';
        closeBtn.style.background = 'transparent';
        closeBtn.style.border = 'none';
        closeBtn.style.color = 'var(--text-muted)';
        closeBtn.style.fontSize = '16px';
        closeBtn.style.cursor = 'pointer';
        closeBtn.style.padding = '0';
        closeBtn.style.width = '20px';
        closeBtn.style.height = '20px';
        closeBtn.style.display = 'flex';
        closeBtn.style.alignItems = 'center';
        closeBtn.style.justifyContent = 'center';
        
        // Append elements
        toast.appendChild(toastTitle);
        toast.appendChild(toastMessage);
        toast.appendChild(closeBtn);
        toastContainer.appendChild(toast);
        
        // Animate in
        setTimeout(() => {
            toast.style.opacity = '1';
            toast.style.transform = 'translateX(0)';
        }, 10);
        
        // Set up close button
        closeBtn.addEventListener('click', () => {
            removeToast(toast);
        });
        
        // Auto remove after duration
        const timeoutId = setTimeout(() => {
            removeToast(toast);
        }, duration);
        
        // Store timeout ID to clear it if manually closed
        toast._timeoutId = timeoutId;
        
        function removeToast(toast) {
            // Clear the timeout
            if (toast._timeoutId) {
                clearTimeout(toast._timeoutId);
            }
            
            // Animate out
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(20px)';
            
            // Remove after animation completes
            setTimeout(() => {
                toast.remove();
                
                // Remove container if empty
                if (toastContainer.children.length === 0) {
                    toastContainer.remove();
                }
            }, 300);
        }
        
        return toast;
    }
    
    function refreshOrderLists() {
        // Refresh orders in all tabs and sections
        
        // 1. Send event to refresh the orderbook
        const orderBookEvent = new CustomEvent('orderBookRefresh');
        window.dispatchEvent(orderBookEvent);
        
        // 2. Force refresh all orders tables using HTMX
        const ordersElements = document.querySelectorAll('[hx-trigger="load"]');
        ordersElements.forEach(element => {
            if (element.getAttribute('hx-get') && 
                (element.getAttribute('hx-get').includes('/orders') || 
                 element.getAttribute('hx-get').includes('/api/orders'))) {
                // Trigger HTMX to reload this content
                htmx.trigger(element, 'load');
            }
        });
        
        // 3. Find and refresh all tables with specific IDs
        const orderTables = [
            'open-orders-table',
            'all-orders-table',
            'active-orders-body',
            'all-orders-body',
            'account-orders-body'
        ];
        
        orderTables.forEach(tableId => {
            const table = document.getElementById(tableId);
            if (table && table.getAttribute('hx-get')) {
                htmx.trigger(table, 'load');
            }
        });
    }
    
    // Start the initial connection
    connect();
    
    // Add event listener for network status changes
    window.addEventListener('online', () => {
        console.log('Network connection restored, reconnecting WebSocket');
        connect();
    });
}

/**
 * Initialize connection status indicator
 */
function initConnectionStatus() {
    const connectionStatus = document.getElementById('connection-status');
    
    if (!connectionStatus) return;
    
    // Check connection every 10 seconds
    setInterval(() => {
        checkConnection(connectionStatus);
    }, 10000);
    
    // Initial check
    checkConnection(connectionStatus);
}

/**
 * Check the connection status
 */
function checkConnection(statusElement) {
    fetch('/api/status', { method: 'GET' })
        .then(response => {
            if (response.ok) {
                statusElement.textContent = 'Connected';
                statusElement.style.color = 'var(--success-color)';
                statusElement.style.backgroundColor = 'transparent';
            } else {
                throw new Error('Server error');
            }
        })
        .catch(error => {
            statusElement.textContent = 'Disconnected';
            statusElement.style.color = 'var(--danger-color)';
            statusElement.style.backgroundColor = 'transparent';
            console.error('Connection error:', error);
        });
}

/**
 * Initialize tabs functionality
 */
function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-btn');
    
    tabButtons.forEach(button => {
        button.addEventListener('click', () => {
            const targetTab = button.dataset.tab;
            const tabContainer = button.closest('.tabs').parentElement;
            
            // Remove active class from all buttons in this tab group
            const buttons = button.closest('.tabs').querySelectorAll('.tab-btn');
            buttons.forEach(btn => btn.classList.remove('active'));
            
            // Add active class to clicked button
            button.classList.add('active');
            
            // Hide all sections
            const sections = tabContainer.querySelectorAll('[data-tab-content]');
            sections.forEach(section => {
                section.style.display = 'none';
            });
            
            // Show selected section
            const targetSection = tabContainer.querySelector(`[data-tab-content="${targetTab}"]`);
            if (targetSection) {
                targetSection.style.display = 'block';
            }
        });
    });
    
    // Activate first tab by default if none are active
    document.querySelectorAll('.tabs').forEach(tabGroup => {
        const activeTab = tabGroup.querySelector('.tab-btn.active');
        if (!activeTab && tabGroup.querySelector('.tab-btn')) {
            tabGroup.querySelector('.tab-btn').click();
        }
    });
}

// Expose common functions to global scope for use in inline scripts if needed
window.OES = {
    initConnectionStatus,
    initTabs
}; 
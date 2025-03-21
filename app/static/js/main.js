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
        const errorDiv = document.createElement('div');
        errorDiv.className = 'error-message';
        errorDiv.textContent = message;
        document.body.appendChild(errorDiv);
        setTimeout(() => errorDiv.remove(), 5000);
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
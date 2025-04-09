class Chatbot {
    constructor() {
        this.chatbotContainer = null;
        this.messagesContainer = null;
        this.inputField = null;
        this.isOpen = false;
        this.initialize();
    }

    initialize() {
        // Create chatbot container
        this.chatbotContainer = document.createElement('div');
        this.chatbotContainer.className = 'chatbot-container';
        this.chatbotContainer.innerHTML = `
            <div class="chatbot-header">
                <h3>Order Assistant</h3>
                <button class="close-btn">×</button>
            </div>
            <div class="chatbot-messages"></div>
            <div class="chatbot-input">
                <input type="text" placeholder="Type your message...">
                <button class="send-btn">Send</button>
            </div>
        `;

        // Add styles
        const style = document.createElement('style');
        style.textContent = `
            .chatbot-container {
                position: fixed;
                bottom: 20px;
                right: 20px;
                width: 350px;
                height: 500px;
                background: var(--card-dark);
                border: 1px solid var(--border-dark);
                display: flex;
                flex-direction: column;
                z-index: 1000;
                transform: translateY(100%);
                transition: transform 0.3s ease;
            }

            .chatbot-container.open {
                transform: translateY(0);
            }

            .chatbot-header {
                padding: 10px;
                background: var(--header-bg);
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid var(--border-dark);
            }

            .chatbot-header h3 {
                margin: 0;
                color: var(--text-dark);
            }

            .close-btn {
                background: none;
                border: none;
                color: var(--text-dark);
                font-size: 20px;
                cursor: pointer;
            }

            .chatbot-messages {
                flex: 1;
                overflow-y: auto;
                padding: 10px;
            }

            .message {
                margin-bottom: 10px;
                padding: 8px 12px;
                border-radius: 4px;
                max-width: 80%;
            }

            .user-message {
                background: var(--primary-color);
                color: white;
                margin-left: auto;
            }

            .bot-message {
                background: var(--card-dark);
                color: var(--text-dark);
                border: 1px solid var(--border-dark);
            }

            .chatbot-input {
                padding: 10px;
                display: flex;
                gap: 10px;
                border-top: 1px solid var(--border-dark);
            }

            .chatbot-input input {
                flex: 1;
                padding: 8px;
                background: var(--card-dark);
                border: 1px solid var(--border-dark);
                color: var(--text-dark);
            }

            .send-btn {
                padding: 8px 16px;
                background: var(--primary-color);
                color: white;
                border: none;
                cursor: pointer;
            }

            .chatbot-toggle {
                position: fixed;
                bottom: 20px;
                right: 20px;
                width: 50px;
                height: 50px;
                background: var(--primary-color);
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                cursor: pointer;
                z-index: 999;
            }
        `;
        document.head.appendChild(style);

        // Create toggle button
        const toggleButton = document.createElement('div');
        toggleButton.className = 'chatbot-toggle';
        toggleButton.innerHTML = '💬';
        document.body.appendChild(toggleButton);

        // Add event listeners
        toggleButton.addEventListener('click', () => this.toggle());
        this.chatbotContainer.querySelector('.close-btn').addEventListener('click', () => this.toggle());
        this.inputField = this.chatbotContainer.querySelector('input');
        this.messagesContainer = this.chatbotContainer.querySelector('.chatbot-messages');
        
        const sendButton = this.chatbotContainer.querySelector('.send-btn');
        sendButton.addEventListener('click', () => this.handleSend());
        this.inputField.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') this.handleSend();
        });

        document.body.appendChild(this.chatbotContainer);
    }

    toggle() {
        this.isOpen = !this.isOpen;
        this.chatbotContainer.classList.toggle('open');
    }

    async handleSend() {
        const message = this.inputField.value.trim();
        if (!message) return;

        this.addMessage(message, 'user');
        this.inputField.value = '';

        try {
            const response = await this.processMessage(message);
            this.addMessage(response, 'bot');
        } catch (error) {
            this.addMessage('Sorry, I encountered an error. Please try again.', 'bot');
            console.error('Error processing message:', error);
        }
    }

    addMessage(text, sender) {
        const messageDiv = document.createElement('div');
        messageDiv.className = `message ${sender}-message`;
        messageDiv.textContent = text;
        this.messagesContainer.appendChild(messageDiv);
        this.messagesContainer.scrollTop = this.messagesContainer.scrollHeight;
    }

    async processMessage(message) {
        // Check if it's an order command
        if (message.toLowerCase().includes('buy') || message.toLowerCase().includes('sell')) {
            return await this.processOrder(message);
        }
        // Check if it's a ticker information request
        else if (message.toLowerCase().includes('info') || message.toLowerCase().includes('price')) {
            return await this.getTickerInfo(message);
        }
        // Default response
        return "I can help you with:\n1. Placing orders (e.g., 'buy 100 shares of AAPL at $150')\n2. Getting stock information (e.g., 'info on AAPL')\n3. Checking prices (e.g., 'price of MSFT')";
    }

    async processOrder(message) {
        // Extract order details using regex
        const orderRegex = /(buy|sell)\s+(\d+)\s+shares?\s+of\s+([A-Z]+)\s+at\s+\$?(\d+(?:\.\d{1,2})?)/i;
        const match = message.match(orderRegex);

        if (!match) {
            return "I couldn't understand the order. Please use the format: 'buy/sell X shares of SYMBOL at $PRICE'";
        }

        const [_, action, quantity, symbol, price] = match;
        
        try {
            const response = await fetch('/api/orders', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    type: action.toLowerCase(),
                    symbol: symbol.toUpperCase(),
                    price: parseFloat(price),
                    quantity: parseInt(quantity)
                })
            });

            if (response.ok) {
                return `Order placed successfully: ${action} ${quantity} shares of ${symbol} at $${price}`;
            } else {
                const error = await response.json();
                return `Failed to place order: ${error.detail || 'Unknown error'}`;
            }
        } catch (error) {
            return `Error placing order: ${error.message}`;
        }
    }

    async getTickerInfo(message) {
        // Extract ticker symbol using regex
        const tickerRegex = /(?:info|price)\s+(?:on|of|for)?\s+([A-Z]+)/i;
        const match = message.match(tickerRegex);

        if (!match) {
            return "I couldn't find a ticker symbol. Please use the format: 'info on SYMBOL' or 'price of SYMBOL'";
        }

        const symbol = match[1].toUpperCase();
        
        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    message: `info on ${symbol}`
                })
            });

            if (response.ok) {
                const data = await response.json();
                return data.response;
            } else {
                const error = await response.json();
                return `Error getting information: ${error.detail || 'Unknown error'}`;
            }
        } catch (error) {
            return `Error getting information for ${symbol}: ${error.message}`;
        }
    }
}

// Initialize chatbot when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new Chatbot();
}); 
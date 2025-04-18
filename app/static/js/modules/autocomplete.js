/**
 * Symbol Autocomplete Module
 * 
 * This module provides autocomplete functionality for symbol inputs
 * with keyboard navigation and selection.
 */

class Autocomplete {
    constructor(inputElement, options = {}) {
        this.input = inputElement;
        this.options = Object.assign({
            minLength: 1,
            maxResults: 10,
            delay: 150,
            onSelect: null,
            getSymbols: null, // Function to get symbols
            symbols: []       // Default symbols
        }, options);
        
        this.resultsContainer = null;
        this.timeout = null;
        this.selectedIndex = -1;
        this.results = [];
        
        this.initialize();
    }
    
    initialize() {
        // Create results container
        this.resultsContainer = document.createElement('div');
        this.resultsContainer.className = 'autocomplete-results';
        this.resultsContainer.style.display = 'none';
        
        // Wrap input in a container if it's not already wrapped
        let container = this.input.parentElement;
        if (!container.classList.contains('autocomplete-container')) {
            container = document.createElement('div');
            container.className = 'autocomplete-container';
            this.input.parentNode.insertBefore(container, this.input);
            container.appendChild(this.input);
        }
        
        container.appendChild(this.resultsContainer);
        
        // Add event listeners
        this.input.addEventListener('input', this.onInput.bind(this));
        this.input.addEventListener('keydown', this.onKeyDown.bind(this));
        this.input.addEventListener('blur', () => {
            setTimeout(() => this.hideResults(), 200);
        });
        
        // Click outside to close results
        document.addEventListener('click', (e) => {
            if (!container.contains(e.target)) {
                this.hideResults();
            }
        });
    }
    
    onInput() {
        const value = this.input.value.trim();
        
        clearTimeout(this.timeout);
        
        if (value.length < this.options.minLength) {
            this.hideResults();
            return;
        }
        
        this.timeout = setTimeout(() => {
            this.search(value);
        }, this.options.delay);
    }
    
    onKeyDown(e) {
        if (!this.resultsContainer.style.display || this.resultsContainer.style.display === 'none') {
            return;
        }
        
        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.moveSelection(1);
                break;
            case 'ArrowUp':
                e.preventDefault();
                this.moveSelection(-1);
                break;
            case 'Enter':
                e.preventDefault();
                if (this.selectedIndex >= 0) {
                    this.selectResult(this.selectedIndex);
                }
                break;
            case 'Escape':
                e.preventDefault();
                this.hideResults();
                break;
        }
    }
    
    async search(query) {
        let symbols = [];
        
        if (typeof this.options.getSymbols === 'function') {
            // Get symbols from a custom function (e.g. from API)
            symbols = await this.options.getSymbols(query);
        } else {
            // Filter from provided symbols
            symbols = this.options.symbols.filter(symbol => 
                symbol.toLowerCase().includes(query.toLowerCase())
            );
        }
        
        // Limit results
        this.results = symbols.slice(0, this.options.maxResults);
        
        if (this.results.length === 0) {
            this.hideResults();
            return;
        }
        
        this.showResults();
    }
    
    showResults() {
        this.resultsContainer.innerHTML = '';
        this.selectedIndex = -1;
        
        this.results.forEach((result, index) => {
            const item = document.createElement('div');
            item.className = 'autocomplete-item';
            item.textContent = result;
            
            item.addEventListener('click', () => {
                this.selectResult(index);
            });
            
            item.addEventListener('mouseover', () => {
                this.highlightResult(index);
            });
            
            this.resultsContainer.appendChild(item);
        });
        
        this.resultsContainer.style.display = 'block';
    }
    
    hideResults() {
        this.resultsContainer.style.display = 'none';
        this.selectedIndex = -1;
    }
    
    moveSelection(direction) {
        this.selectedIndex += direction;
        
        // Loop around if out of bounds
        if (this.selectedIndex < 0) {
            this.selectedIndex = this.results.length - 1;
        } else if (this.selectedIndex >= this.results.length) {
            this.selectedIndex = 0;
        }
        
        this.highlightResult(this.selectedIndex);
    }
    
    highlightResult(index) {
        const items = this.resultsContainer.querySelectorAll('.autocomplete-item');
        
        items.forEach(item => item.classList.remove('selected'));
        
        if (items[index]) {
            items[index].classList.add('selected');
            
            // Scroll to item if needed
            const container = this.resultsContainer;
            const item = items[index];
            
            if (item.offsetTop < container.scrollTop) {
                container.scrollTop = item.offsetTop;
            } else if (item.offsetTop + item.offsetHeight > container.scrollTop + container.offsetHeight) {
                container.scrollTop = item.offsetTop + item.offsetHeight - container.offsetHeight;
            }
        }
        
        this.selectedIndex = index;
    }
    
    selectResult(index) {
        const value = this.results[index];
        this.input.value = value;
        this.hideResults();
        
        // Trigger onSelect callback
        if (typeof this.options.onSelect === 'function') {
            this.options.onSelect(value);
        }
        
        // Trigger change event on input
        const event = new Event('change', { bubbles: true });
        this.input.dispatchEvent(event);
    }
}

// Fetch tickers from API
async function fetchTickers() {
    try {
        const response = await fetch('/api/market/tickers');
        const data = await response.json();
        return data.tickers || [];
    } catch (error) {
        console.error('Error fetching tickers:', error);
        return [];
    }
}

// Define symbol lists for different asset types - these will be populated dynamically
const SYMBOL_LISTS = {
    stocks: [],
    futures: [
        'ES', 'NQ', 'YM', 'RTY', 'CL', 'GC', 'SI', 'HG', 'ZB', 'ZN',
        'ZF', 'ZT', '6E', '6J', '6B', '6A', '6C', 'KC', 'CT', 'SB',
        'ZS', 'ZM', 'ZW', 'ZC', 'LBS', 'LE', 'HE', 'GF'
    ],
    options: [
        'AAPL230915C180', 'AAPL230915P170', 'SPY230915C410', 'SPY230915P400',
        'QQQ231020C380', 'QQQ231020P370', 'MSFT231020C350', 'MSFT231020P340',
        'TSLA240119C250', 'TSLA240119P240', 'AMZN240119C150', 'AMZN240119P140'
    ],
    crypto: [
        'BTC-USD', 'ETH-USD', 'XRP-USD', 'BCH-USD', 'LTC-USD', 'EOS-USD',
        'ADA-USD', 'XLM-USD', 'LINK-USD', 'DOT-USD', 'YFI-USD', 'UNI-USD',
        'AAVE-USD', 'SOL-USD', 'AVAX-USD', 'MATIC-USD', 'COMP-USD', 'SNX-USD'
    ]
};

// Initialize tickers
(async function() {
    try {
        SYMBOL_LISTS.stocks = await fetchTickers();
        console.log(`Loaded ${SYMBOL_LISTS.stocks.length} stock tickers`);
    } catch (error) {
        console.error('Failed to initialize tickers:', error);
    }
})();

// Export the Autocomplete class and symbol lists
export { Autocomplete, SYMBOL_LISTS }; 
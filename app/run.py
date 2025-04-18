import os
import signal
import sys
import uvicorn
import asyncio
import logging
import importlib
import socket
import subprocess
import time
import platform

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger("oes.run")

# Add the parent directory to sys.path to make the app module importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.main import app, shutdown_event

# Define server port
SERVER_PORT = 8002

# Set global flag for preventing data clearing
NO_CLEAR_DATA = False

def check_port_in_use(port):
    """Check if the specified port is already in use"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('localhost', port)) == 0

def find_process_using_port(port):
    """Find process ID using the specified port"""
    system = platform.system()
    
    try:
        if system == 'Darwin' or system == 'Linux':  # macOS or Linux
            # Using lsof to find the process
            cmd = f"lsof -i :{port} -t"
            output = subprocess.check_output(cmd, shell=True, text=True).strip()
            if output:
                return output.split('\n')[0]  # Return the first PID if multiple
        elif system == 'Windows':
            # Using netstat on Windows
            cmd = f"netstat -ano | findstr :{port}"
            output = subprocess.check_output(cmd, shell=True, text=True)
            if output:
                lines = output.strip().split('\n')
                for line in lines:
                    if f":{port}" in line:
                        parts = line.strip().split()
                        return parts[-1]  # The last column is the PID
    except subprocess.SubprocessError:
        logger.error(f"Failed to find process using port {port}")
    
    return None

def kill_process(pid):
    """Kill a process by its PID"""
    system = platform.system()
    
    try:
        if system == 'Darwin' or system == 'Linux':  # macOS or Linux
            os.kill(int(pid), signal.SIGTERM)
            logger.info(f"Sent SIGTERM to process {pid}")
            
            # Wait for process to terminate
            time.sleep(1)
            
            # If still running, force kill
            try:
                os.kill(int(pid), 0)  # Check if process is still running
                logger.info(f"Process {pid} still running, sending SIGKILL")
                os.kill(int(pid), signal.SIGKILL)
            except OSError:
                pass  # Process already terminated
                
        elif system == 'Windows':
            subprocess.check_call(['taskkill', '/F', '/PID', str(pid)])
            logger.info(f"Killed process {pid} on Windows")
            
        return True
    except (subprocess.SubprocessError, OSError) as e:
        logger.error(f"Failed to kill process {pid}: {e}")
        return False

def ensure_port_available(port):
    """Make sure the specified port is available, killing any process using it"""
    if check_port_in_use(port):
        logger.warning(f"Port {port} is already in use")
        pid = find_process_using_port(port)
        
        if pid:
            logger.info(f"Found process {pid} using port {port}")
            if kill_process(pid):
                logger.info(f"Successfully killed process {pid}")
                time.sleep(1)  # Give the system time to release the port
                
                if check_port_in_use(port):
                    logger.error(f"Port {port} is still in use after killing process {pid}")
                    return False
                else:
                    logger.info(f"Port {port} is now available")
                    return True
            else:
                logger.error(f"Failed to kill process {pid}")
                return False
        else:
            logger.error(f"Could not find process using port {port}")
            return False
    else:
        # Port is already available
        return True

def populate_data():
    """Populate Redis with realistic market data and trades"""
    try:
        logger.info("Populating market data...")
        market_data_module = importlib.import_module("app.populate_market_data")
        market_data_module.main()
        
        logger.info("Populating trade data...")
        trades_module = importlib.import_module("app.populate_trades")
        trades_module.main()
        
        logger.info("Data population completed successfully")
    except Exception as e:
        logger.error(f"Error populating data: {e}")

def signal_handler(sig, frame):
    print('\nShutting down gracefully...')
    # Force exit immediately
    os._exit(0)

if __name__ == "__main__":
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Check command line arguments
    if "--no-clear" in sys.argv:
        NO_CLEAR_DATA = True
        logger.info("Data clearing during startup will be skipped (--no-clear flag detected)")
    
    # Make sure the port is available
    if not ensure_port_available(SERVER_PORT):
        logger.error(f"Could not free up port {SERVER_PORT}, exiting")
        sys.exit(1)
    
    # Populate data before starting the server
    if "--skip-populate" not in sys.argv:
        populate_data()
    else:
        logger.info("Skipping data population (--skip-populate flag detected)")
    
    # Set environment variable to communicate with main.py
    if NO_CLEAR_DATA:
        os.environ["OES_NO_CLEAR_DATA"] = "1"
    
    # Configure uvicorn
    config = uvicorn.Config(
        "app.main:app",
        host="0.0.0.0",
        port=SERVER_PORT,
        reload=False,
        log_level="info",
        workers=1
    )
    
    # Run the server
    server = uvicorn.Server(config)
    try:
        server.run()
    except KeyboardInterrupt:
        print("Received exit signal")
        os._exit(0) 
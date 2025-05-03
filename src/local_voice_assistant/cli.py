import argparse
import yaml
import logging
import sys
import time
from dotenv import load_dotenv
import os
import logging.handlers # Import handlers

# --- Load .env file early! ---
load_dotenv()
# ---------------------------

# Get a logger instance specific to this module
logger = logging.getLogger(__name__)

# It's generally safe to import standard libraries and modules
# that *don't* do logging on import themselves here.

# --- Shared Logging Configuration ---
LOG_FILENAME = 'jarvis.log' # Log file in the root directory
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
# ---------------------------------

def setup_logging(log_level_str: str = "INFO"):
    """Configures logging for the main application."""
    log_level = getattr(logging, log_level_str.upper(), logging.INFO)
    
    # Get the root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG) 

    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)

    # Remove existing handlers (if any added by basicConfig elsewhere or previously)
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    # --- Console Handler ---
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level) # Console logs at the specified level
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # --- File Handler ---
    try:
        # Log everything (including DEBUG from modules if root is DEBUG) to the file
        file_handler = logging.FileHandler(LOG_FILENAME, mode='a', encoding='utf-8')
        # Set file handler level - typically INFO or DEBUG depending on desired file verbosity
        # Let's set it to DEBUG to capture everything from all modules.
        file_handler.setLevel(logging.DEBUG) 
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        logger.info(f"Logging configured. Level: {log_level_str}. Outputting to console and file: {LOG_FILENAME}")
    except Exception as e:
        logger.error(f"Failed to configure file logging to {LOG_FILENAME}: {e}")
        # Continue with console logging only

# --- Now import application modules ---
# Orchestrator import now happens *after* load_dotenv() has run
from .orchestrator import Orchestrator
from .audio_interface import AudioCapture

def main():
    # Full argument parsing (now that logging is set up)
    parser = argparse.ArgumentParser(
         description="Local Voice Assistant (PTT Mode Only)",
    )
    # Re-add --debug here so the main parser recognizes it
    parser.add_argument('--debug', action='store_true', help='Enable debug logging') 
    parser.add_argument('--config', type=str, default='config.yaml', help='Path to config.yaml')
    args = parser.parse_args()
    
    # Logging level was already set by setup_logging() based on pre-parsing --debug
    logger.debug(f"Parsed arguments: {args}") 
    
    # Load config file
    try:
        with open(args.config, 'r') as f:
            config = yaml.safe_load(f)
            logger.info(f"Loaded configuration from: {args.config}")
    except FileNotFoundError:
         logger.error(f"Configuration file not found: {args.config}")
         return
    except yaml.YAMLError as e:
         logger.error(f"Error parsing configuration file {args.config}: {e}")
         return
    except Exception as e:
         logger.error(f"Unexpected error loading config {args.config}: {e}")
         return

    # Initialize and start Orchestrator background tasks
    _orchestrator_instance = None # Keep a reference for potential cleanup
    try:
        logger.info("Initializing Orchestrator...")
        _orchestrator_instance = Orchestrator(config)
        logger.info("Starting Orchestrator background tasks...")
        _orchestrator_instance.start() # This should now return quickly
        logger.info("Orchestrator tasks started.")
    except Exception as e:
         logger.exception(f"💥 Fatal error during orchestrator setup or start: {e}")
         return # Exit if orchestrator fails

    # Keep the main thread alive to allow background threads to run
    logger.info("🚀 Voice Assistant running. Press Ctrl+C to exit.")
    try:
        # Simple way to keep the main thread alive
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Keyboard interrupt received. Exiting...")
        sys.exit(0)

if __name__ == '__main__':
    main()

import argparse
import yaml
import logging
import sys
from dotenv import load_dotenv
import os

# --- Load .env file immediately ---
load_dotenv() # <-- Call earlier, before other imports try to use env vars
logger_env_check = logging.getLogger('dotenv_check') # Temp logger
api_key_check = os.getenv("ANTHROPIC_API_KEY")
if api_key_check:
    logger_env_check.debug(".env loaded, ANTHROPIC_API_KEY found.")
else:
    logger_env_check.debug(".env loaded, ANTHROPIC_API_KEY *not* found.")
# ---------------------------------

# Get a logger instance specific to this module
logger = logging.getLogger(__name__)

# It's generally safe to import standard libraries and modules
# that *don't* do logging on import themselves here.

# --- Configure Logging Immediately ---
# Determine log level from args *first*
def setup_logging():
    # Parse only known args related to logging initially
    # to avoid errors if other args are present before full parsing.
    parser = argparse.ArgumentParser(add_help=False) # Don't add help here yet
    parser.add_argument('--debug', action='store_true')
    args, _ = parser.parse_known_args() # Parse known args, ignore others for now
    
    log_level = logging.DEBUG if args.debug else logging.INFO
        
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s", # Consistent format
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    logging.info(f"Logging configured at level: {logging.getLevelName(log_level)}")

setup_logging() # Call configuration immediately

# --- Now import application modules ---
# Orchestrator import now happens *after* load_dotenv() has run
from .orchestrator import Orchestrator

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
            logging.info(f"Loaded configuration from: {args.config}")
    except FileNotFoundError:
         logging.error(f"Configuration file not found: {args.config}")
         return
    except yaml.YAMLError as e:
         logging.error(f"Error parsing configuration file {args.config}: {e}")
         return
    except Exception as e:
         logging.error(f"Unexpected error loading config {args.config}: {e}")
         return

    # Initialize and start Orchestrator background tasks
    _orchestrator_instance = None # Keep a reference for potential cleanup
    try:
        logging.info("Initializing Orchestrator...")
        _orchestrator_instance = Orchestrator(config)
        logging.info("Starting Orchestrator background tasks...")
        _orchestrator_instance.start() # This should now return quickly
        logging.info("Orchestrator tasks started.")
    except Exception as e:
         logging.exception(f"💥 Fatal error during orchestrator setup or start: {e}")
         return # Exit if orchestrator fails

    # Keep the main thread alive to allow background threads to run
    logging.info("🚀 Voice Assistant running. Press Ctrl+C to exit.")
    try:
        # Simple way to keep the main thread alive
        while True:
            import time
            time.sleep(1)
    except KeyboardInterrupt:
        logging.info("👋 Keyboard interrupt received. Exiting...")
        sys.exit(0)

if __name__ == '__main__':
    main()

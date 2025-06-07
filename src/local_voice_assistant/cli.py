import argparse
# import yaml # <-- Remove YAML import
import logging
import sys
import time
from dotenv import load_dotenv
import os
import logging.handlers
import warnings # <-- Add warnings import
import threading

# --- Suppress Semaphore Leak Warning --- 
warnings.filterwarnings(
    "ignore", 
    message="resource_tracker: There appear to be.*leaked semaphore objects.*", 
    category=UserWarning
)
# -------------------------------------

# --- Load .env file early! ---
load_dotenv()
# ---------------------------

logger = logging.getLogger(__name__)

# --- Shared Logging Configuration (Keep as is) ---
LOG_FILENAME = 'last_run.log'
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
# from .audio_interface import AudioCapture # No longer needed here

global_notification_manager = None

def global_exception_handler(exc_type, exc_value, exc_traceback):
    logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))
    if global_notification_manager:
        try:
            global_notification_manager.show_message(f"💥 {exc_value}", group_id='error_toast')
        except Exception as toast_exc:
            logger.error(f"Failed to show global error toast: {toast_exc}")

sys.excepthook = global_exception_handler

def run_orchestrator():
    # --- Pre-parse for --debug ---
    pre_parser = argparse.ArgumentParser(add_help=False)
    pre_parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    pre_args, _ = pre_parser.parse_known_args()
    log_level = "DEBUG" if pre_args.debug else "INFO"
    setup_logging(log_level)
    # ---------------------------

    # --- Main Argument Parsing (No --config needed) ---
    parser = argparse.ArgumentParser(
         description="Local Voice Assistant (PTT Mode Only)",
         parents=[pre_parser]
    )
    parser.add_argument('--ner', action='store_true', help='Enable NER service and client')
    args = parser.parse_args()
    logger.debug(f"Parsed arguments: {args}")

    # --- Load Configuration from Environment Variables ---
    logger.info("Loading configuration from environment variables...")
    try:
        model_size = os.getenv('MODEL_SIZE', 'small')
        device = os.getenv('DEVICE', 'cpu')
        compute_type = os.getenv('COMPUTE_TYPE', 'int8')
        beam_size = int(os.getenv('BEAM_SIZE', '1'))
        language = os.getenv('LANGUAGE', 'en-US')
        sample_rate = int(os.getenv('SAMPLE_RATE', '16000'))
        vad_aggressiveness = int(os.getenv('VAD_AGGRESSIVENESS', '2'))
        mic_name = os.getenv('MIC_NAME')
        llm_provider = os.getenv('LLM_PROVIDER', 'google')
        ptt_hotkey = os.getenv('PTT_HOTKEY', 'option')
        min_ptt_duration = float(os.getenv('MIN_PTT_DURATION', '1.2'))
        ner_service_url = 'http://localhost:5001/extract' if args.ner else None
        logger.info("Configuration loaded successfully from environment.")
        logger.debug(f"  MODEL_SIZE={model_size}, DEVICE={device}, COMPUTE_TYPE={compute_type}, BEAM_SIZE={beam_size}")
        logger.debug(f"  LANGUAGE={language}, SAMPLE_RATE={sample_rate}, VAD_AGGRESSIVENESS={vad_aggressiveness}, MIC_NAME={mic_name}")
        logger.debug(f"  LLM_PROVIDER={llm_provider}")
        logger.debug(f"  PTT_HOTKEY={ptt_hotkey}, MIN_PTT_DURATION={min_ptt_duration}")
        logger.debug(f"  NER_SERVICE_URL={ner_service_url}")
    except ValueError as e:
        logger.error(f"❌ Configuration Error: Invalid numeric value in environment variable. {e}")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Unexpected error loading configuration from environment: {e}")
        sys.exit(1)

    from .orchestrator import Orchestrator
    global global_notification_manager
    _orchestrator_instance = None
    try:
        logger.info("Initializing Orchestrator...")
        config = {
            'model_size': model_size,
            'device': device,
            'compute_type': compute_type,
            'beam_size': beam_size,
            'language': language,
            'sample_rate': sample_rate,
            'vad_aggressiveness': vad_aggressiveness,
            'mic_name': mic_name,
            'llm_provider': llm_provider,
            'ptt_hotkey': ptt_hotkey,
            'min_ptt_duration': min_ptt_duration,
            'ner_service_url': ner_service_url if args.ner else None
        }
        _orchestrator_instance = Orchestrator(config)
        global_notification_manager = _orchestrator_instance.notification_manager
        logger.info("Starting Orchestrator background tasks...")
        _orchestrator_instance.start()
        logger.info("Orchestrator tasks started.")
    except Exception as e:
        logger.exception(f"💥 Fatal error during orchestrator setup or start: {e}")
        return

if __name__ == '__main__':
    # Set up basic logging first
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATEFMT)
    
    run_orchestrator()
    logger.info("🚀 Voice Assistant running. Press Ctrl+C to exit.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("👋 Keyboard interrupt received. Exiting...")
        sys.exit(0)

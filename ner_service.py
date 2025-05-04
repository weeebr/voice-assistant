import logging
import os
import sys
from flask import Flask, request, jsonify
import torch # Import torch
import logging.handlers # Import handlers
import warnings # <-- Import warnings module

# --- Suppress specific UserWarning from transformers --- 
warnings.filterwarnings(
    "ignore", 
    message="The sentencepiece tokenizer that you are converting to a fast tokenizer uses the byte fallback option.*", 
    category=UserWarning, 
    module="transformers.convert_slow_tokenizer"
)
# --- Suppress Semaphore Leak Warning --- 
warnings.filterwarnings(
    "ignore", 
    message="resource_tracker: There appear to be.*leaked semaphore objects.*", 
    category=UserWarning
    # module="multiprocessing.resource_tracker" # Optionally add module for more specificity
)
# ------------------------------------------------------

# --- Shared Logging Configuration (Match cli.py) ---
LOG_FILENAME = 'last_run.log' # Log file in the root directory
LOG_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
# -----------------------------------------------------

# Get the logger for this service
logger = logging.getLogger("NERService")
logger.setLevel(logging.DEBUG) # Set service logger level to DEBUG

# --- Remove existing handlers (important!) ---
for handler in logger.handlers[:]:
    logger.removeHandler(handler)
# Prevent logs from propagating to the root logger if it has handlers (like console)
logger.propagate = False 
# ---------------------------------------------

# --- File Handler for NER Service ---
try:
    # Create formatter
    formatter = logging.Formatter(LOG_FORMAT, datefmt=LOG_DATEFMT)
    
    # Create file handler
    file_handler = logging.FileHandler(LOG_FILENAME, mode='a', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG) # Log all DEBUG messages from this service to the file
    file_handler.setFormatter(formatter)
    
    # Add ONLY the file handler to this specific logger
    logger.addHandler(file_handler)
    logger.info(f"NERService logging configured. Level: DEBUG. Outputting ONLY to file: {LOG_FILENAME}")
except Exception as e:
    # Fallback to basic console logging if file setup fails
    logging.basicConfig(level=logging.ERROR, format=LOG_FORMAT, datefmt=LOG_DATEFMT)
    logger.error(f"Failed to configure file logging for NERService to {LOG_FILENAME}: {e}. Falling back to basic console logging for errors.")
# ---------------------------------

# --- Configuration ---
# Determine device (MPS if available on Mac, otherwise CPU)
if torch.backends.mps.is_available() and torch.backends.mps.is_built():
    DEVICE = "mps"
else:
    DEVICE = "cpu"
logger.info(f"Using device: {DEVICE}")
# Select the model - use a specific repo_id for a potentially smaller/faster version if needed
MODEL_REPO_ID = "urchade/gliner_base"
# --------------------

# --- REMOVE SUPPORTED TYPES --- 
# SUPPORTED_NER_TYPES = {
#     "Person", "Company", "Place", "State", "City", "Country", "Government",
#     "Location",
#     # Add any other labels the chosen GLiNER model supports well and you want to allow
# }
# logger.info(f"Service configured to support NER types: {SUPPORTED_NER_TYPES}")
# ------------------------------

# --- Load GLiNER Model --- 
GLINER_MODEL = None
GLINER_MODEL_NAME = os.getenv("GLINER_MODEL", "urchade/gliner_medium-v2.1") # Use env var or default

logger.info(f"Attempting to load GLiNER model: {GLINER_MODEL_NAME}...")
try:
    # Try importing GLiNER first
    from gliner import GLiNER
    # Load the model
    GLINER_MODEL = GLiNER.from_pretrained(GLINER_MODEL_NAME)
    logger.info(f"✅ GLiNER model '{GLINER_MODEL_NAME}' loaded successfully.")
except ImportError:
    logger.error("❌ Failed to import GLiNER. Service cannot run. Install with: pip install gliner")
    GLINER_MODEL = None # Ensure it's None
    # Optionally exit: sys.exit(1)
except Exception as e:
    logger.exception(f"❌💥 Failed to load GLiNER model '{GLINER_MODEL_NAME}': {e}")
    GLINER_MODEL = None # Ensure it's None
# -------------------------

# --- Flask App Setup --- 
app = Flask(__name__)

def predict_entities(text, types, threshold):
    """Core prediction logic using the loaded GLiNER model."""
    try:
        logger.info(f"Running prediction for types: {types} (threshold: {threshold})")
        logger.debug(f"Passing to GLINER_MODEL.predict_entities: text='{text[:100]}...', types={types}, threshold={threshold}") 
        entities = GLINER_MODEL.predict_entities(text, types, threshold=threshold)
        logger.info(f"Prediction returned {len(entities)} entities.")
        logger.debug(f"Raw entities from GLINER_MODEL: {entities}")
        return entities
    except Exception as e:
        logger.exception(f"Error during GLiNER prediction: {e}")
        return None # Indicate error

@app.route('/extract', methods=['GET'])
def handle_extract():
    """Handles standard extraction, parsing types intelligently."""
    text = request.args.get('text')
    types_param = request.args.get('types') 
    threshold = float(request.args.get('threshold', 0.5))

    if not text or not types_param:
        return jsonify({"error": "Missing required parameters: text and types"}), 400

    logger.info(f"Received /extract request. Text length: {len(text)}, Types param: '{types_param}'")

    # --- Parse types_param intelligently --- 
    parsed_types = [] # Changed variable name
    raw_types = []
    is_comma_separated = ',' in types_param
    
    if is_comma_separated:
        logger.debug("Parsing types parameter as comma-separated list.")
        raw_types = [t.strip() for t in types_param.split(',') if t.strip()]
    else:
        logger.debug("Parsing types parameter as space-separated string.")
        raw_types = [t.strip() for t in types_param.split() if t.strip()] # Split by space
    
    # Capitalize all parsed types directly for passing to GLiNER
    parsed_types = [t.capitalize() for t in raw_types if t] # Ensure no empty strings
    # Remove duplicates while preserving order (if needed, less critical now)
    seen = set()
    final_types_list = [x for x in parsed_types if not (x in seen or seen.add(x))]
    # -----------------------------------------------------
             
    if not final_types_list:
         # This error now means the types parameter was empty or only whitespace/commas
         logger.error(f"No types found after parsing types parameter: '{types_param}'")
         return jsonify({"error": f"No types specified in 'types' parameter ('{types_param}')"}), 400
    # -------------------------------------------

    logger.info(f"Passing dynamically parsed types to prediction: {final_types_list}")
    entities = predict_entities(text, final_types_list, threshold)

    if entities is None:
         return jsonify({"error": "Prediction failed internally"}), 500

    return jsonify(entities)

# --- Run the Service --- 
if __name__ == '__main__':
    port = int(os.environ.get("NER_SERVICE_PORT", 5001))
    logger.info(f"Starting NER service on http://localhost:{port}")
    # Use waitress or gunicorn for production instead of Flask's dev server
    # For development:
    app.run(host='0.0.0.0', port=port, debug=False) # debug=False recommended for stability 

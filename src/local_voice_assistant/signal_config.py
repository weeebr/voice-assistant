import logging

# Get a logger instance (assuming orchestrator might configure the root logger)
# Alternatively, configure a specific logger here if needed.
logger = logging.getLogger(__name__)

# --- Configuration moved to signal_config.json --- 

logger.info("Signal configuration is now loaded from signal_config.json")

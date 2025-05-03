#!/bin/bash
# Starts the standalone NER microservice.

# Strict mode: exit on errors, exit on unset variables, pipe failures count as errors
set -euo pipefail

# --- Configuration (Should match start.sh for consistency) ---
VENV_DIR="venv"
REQUIREMENTS_FILE="requirements.txt"
NER_SERVICE_SCRIPT="ner_service.py"

# --- Script Logic ---
echo "🚀 Starting NER Service Setup..."

# 1. Ensure Virtual Environment Exists
echo "🐍 Ensuring virtual environment '$VENV_DIR' exists..."
if [ ! -d "$VENV_DIR" ]; then
    echo "❌ Virtual environment '$VENV_DIR' not found. Please run the main ./start.sh script first to create it." 
    exit 1
fi
echo "👍 Virtual environment exists."

# 2. Activate Virtual Environment
echo "⚡ Activating virtual environment..."
source "$VENV_DIR/bin/activate"
echo "✅ Virtual environment activated (`which python`)."

# 3. Ensure Dependencies (Optional but Recommended for standalone use)
# Re-running install ensures Flask and gliner are present if requirements changed.
echo "📦 Ensuring dependencies from '$REQUIREMENTS_FILE' are installed..."
pip install --quiet --disable-pip-version-check -r "$REQUIREMENTS_FILE"
if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies from $REQUIREMENTS_FILE."
    exit 1
fi
echo "✅ Dependencies checked/installed."

# 4. Run the NER Service
echo "▶️ Starting NER Service (using script: $NER_SERVICE_SCRIPT)..."
echo "(Running command: python $NER_SERVICE_SCRIPT)"

# Check if the script exists
if [ ! -f "$NER_SERVICE_SCRIPT" ]; then
    echo "❌ NER service script '$NER_SERVICE_SCRIPT' not found."
    exit 1
fi

echo "-------------------------------------"
# Use exec to replace the shell process with the Python process
# Use 'python' which will resolve to the venv python after activation
exec python "$NER_SERVICE_SCRIPT"

# Note: The script won't reach here if 'exec' is used successfully.
echo "-------------------------------------"
echo "❌ Failed to execute Python script '$NER_SERVICE_SCRIPT'."
exit 1 

#!/bin/bash
# Strict mode: exit on errors, exit on unset variables, pipe failures count as errors
set -euo pipefail

# --- Configuration ---
VENV_DIR="venv"                      # Name of the virtual environment directory
# Use the specific Python where libraries were installed
# PYTHON_EXEC="/Library/Frameworks/Python.framework/Versions/3.10/bin/python3" # Command to use for Python 3
REQUIREMENTS_FILE="requirements.txt" # Path to your requirements file
PACKAGE_ENTRY_POINT="voice-assistant" # The command provided by your package
MAIN_MODULE_PATH="src.local_voice_assistant.cli"
NER_SERVICE_SCRIPT="ner_service.py"
NER_SERVICE_LOG="ner_service.log"

# --- Cleanup Function --- 
# This function will be called when the script exits
cleanup() {
    echo "🧹 Performing cleanup..."
    # Check if NER_SERVICE_PID is set and refers to a running process
    if [ -n "${NER_SERVICE_PID+x}" ] && ps -p "$NER_SERVICE_PID" > /dev/null; then
        echo "🔪 Stopping background NER service (PID: $NER_SERVICE_PID)..."
        # Send SIGTERM first for graceful shutdown, then SIGKILL if necessary
        kill "$NER_SERVICE_PID" || true 
        sleep 1 # Give it a moment to terminate
        # Force kill if still running (optional)
        # kill -9 "$NER_SERVICE_PID" 2>/dev/null || true 
        echo "✅ NER service stop signal sent."
    else
        echo "🤷 NER service PID not found or process already stopped."
    fi
}

# Set the trap to call the cleanup function on script exit (EXIT signal)
trap cleanup EXIT

# --- Script Logic ---
echo "🚀 Starting Voice Assistant Setup..."

# --- ADDED: Clean Python Cache ---
echo "🧹 Cleaning Python cache directories (__pycache__)..."
find . -path "*/__pycache__" -type d -exec rm -rf {} +
echo "✅ Python cache cleaned."
# ---------------------------------

# Ensure we are in the project root (where the script, venv, requirements.txt should be)
# Optional: cd "$(dirname "$0")" # Uncomment if script might be run from elsewhere

# 1. Ensure Virtual Environment Exists
echo "🐍 Ensuring virtual environment '$VENV_DIR' exists..."
if [ ! -d "$VENV_DIR" ]; then
    echo "💨 Virtual environment not found. Creating with python3..."
    # $PYTHON_EXEC -m venv "$VENV_DIR"
    python3 -m venv "$VENV_DIR" # Use python3 directly
    if [ $? -ne 0 ]; then
        echo "❌ Failed to create virtual environment. Please check your Python 3 installation and ensure 'python3' is in your PATH."
        exit 1
    fi
    echo "✅ Virtual environment created."
else
    echo "👍 Virtual environment already exists."
fi

# 2. Activate Virtual Environment
echo "⚡ Activating virtual environment..."
# Use source to activate in the current script's shell session
# shellcheck source=/dev/null # Tell shellcheck linters to ignore this line
source "$VENV_DIR/bin/activate"
echo "✅ Virtual environment activated (`which python`)."

# 3. Upgrade Pip
echo "⏫ Upgrading pip within the virtual environment..."
# Use explicit path to python within venv to run pip module
"$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check --upgrade pip 
if [ $? -ne 0 ]; then
    echo "⚠️ Failed to upgrade pip (continuing anyway)..."
fi
echo "✅ Pip upgrade checked."

# 4. Install/Update Dependencies
echo "📦 Installing/updating dependencies from '$REQUIREMENTS_FILE'..."
# Use explicit path to python within venv to run pip module
"$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check -r "$REQUIREMENTS_FILE"
if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies from $REQUIREMENTS_FILE."
    exit 1
fi
echo "✅ Dependencies checked/installed."

# 5. Install Local Package in Editable Mode
echo "🛠️ Ensuring local package is installed in editable mode..."
# Use explicit path to python within venv to run pip module
"$VENV_DIR/bin/python" -m pip install --quiet --disable-pip-version-check -e .
if [ $? -ne 0 ]; then
    echo "❌ Failed to install local package in editable mode."
    exit 1
fi
echo "✅ Local package installation checked."

# --- Start Background NER Service --- 
NER_SERVICE_PID="" # Initialize PID variable
NER_PORT=5001 # Define the port used by the service

echo "🧠 Checking for existing process on port $NER_PORT..."
# Use lsof to find the PID listening on the port. -t gives only the PID.
# Redirect errors to /dev/null in case port is not in use.
EXISTING_PID=$(lsof -t -i :"$NER_PORT" 2>/dev/null || true)

if [ -n "$EXISTING_PID" ]; then
    echo "⚠️ Found existing process (PID: $EXISTING_PID) on port $NER_PORT. Attempting to stop it..."
    kill "$EXISTING_PID" || true # Send SIGTERM, ignore error if already stopped
    sleep 1 # Give it a moment to terminate
    # Verify if it stopped
    if ps -p "$EXISTING_PID" > /dev/null; then
        echo "⛔ Process $EXISTING_PID did not stop gracefully. Trying force kill..."
        kill -9 "$EXISTING_PID" || true
        sleep 1
    fi
    # Final check
    if lsof -t -i :"$NER_PORT" > /dev/null 2>&1; then
         echo "❌ ERROR: Failed to free port $NER_PORT. Please stop the process (PID: $EXISTING_PID) manually." 
         exit 1
    else
         echo "✅ Port $NER_PORT cleared."
    fi
else
    echo "👍 Port $NER_PORT is free."
fi

echo "🧠 Starting background NER Service..."
if [ ! -f "$NER_SERVICE_SCRIPT" ]; then
    echo "⚠️ NER service script '$NER_SERVICE_SCRIPT' not found. NER features will fail."
else
    echo "   (Logs are configured via Python logging to jarvis.log)"
    # Use explicit path to python within venv
    "$VENV_DIR/bin/python" "$NER_SERVICE_SCRIPT" & # Launch in background without shell redirection
    NER_SERVICE_PID=$! # Capture the PID of the background process
    echo "✅ NER Service started in background (PID: $NER_SERVICE_PID)."
fi
# ------------------------------------

# 6. Run the Main Application
echo "▶️ Starting Main Voice Assistant (using module: $MAIN_MODULE_PATH)..."
echo "(Running command: $VENV_DIR/bin/python -m $MAIN_MODULE_PATH $@)"
echo "-------------------------------------"

# Execute the Python module directly, passing all script arguments ($@)
# Use exec to replace the shell process with the Python process
# Use explicit path to python within venv
exec "$VENV_DIR/bin/python" -m "$MAIN_MODULE_PATH" "$@"

# Note: The script won't reach here if 'exec' is used successfully.
echo "-------------------------------------"
echo "❌ Failed to execute Python module '$MAIN_MODULE_PATH'."
exit 1 

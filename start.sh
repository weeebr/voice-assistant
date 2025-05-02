#!/bin/bash
# Strict mode: exit on errors, exit on unset variables, pipe failures count as errors
set -euo pipefail

# --- Configuration ---
VENV_DIR="venv"                      # Name of the virtual environment directory
# Use the specific Python where libraries were installed
PYTHON_EXEC="/Library/Frameworks/Python.framework/Versions/3.10/bin/python3" # Command to use for Python 3
REQUIREMENTS_FILE="requirements.txt" # Path to your requirements file
PACKAGE_ENTRY_POINT="voice-assistant" # The command provided by your package

# --- Script Logic ---
echo "🚀 Starting Voice Assistant Setup..."

# Ensure we are in the project root (where the script, venv, requirements.txt should be)
# Optional: cd "$(dirname "$0")" # Uncomment if script might be run from elsewhere

# 1. Ensure Virtual Environment Exists
echo "🐍 Ensuring virtual environment '$VENV_DIR' exists..."
if [ ! -d "$VENV_DIR" ]; then
    echo "💨 Virtual environment not found. Creating with $PYTHON_EXEC..."
    $PYTHON_EXEC -m venv "$VENV_DIR"
    if [ $? -ne 0 ]; then
        echo "❌ Failed to create virtual environment. Please check your Python 3 installation."
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
pip install --quiet --disable-pip-version-check --upgrade pip
if [ $? -ne 0 ]; then
    echo "⚠️ Failed to upgrade pip (continuing anyway)..."
fi
echo "✅ Pip upgrade checked."

# 4. Install/Update Dependencies
echo "📦 Installing/updating dependencies from '$REQUIREMENTS_FILE'..."
pip install --quiet --disable-pip-version-check -r "$REQUIREMENTS_FILE"
if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies from $REQUIREMENTS_FILE."
    exit 1
fi
echo "✅ Dependencies checked/installed."

# 5. Install Local Package in Editable Mode
echo "🛠️ Ensuring local package is installed in editable mode..."
pip install --quiet --disable-pip-version-check -e .
if [ $? -ne 0 ]; then
    echo "❌ Failed to install local package in editable mode."
    exit 1
fi
echo "✅ Local package installation checked."

# 6. Run the Application via Module
MODULE_PATH="src.local_voice_assistant.cli"
echo "▶️ Starting Voice Assistant (using module: $MODULE_PATH)..."
echo "(Running command: python -m $MODULE_PATH $@)" # Show the command being run
echo "-------------------------------------"

# Execute the Python module directly, passing all script arguments ($@)
# Use exec to replace the shell process with the Python process
exec "$PYTHON_EXEC" -m "$MODULE_PATH" "$@"

# Note: The script won't reach here if 'exec' is used successfully.
echo "-------------------------------------"
echo "❌ Failed to execute Python module '$MODULE_PATH'."
exit 1 

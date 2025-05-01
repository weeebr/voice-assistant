#!/bin/bash
# Strict mode: exit on errors, exit on unset variables, pipe failures count as errors
set -euo pipefail

# --- Configuration ---
VENV_DIR="venv"                      # Name of the virtual environment directory
PYTHON_EXEC="python3"                # Command to use for Python 3
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

# 3. Install/Update Dependencies
echo "📦 Installing/updating dependencies from '$REQUIREMENTS_FILE'..."
pip install --quiet --disable-pip-version-check -r "$REQUIREMENTS_FILE"
if [ $? -ne 0 ]; then
    echo "❌ Failed to install dependencies from $REQUIREMENTS_FILE."
    # Optional: Deactivate before exiting on error?
    # deactivate
    exit 1
fi
echo "✅ Dependencies checked/installed."

# 4. Install Local Package in Editable Mode
echo "🛠️ Ensuring local package is installed in editable mode..."
pip install --quiet --disable-pip-version-check -e .
if [ $? -ne 0 ]; then
    echo "❌ Failed to install local package in editable mode."
    # deactivate
    exit 1
fi
echo "✅ Local package installation checked."

# 5. Run the Application
echo "▶️ Starting Voice Assistant..."
echo "(Running command: $PACKAGE_ENTRY_POINT $@)" # Show the command being run
echo "-------------------------------------"

# Execute the voice assistant command, passing all script arguments ($@)
# Use exec to replace the shell process with the voice-assistant process
# This ensures signals (like Ctrl+C) go directly to the application.
exec "$PACKAGE_ENTRY_POINT" "$@"

# Note: The script won't reach here if 'exec' is used successfully.
# If 'exec' fails (e.g., command not found), the script will exit due to set -e.
# Adding a fallback message just in case.
echo "-------------------------------------"
echo "❌ Failed to execute '$PACKAGE_ENTRY_POINT'. Please ensure it's installed correctly in the venv."
exit 1 

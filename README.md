# Local AI Voice Assistant

This project implements a local, no-cost, privacy-preserving voice assistant with the focus on being responsive, efficient and quick both when managing and customizing commands (→ config.py) and during runtime.

## Features ✨

- **Zero-Cost Voice Processing:** Leverages local processing to minimize external dependencies and costs. 💰🚫
- **Push-To-Talk Activation:** Uses a configurable hotkey with a minimum duration threshold for activation. 🎙️⌨️
- **LLM Integration:** Supports calls to Anthropic, Google, and OpenAI models for advanced tasks. 🧠 (API keys required)
- **Multi-Language Support:** Switch between English, German, and Swiss German modes. [🇬🇧/🇩🇪/🇨🇭]
- **Text Transformation Templates:** Apply predefined or custom templates to your spoken text. 🔄📝
- **Local Transcription Logging:** Keeps a record of all spoken text locally for privacy and review. 🔒📜
- **Usage Statistics:** Includes word counts and other relevant statistics. 📊🔢
- **Named Entity Recognition (NER):** Extracts entities like names, locations, organizations from spoken text. 🧐

## Templates 🪄

Use templates to transform your input in various ways:

- **{text} Token:** Represents the text transcribed from your speech.
- **{clipboard} Token:** Represents the current content of your system clipboard.

**Examples:**

- `Translate into Central Swiss German (Schweizerdeutsch) and provide only the translation. Here's the text: {text}`

- `Summarize the following: {clipboard}`

## Quick Start 🚀

1.  **Clone the repository** (if you haven't already):
    ```bash
    git clone <repository-url>
    cd <repository-directory>
    ```
2.  **Run the start script:**
    ```bash
    ./start.sh
    ```
    This script handles everything: virtual environment setup, dependency installation, background service startup, and running the main application.

## Setup Details (Handled by `start.sh`)

The `./start.sh` script automates the following steps:

1.  **Virtual Environment:** Creates/activates a Python 3.10+ virtual environment in `./venv`.
2.  **Dependencies:** Installs required packages from `requirements.txt`.
3.  **Local Package:** Installs the `voice-assistant` package in editable mode (`pip install -e .`).
4.  **NER Service:** Starts the Named Entity Recognition service (`ner_service.py`) in the background.

## Configuration ⚙️

Edit `config.yaml` to customize:

- **API Keys:** Set keys for LLM providers (e.g., `anthropic_api_key`, `openai_api_key`).
- **Hotkey Duration:** Optionally adjust `min_hotkey_duration` (in seconds).
- **Microphone:** (Optional) Force a specific microphone by setting `mic_name`.

## Usage ▶️

Simply run the start script:

```bash
./start.sh [arguments]
```

Any arguments provided to `start.sh` will be passed directly to the main voice assistant application (e.g., to specify modes like `--mode hotkey`, though the script default might handle this).

The script will:

- Set up the environment.
- Start the background NER service.
- Launch the main voice assistant application.

Press the configured hotkey (<cmd> by default) to interact.

The NER service and other background processes started by the script will be automatically cleaned up when you stop the main application (e.g., with Ctrl+C).

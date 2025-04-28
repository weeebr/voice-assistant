# Local Voice Assistant

This project implements a local, privacy-preserving voice assistant following a multi-phase roadmap:

- **Phase 1**: Foundations & Environment Setup
- **Phase 2**: Audio I/O & Low-Latency Capture
- **Phase 3**: Speech-to-Text with Faster Whisper
- **Phase 4**: Wake-Word Detection
- **Phase 5**: Hotkey-Based Push-to-Talk
- **Phase 6**: Post-Processing & Grammar Correction
- **Phase 7**: (Optional) Local LLM for NLU/NLG
- **Phase 8**: Orchestration & Architecture
- **Phase 9**: Testing & Benchmarking
- **Phase 10**: Deployment & Packaging

## Quick Setup

```bash
python3 -m venv ~/.local-voice-env && source ~/.local-voice-env/bin/activate && pip install -r requirements.txt && pip install -e . && voice-assistant --mode both
```

## Setup

1. Create and activate a Python 3.10+ virtual environment:
   ```bash
   python3 -m venv ~/.local-voice-env
   source ~/.local-voice-env/bin/activate
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   pip install -e .
   ```
3. (Optional) To enable grammar correction, install Java (OpenJDK 8+):
   ```bash
   brew install openjdk
   ```
4. Edit `config.yaml`:
   - Set `picovoice_access_key` and update `keyword_paths` with your wake-word file (e.g., `hey-assistant.ppn`).
   - Optionally adjust `wake_sensitivity` (0.0 to 1.0) to tune wake-word detection; higher values increase sensitivity.
5. (Optional) To force a specific mic, set `mic_name` to the device name (or substring) in `config.yaml`.
   On macOS, leaving it blank will auto-select the built-in microphone.

## Usage

```bash
voice-assistant --mode trigger    # wake-word mode
voice-assistant --mode hotkey     # push-to-talk mode
voice-assistant --mode both       # both modes
```

On startup you should see INFO messages like:

```
Assistant starting in mode: both.
Wake-word detection enabled.
Hotkey (push-to-talk) detection enabled.
```

If you don’t see these, the assistant may not have initialized correctly.
In environments where global hotkeys aren’t available, you can use the fallback PTT:
• When you see “Fallback PTT: press ENTER in console to toggle recording”, hit ENTER to start a recording session.
• Press ENTER again to stop and process the recorded speech.

Press the configured hotkey (<cmd> by default) or say your wake-word to interact.

- [ ] **Phase 1: Foundations & Environment Setup 🛠️🐍**

  - [ ] **Install system prerequisites**
    - [ ] Install Homebrew (if not already) 🍺
    - [ ] Install Python 3.10+ via Homebrew (or use pyenv) 🐍
    - [ ] Grant Terminal “Accessibility” rights in System Settings (for global hotkeys) 🔑
  - [ ] **Create isolated Python environment**
    - [ ] `python3 -m venv ~/.local-voice-env`
    - [ ] `source ~/.local-voice-env/bin/activate`
  - [ ] **Core library installations (pip) 📦**
    - [ ] `pip install faster-whisper soundcard pvporcupine webrtcvad pynput language-tool-python`
    - [ ] _(Optional)_ `pip install llama-cpp-python transformers torch` for local LLM support 🤖
  - [ ] **Configure Apple‑Silicon acceleration**
    - [ ] Verify PyTorch MPS backend works:
      ```bash
      python -c "import torch; print(torch.backends.mps.is_available())"
      ```
    - [ ] Set CTranslate2 to use Apple Neural Engine / Accelerate for Faster Whisper ⚡

- [ ] **Phase 2: Audio I/O & Low‑Latency Capture 🎙️⚡**

  - [ ] **SoundCard microphone streaming**
    - [ ] Identify default mic:
      ```python
      import soundcard as sc
      print(sc.default_microphone())
      ```
    - [ ] Open 16 kHz mono stream, small buffer (20 ms frames)
  - [ ] **Sample-rate conversion** (if needed)
    - [ ] Install `scipy` or `librosa` for resampling to 16 kHz
    - [ ] Integrate on‑the‑fly downsampling in audio loop
  - [ ] **Voice Activity Detection (VAD)**
    - [ ] Configure `webrtcvad.Vad(2)` for medium sensitivity
    - [ ] Feed 20 ms frames to VAD to detect end‑of‑speech (trigger-mode)

- [ ] **Phase 3: Speech‑to‑Text Pipeline with Faster Whisper 🤖✨**

  - [ ] **Model selection & download**
    - [ ] Choose model size: `tiny`/`base` for fastest, `small`/`medium` for balance
    - [ ] `from faster_whisper import WhisperModel; model = WhisperModel("small", device="cpu", compute_type="int8")`
  - [ ] **CTranslate2 / quantization settings**
    - [ ] Enable int8 quantization for speed
    - [ ] Set `beam_size=1` (greedy) to reduce latency
  - [ ] **Test real‑time transcription**
    - [ ] Record short clip (2 s) → transcribe → measure end‑to‑end time < 2 s

- [ ] **Phase 4: Wake‑Word Detection (Trigger‑Mode) 🐷🔑**

  - [ ] **Picovoice Porcupine setup**
    - [ ] **Sign up** at Picovoice Console → get `PICOVOICE_ACCESS_KEY` 🔑
    - [ ] Download / train `hey-assistant.ppn` keyword file via Console
  - [ ] **Integrate `pvporcupine`**
    - [ ] `import pvporcupine; pp = pvporcupine.create(access_key=..., keyword_paths=["hey-assistant.ppn"])`
    - [ ] Continuously read 512‑sample frames → `pp.process(frame)` → on match trigger STT
  - [ ] **Fallback / false‑positive mitigation**
    - [ ] Use VAD to confirm actual speech after wake‑word
    - [ ] Debounce wake callback (ignore additional triggers for 1 s)

- [ ] **Phase 5: Hotkey‑Based Push‑to‑Talk 🎹🔴**

  - [ ] **Global key listener with `pynput`**
    - [ ] `from pynput import keyboard` → monitor `<cmd>` press & release
    - [ ] On `<cmd>` down → start audio capture; on release → stop & process
  - [ ] **Threading / async coordination**
    - [ ] Run key listener in separate thread to avoid blocking audio loop
    - [ ] Use thread‑safe queue to pass raw audio chunks to STT thread

- [ ] **Phase 6: Post‑Processing & Grammar Correction ✍️✅**

  - [ ] **LanguageTool integration**
    - [ ] No API key needed; Java backend auto‑downloads on first run
    - [ ] `import language_tool_python; tool_en = LanguageTool('en-US'); tool_de = LanguageTool('de-DE')`
    - [ ] `corrected = tool_en.correct(raw_text)` (choose tool based on detected language)
  - [ ] **Language detection (optional)**
    - [ ] If using Whisper’s `language=` arg or run `langdetect.detect()` to pick correct tool
  - [ ] **Final formatting**
    - [ ] Normalize quotes: German „…“ vs English “…”
    - [ ] Ensure proper capitalization & punctuation

- [ ] **Phase 7: (Optional) Local LLM for NLU/NLG 🧠💬**

  - [ ] **Model & framework choice**
    - [ ] `llama-cpp-python` + LLaMA 2 (7B int4) with Metal acceleration
    - [ ] Or Hugging Face Transformers with `device="mps"`
  - [ ] **Download & quantize models**
    - [ ] If using HF: set `HUGGING_FACE_HUB_TOKEN` env var 🔑
    - [ ] `transformers-cli login` → download model to `~/.cache/huggingface/`
  - [ ] **Inference integration**
    - [ ] Wrap transcription output → pass as prompt to LLM
    - [ ] Stream / batch generate tokens for short responses

- [ ] **Phase 8: Orchestration & Architecture 🏗️📈**

  - [ ] **Main process structure**
    - [ ] **Thread 1**: Wake‑word listener → triggers recording
    - [ ] **Thread 2**: Hotkey listener → triggers recording
    - [ ] **Thread 3**: Audio capture & VAD → raw PCM frames → buffer
    - [ ] **Thread 4**: STT & post‑processing → final text output
  - [ ] **Inter-thread communication**
    - [ ] Use `queue.Queue` for passing audio data and control events
    - [ ] Define clear event types: `WAKE_TRIGGER`, `HOTKEY_DOWN`, `HOTKEY_UP`, `AUDIO_READY`
  - [ ] **Configuration & logging**
    - [ ] Central `config.yaml` or `.env` for model paths, API keys, buffer sizes
    - [ ] Structured logging (`logging` module) for events, latencies, errors

- [ ] **Phase 9: Testing, Benchmarking & Optimization 🔍📊**

  - [ ] **Unit tests** for each component (wake‑word, hotkey, audio, STT, grammar)
  - [ ] **Integration tests**: simulate a full request from wake → output
  - [ ] **Latency benchmarks**: record and log end‑to‑end times per mode
  - [ ] **Resource monitoring**: CPU, memory, thermal on M1 Pro → optimize buffer sizes & threading
  - [ ] **Error handling & retries**: handle misfires, VAD misses, model load failures

- [ ] **Phase 10: Deployment & Packaging 📦🚀**
  - [ ] **CLI entrypoint**: `voice-assistant --mode=trigger|hotkey`
  - [ ] **Launch at login** (optional): create a Mac LaunchAgent plist
  - [ ] **Distribution**: package with `pyinstaller` or `shiv` for easy startup
  - [ ] **Documentation**: README with setup steps, key bindings, config options

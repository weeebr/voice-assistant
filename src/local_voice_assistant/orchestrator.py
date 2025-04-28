import threading
import time
import logging
import subprocess
import os
# Initialize Anthropic client for Swiss German translation (requires ANTHROPIC_API_KEY)
try:
    from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT
    import httpx
    _anthropic_client = None
    _api_key = "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"
    if _api_key:
        _anthropic_client = Anthropic(api_key=_api_key)
    else:
        logging.info("ANTHROPIC_API_KEY not set; Swiss German translation disabled.")
except ImportError:
    _anthropic_client = None
    logging.info("anthropic or httpx package not installed; Swiss German translation disabled.")
except Exception as e:
    logging.error(f"Anthropic init failed: {e}")
    _anthropic_client = None

from .audio_interface import AudioCapture
from .vad import VAD
from .stt import SpeechToText
from .wake_word import WakeWordDetector
from .hotkey import HotkeyListener
from .post_processing import PostProcessor

class Orchestrator:
    """
    Coordinates wake-word, hotkey, audio capture, STT, and post-processing.
    """
    # List of phrases to skip copying/pasting
    FILTERED_PHRASES = ["thank you", "you", "thanks for watching", "thank you for watching"]
    
    @staticmethod
    def is_filtered_phrase(text):
        """Check if text is a filtered phrase that should be ignored for clipboard operations."""
        if not text:
            return True
        
        # Normalize text: lowercase, strip whitespace and punctuation
        normalized = text.strip().lower()
        normalized_no_punct = normalized.replace(".", "").replace("!", "").replace("?", "").strip()
        
        # Check if it's one of our filtered phrases
        return (normalized.rstrip('.!?') in Orchestrator.FILTERED_PHRASES or 
                normalized_no_punct in Orchestrator.FILTERED_PHRASES)
    
    def __init__(self, config):
        # Whether to ignore hotkey events (e.g., during paste)
        self.hotkey_suppressed = False
        self.config = config
        # Audio capture: sample rate, channels, and optional mic name override
        self.audio = AudioCapture(
            sample_rate=config.get('sample_rate', 16000),
            channels=config.get('channels', 1),
            mic_name=config.get('mic_name')
        )
        self.vad = VAD(config.get('vad_aggressiveness', 2))
        self.stt = SpeechToText(
            model_size=config.get('model_size', 'small'),
            device=config.get('device', 'cpu'),
            compute_type=config.get('compute_type', 'int8'),
            beam_size=config.get('beam_size', 1)
        )
        # Processing language (for post-processing); can switch at runtime via voice commands
        self.language = config.get('language', 'en-US')
        self.post = PostProcessor(self.language)
        self.mode = config.get('mode', 'trigger')
        # Initialize wake-word detector if access key provided
        self.wake_detector = None
        access_key = config.get('picovoice_access_key')
        if access_key:
            try:
                # Initialize wake-word detector with configurable sensitivity
                self.wake_detector = WakeWordDetector(
                    access_key,
                    config.get('keyword_paths', []),
                    config.get('wake_sensitivity', 0.5)
                )
            except Exception as e:
                logging.error(f"Wake-word initialization failed ({e}); wake-word mode disabled.")
                self.wake_detector = None
        # Warn if trigger mode requested but wake-word unavailable
        if self.mode in ['trigger', 'both'] and not self.wake_detector:
            logging.warning("Wake-word mode requested but no valid detector; wake-word disabled.")
        # Push-to-talk hotkey
        self.hotkey = None
        self.fallback_ptt = False
        if self.mode in ['hotkey', 'both']:
            try:
                from pynput import keyboard
                self.hotkey = HotkeyListener(keyboard.Key.cmd)
                self.hotkey.on_press_callback = self._hotkey_down
                self.hotkey.on_release_callback = self._hotkey_up
            except Exception as e:
                logging.error(f"Hotkey listener init failed ({e}); hotkey disabled.")
                self.hotkey = None
                self.fallback_ptt = True

    def start(self):
        # Startup messages (print and log)
        msg = f"Assistant starting in mode: {self.mode}."
        print(msg, flush=True)
        logging.info(msg)
        if self.wake_detector:
            msg_wake = "Wake-word detection enabled."
            print(msg_wake, flush=True)
            logging.info(msg_wake)
        # Start wake-word listener if enabled
        if self.mode in ['trigger', 'both'] and self.wake_detector:
            threading.Thread(target=self._wakeword_listener, daemon=True).start()
        if self.hotkey:
            msg_hotkey = "Hotkey (push-to-talk) detection enabled."
            print(msg_hotkey, flush=True)
            logging.info(msg_hotkey)
            try:
                self.hotkey.start()
            except Exception as e:
                logging.error(f"Hotkey listener failed to start ({e}); hotkey disabled.")
                self.hotkey = None
                self.fallback_ptt = True
        # If hotkey unavailable, fallback to CLI enter-based PTT
        if self.fallback_ptt:
            print("Fallback PTT: press ENTER in console to toggle recording", flush=True)
            threading.Thread(target=self._fallback_ptt_loop, daemon=True).start()
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logging.info("Shutting down")

    def _wakeword_listener(self):
        """
        Loop: listen for configured keywords and handle them.
        - If keyword matches a language switch (e.g., 'german' or 'english'),
          update processing language and restart listening.
        - Otherwise, treat as assistant wake word: record speech and process.
        """
        while True:
            wake_gen = self.audio.wake_audio_stream()
            for frame in wake_gen:
                if self.wake_detector.process(frame) >= 0:
                    # Close wake-word stream to release microphone before recording
                    try:
                        wake_gen.close()
                    except Exception:
                        pass
                    logging.info("Wake word detected: starting recording")
                    print("[Wake] Recording started", flush=True)
                    # Perform recording and scheduling; catch exceptions to keep listener alive
                    try:
                        self._record_and_process()
                    except Exception as e:
                        logging.error(f"Wake-word record error: {e}")
                    print("[Wake] Recording stopped", flush=True)
                    break

    def _hotkey_down(self):
        # Ignore synthetic hotkey during paste
        if self.hotkey_suppressed:
            return
        logging.info("Hotkey pressed: recording started")
        print("[PTT] Recording started", flush=True)
        self.hotkey_listening = True
        threading.Thread(target=self._hotkey_recording_loop, daemon=True).start()

    def _hotkey_up(self):
        # Ignore synthetic hotkey during paste
        if self.hotkey_suppressed:
            return
        logging.info("Hotkey released: recording stopped")
        print("[PTT] Recording stopped", flush=True)
        self.hotkey_listening = False

    def _hotkey_recording_loop(self):
        frames = []
        for frame in self.audio.speech_audio_stream():
            if not getattr(self, 'hotkey_listening', False):
                break
            frames.append(frame)
        # Offload processing to background thread
        threading.Thread(target=self._process_audio, args=(frames,), daemon=True).start()

    def _record_and_process(self):
        # Record speech until silence threshold
        logging.info("Recording started (wake-word)")
        frames = []
        silence_count = 0
        # approximate max silence frames (~0.3s)
        silence_threshold = int(0.3 / 0.02)
        for frame in self.audio.speech_audio_stream():
            frames.append(frame)
            if self.vad.is_speech(frame):
                silence_count = 0
            else:
                silence_count += 1
                if silence_count > silence_threshold:
                    break
        # Done recording, now offload processing to background thread
        logging.info("Recording stopped (wake-word), scheduling processing")
        threading.Thread(target=self._process_audio, args=(frames,), daemon=True).start()

    def _process_audio(self, frames):
        try:
            # Autodetect transcription to catch language switch prefixes
            detected = self.stt.transcribe(frames)
            raw = detected.strip()
            lower = raw.lower()
            # Swiss German via Claude 3.5 Sonnet
            if lower.startswith('swiss german'):
                # Extract text after the prefix
                rest = raw[len('swiss german'):].lstrip(' ,.!?')
                if not rest:
                    return
                # Try Swiss German translation via Claude (fallback on model 404)
                if _anthropic_client:
                    translation = None
                    for model_name in ("claude-3-5-sonnet-latest"):
                        try:
                            resp = _anthropic_client.completions.create(
                                model=model_name,
                                prompt=(
                                    HUMAN_PROMPT
                                    + "Translate the following text into Central Swiss German (a Swiss German dialect)."
                                    + " Only output the translation without explanations:\n"
                                    + rest + "\n"
                                    + AI_PROMPT
                                ),
                                stop_sequences=[HUMAN_PROMPT],
                                max_tokens_to_sample=300
                            )
                            translation = resp.completion.strip()
                            break
                        except httpx.HTTPStatusError as he:
                            if he.response.status_code == 404:
                                logging.warning(f"Model {model_name} not found, trying fallback.")
                                continue
                            logging.error(f"Swiss German translation HTTP error: {he}")
                            translation = rest
                            break
                        except Exception as e:
                            logging.error(f"Swiss German translation failed: {e}")
                            translation = rest
                            break
                    if translation is None:
                        translation = rest
                else:
                    logging.error("Anthropic client not available, Swiss German translation disabled.")
                    translation = rest
                # Sanitize and output
                sanitized = translation.replace('ß', 'ss').replace('"','"').replace('"','"')
                print(f"Assistant: {sanitized}", flush=True)
                logging.info(f"Assistant: {sanitized}")
                
                # Skip clipboard operations for filtered phrases
                if self.is_filtered_phrase(sanitized):
                    logging.info("Skipping clipboard operations for filtered courtesy phrase")
                    return
                    
                # Copy and paste
                try:
                    subprocess.run(['pbcopy'], input=sanitized.encode('utf-8'), check=True)
                    logging.info("Copied text to clipboard")
                except Exception as e:
                    logging.error(f"Failed to copy to clipboard: {e}")
                try:
                    from pynput.keyboard import Controller, Key
                    kb = Controller()
                    self.hotkey_suppressed = True
                    try:
                        with kb.pressed(Key.cmd):
                            kb.press('v')
                            kb.release('v')
                    finally:
                        self.hotkey_suppressed = False
                    logging.info("Pasted text via Cmd+V")
                except Exception as e:
                    logging.error(f"Failed to paste via Cmd+V: {e}")
                return
            # strip common trailing punctuation (e.g., comma)
            parts = raw.split(None, 1)
            cmd = parts[0].lower().strip('.,?!') if parts else ''
            if cmd in ('german', 'english'):
                # Switch processing language
                self.language = 'de-DE' if cmd == 'german' else 'en-US'
                self.post = PostProcessor(self.language)
                lang_name = 'German' if cmd == 'german' else 'English'
                print(f"[Language] Switched to {lang_name}", flush=True)
                logging.info(f"Processing language switched to {self.language}")
                # Re-transcribe full audio in new language, then drop prefix in text
                hint = self.language.split('-', 1)[0].lower()
                full_text = self.stt.transcribe(frames, language=hint)
                parts2 = full_text.strip().split(None, 1)
                text_to_process = parts2[1] if len(parts2) > 1 else ''
            else:
                # Regular transcription in current language
                hint = self.language.split('-', 1)[0].lower()
                text_to_process = self.stt.transcribe(frames, language=hint)
                
            if not text_to_process:
                return
                
            # Display and log raw recognized text
            print(f"Recognized: {text_to_process}", flush=True)
            logging.info(f"Recognized (raw): {text_to_process}")
            
            # Check if it's a filtered phrase before post-processing
            if self.is_filtered_phrase(text_to_process):
                logging.info("Recognized a filtered courtesy phrase, skipping post-processing and clipboard operations")
                print(f"Assistant: {text_to_process}", flush=True)
                return
                
            # Post-process (grammar correction)
            corrected = self.post.correct(text_to_process)
            
            # Sanitize output: replace German ß with ss, replace curly quotes with straight quotes
            sanitized = corrected.replace('ß', 'ss').replace('"','"').replace('"','"')
            print(f"Assistant: {sanitized}", flush=True)
            logging.info(f"Assistant: {sanitized}")
            
            # Double-check if post-processed text is a filtered phrase (very unlikely but just in case)
            if self.is_filtered_phrase(sanitized):
                logging.info("Post-processed text is a filtered courtesy phrase, skipping clipboard operations")
                return
                
            # Copy to clipboard
            try:
                subprocess.run(['pbcopy'], input=sanitized.encode('utf-8'), check=True)
                logging.info("Copied text to clipboard")
            except Exception as e:
                logging.error(f"Failed to copy to clipboard: {e}")
            # Paste via Cmd+V (suppress hotkey listener during synthetic press)
            try:
                from pynput.keyboard import Controller, Key
                kb = Controller()
                # Suppress hotkey callbacks while pasting
                self.hotkey_suppressed = True
                try:
                    with kb.pressed(Key.cmd):
                        kb.press('v')
                        kb.release('v')
                finally:
                    self.hotkey_suppressed = False
                logging.info("Pasted text via Cmd+V")
            except Exception as e:
                logging.error(f"Failed to paste via Cmd+V: {e}")
        except Exception as e:
            logging.error(f"Processing error: {e}")
    def _fallback_ptt_loop(self):
        """
        Fallback push-to-talk via ENTER key in console.
        Press ENTER to start/stop recording.
        """
        self.fallback_recording = False
        # Thread to capture audio when fallback_recording is True
        def record_thread():
            while True:
                if self.fallback_recording:
                    logging.info("Fallback PTT: start recording")
                    frames = []
                    for frame in self.audio.speech_audio_stream():
                        if not self.fallback_recording:
                            break
                        frames.append(frame)
                    logging.info("Fallback PTT: stop recording, scheduling processing")
                    threading.Thread(target=self._process_audio, args=(frames,), daemon=True).start()
                else:
                    time.sleep(0.1)
        threading.Thread(target=record_thread, daemon=True).start()
        # Monitor console ENTER presses
        while True:
            try:
                _ = input()
            except EOFError:
                break
            # toggle recording state
            self.fallback_recording = not self.fallback_recording

import threading
import time
import logging
import os
# import string # <-- No longer needed directly? Check usage
# import numpy as np # <-- No longer needed directly? Check usage

from .audio_interface import AudioCapture
from .vad import VAD
from .stt import SpeechToText
from .mac_overlay import get_overlay_instance
from pynput import keyboard # Keep pynput for Listener
from pynput.keyboard import Key # Keep Key for VALID_PTT_KEYS
# from types import MethodType # Keep if needed for dynamic methods elsewhere
import platform # Keep if needed

from .system_playback import SystemPlaybackManager
from .clipboard import ClipboardManager
from .llm_client import LLMClient
from .hotkey import HotkeyManager
from .audio_recorder import AudioRecorder
from .audio_processor import AudioProcessor
from .notification_manager import NotificationManager
from .api_client import NERServiceClient

# Import from config.py (for COMMANDS list)
import config as app_config # Use alias
from config import get_configured_signal_phrases

logger = logging.getLogger(__name__)

# --- Transcription Logging Setup (Keep as is) ---
transcription_logger = logging.getLogger('TranscriptionLogger')
transcription_logger.setLevel(logging.INFO)
transcription_logger.propagate = False 
try:
    log_file_path = 'transcriptions.log' 
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    formatter = logging.Formatter('%(asctime)s\t%(message)s', datefmt='%Y-%m-%dT%H:%M:%S') 
    file_handler.setFormatter(formatter)
    transcription_logger.addHandler(file_handler)
    logging.info(f"📝 Transcription logging configured to file: {log_file_path} (with timestamps)")
except Exception as e:
    logging.error(f"❌ Failed to configure transcription file logging to {log_file_path}: {e}")
    transcription_logger = None
# --- End Transcription Logging Setup ---

class Orchestrator:
    VALID_PTT_KEYS = {
        "option": {Key.alt, Key.alt_l, Key.alt_r},
        "cmd": {Key.cmd, Key.cmd_l, Key.cmd_r},
        "ctrl": {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
        "shift": {Key.shift, Key.shift_l, Key.shift_r},
    }
    DEFAULT_PTT_KEY_NAME = "option"
    DEFAULT_PROCESSING_MODE = "normal"

    # --- Modified __init__ signature ---
    def __init__(
        self,
        model_size: str,
        device: str,
        compute_type: str,
        beam_size: int,
        language: str,
        sample_rate: int,
        vad_aggressiveness: int,
        mic_name: str | None,
        llm_provider: str,
        ptt_hotkey: str,
        min_ptt_duration: float,
        ner_service_url: str
        # Add other params like tokens/temp here if passed from cli.py
    ):
        logger.debug("Orchestrator initializing...")
        # Store necessary parameters directly
        # self.config = config # <-- REMOVE config dict
        self.min_ptt_duration = min_ptt_duration
        logger.info(f"Minimum PTT duration set to: {self.min_ptt_duration}s")

        self.active_recording_thread = None
        self.cancel_requested = False
        self._last_paste_successful = False
        self.next_stt_language_hint = None
        self._playback_was_paused = False
        self.processing_mode = self.DEFAULT_PROCESSING_MODE
        self.language = language # Store initial language
        logger.info(f"🚦 Initial processing mode set to: {self.processing_mode}")
        logger.info(f"✍️ Initial language set to: {self.language}")

        # --- Initialize Managers (Pass specific params or let them read env vars) ---
        self.playback_manager = SystemPlaybackManager() # Doesn't seem to need config
        self.clipboard_manager = ClipboardManager(self) # Needs orchestrator instance

        # LLMClient: Let it read env vars for API keys for now, pass provider/defaults
        # Or: modify LLMClient to accept tokens/temp if passed from cli.py
        self.llm_client = LLMClient(
            default_provider=llm_provider
            # Pass other LLM params if needed:
            # anthropic_max_tokens=anthropic_max_tokens,
            # anthropic_temperature=anthropic_temperature,
            # ...etc
        )

        # NERServiceClient: Pass the URL
        logger.info(f"🧐 Configuring NERServiceClient to use service at: {ner_service_url}")
        self.ner_service_client = NERServiceClient(ner_service_url) if ner_service_url else None

        # HotkeyManager: Needs PTT key name
        ptt_key_set = self.VALID_PTT_KEYS.get(ptt_hotkey.lower(), self.VALID_PTT_KEYS[self.DEFAULT_PTT_KEY_NAME])
        logger.info(f"🔑 Using PTT key: {ptt_hotkey.lower()} (Resolved key set: {ptt_key_set})")
        # Defer initialization until other components using it are ready

        # --- Initialize Audio Components (Pass specific params) ---
        self.audio_capture = AudioCapture(
            sample_rate=sample_rate,
            channels=1, # Assuming mono, could be param if needed
            mic_name=mic_name
        )
        configured_mic = mic_name or 'Default'
        logger.info(f"🎤 Audio interface configured (Mic Config: '{configured_mic}', Rate: {self.audio_capture.sample_rate}, Channels: {self.audio_capture.channels})")

        self.audio_recorder = AudioRecorder(
            audio_capture=self.audio_capture,
            min_pause_duration=self.min_ptt_duration,
            playback_manager=self.playback_manager
        )
        logger.debug("AudioRecorder initialized within Orchestrator.")

        self.vad = VAD(vad_aggressiveness)
        logger.debug(f"VAD configured (Aggressiveness: {vad_aggressiveness})." )

        self.stt = SpeechToText(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            beam_size=beam_size
            # language is handled dynamically by AudioProcessor/Orchestrator state
        )
        logger.info(f"🗣️ STT model loaded (Size: {model_size}, Device: {device}, Compute: {compute_type}, Beam: {beam_size})" )

        # --- Overlay initialization ---
        _overlay_instance = None
        try:
            _overlay_instance = get_overlay_instance()
            logger.info("✅ Overlay instance created.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize overlay: {e}")

        # --- Initialize Notification Manager (Pass necessary params) ---
        self.notification_manager = NotificationManager(
            overlay=_overlay_instance,
            audio_capture=self.audio_capture # Needs sample rate
            # Pass other specific config if NotificationManager needs it
        )

        # --- Initialize Audio Processor (Pass necessary components/params) ---
        self.audio_processor = AudioProcessor(
            stt=self.stt,
            initial_language=self.language,
            notification_manager=self.notification_manager,
            clipboard_manager=self.clipboard_manager,
            llm_client=self.llm_client,
            ner_service_client=self.ner_service_client,
            transcription_logger=transcription_logger
        )
        logger.debug("AudioProcessor initialized within Orchestrator.")

        # --- Initialize HotkeyManager (Now components are ready) ---
        self.hotkey_manager = HotkeyManager(
            ptt_keys=ptt_key_set, # Use resolved key set
            on_ptt_start=self._handle_ptt_start,
            on_ptt_stop=self._handle_ptt_stop,
            on_cancel=self._handle_ptt_cancel,
            on_ctrl_press_during_ptt=self._handle_ctrl_press_during_ptt
        )

        logger.debug("Orchestrator initialization complete.")

    # --- Methods (start, stop, _handle_*, suppress_hotkeys, _get_clipboard_content) ---
    # These methods generally shouldn't need changes, as they use instance variables
    # that are now set directly in __init__ instead of from a config dict.
    # Double-check if any method specifically accessed self.config, but it seems unlikely.

    def start(self):
        # (Keep as is)
        logger.info("🤖 Assistant PTT mode starting...")
        try:
            self.hotkey_manager.start()
            logger.info("👂 Hotkey listener started via manager.")
            self.notification_manager.show_message("Assistant Ready!", duration=2.0, group_id="startup_toast")
            logger.info("🍞 Startup notification displayed.")
        except Exception as e:
             logger.exception(f"❌ Failed to start hotkey listener via manager: {e}")
             raise

    def stop(self):
         # (Keep as is)
         logger.info("Orchestrator stopping...")
         if self.hotkey_manager:
             self.hotkey_manager.stop()

    def _handle_ptt_start(self, ctrl_pressed: bool):
        # (Keep as is - uses self.active_recording_thread, self.playback_manager, etc.)
        logger.debug(f"Orchestrator: _handle_ptt_start called (Ctrl: {ctrl_pressed}).")
        self._playback_was_paused = False
        self.cancel_requested = False
        if self.active_recording_thread and self.active_recording_thread.is_alive():
             logger.warning("PTT Start requested, but recording thread already active.")
             return
        if ctrl_pressed:
            logger.info("Ctrl key detected with PTT start, pausing playback...")
            self.playback_manager.pause()
            self._playback_was_paused = True
        self.active_recording_thread = self.audio_recorder.start_recording()
        try:
            signal_phrases = get_configured_signal_phrases() # Uses COMMANDS from config.py
            if signal_phrases:
                display_string = " ⋅ ".join(signal_phrases)
                logger.info(f"🚦 Displaying start notification with signals: {display_string}")
                self.notification_manager.show_message("Recording... 🇨🇭 🇩🇪 🇬🇧\n" + display_string)
        except Exception as e:
             logger.error(f"❌ Failed to get or display signal phrases from config.py: {e}")


    def _handle_ptt_stop(self, ctrl_pressed: bool):
        # (Keep as is - uses self.audio_recorder, self.min_ptt_duration, self.audio_processor etc.)
        logger.debug(f"Orchestrator: _handle_ptt_stop called (Ctrl: {ctrl_pressed}).")
        frames, duration = self.audio_recorder.stop_recording()
        self.active_recording_thread = None
        if self._playback_was_paused:
            logger.info("Playback was paused for this recording, resuming...")
            self.playback_manager.resume()
        else:
             logger.debug("Playback was not paused for this recording, skipping resume.")
        self._playback_was_paused = False
        if self.cancel_requested:
            logger.info("🚫 Processing cancelled (Esc key pressed).")
            self.cancel_requested = False
            self.notification_manager.show_message("Cancelled", duration=1.0)
            return
        if not frames:
            logger.warning("⚠️ No audio frames captured after stop. Skipping.")
        if duration < self.min_ptt_duration:
            logger.info(f"❌ Duration too short ({duration:.2f}s < {self.min_ptt_duration}s). Skipping.")
            self.notification_manager.hide_overlay()
            return
        logger.info(f"✅ Duration OK ({duration:.2f}s). Processing audio synchronously (Mode: {self.processing_mode})...")
        self.notification_manager.show_message(f"Processing... [{duration:.2f}s]")
        try:
            processing_result = self.audio_processor.process_audio(
                frames,
                self.processing_mode,
                self.next_stt_language_hint,
                self.DEFAULT_PROCESSING_MODE, # Pass default mode explicitly
                frames # Pass frames for potential re-running STT
            )
            self.processing_mode = processing_result.get('new_processing_mode', self.processing_mode)
            self.next_stt_language_hint = processing_result.get('new_stt_hint', None)
            text_to_paste = processing_result.get('text_to_paste')
            paste_successful = processing_result.get('paste_successful', False)
            if paste_successful and text_to_paste is not None:
                logger.info(f"Attempting paste (Mode: {self.processing_mode}): '{text_to_paste[:100]}...'")
                self.clipboard_manager.copy_and_paste(text_to_paste)
                self.notification_manager.show_message(f"Pasted: {text_to_paste[:50]}", duration=2.0)
                self._last_paste_successful = True
            else:
                mode_changed = processing_result.get('new_processing_mode') != self.processing_mode and processing_result.get('new_processing_mode') is not None
                if not text_to_paste and not mode_changed:
                     logger.info(f"No text to paste and no mode change (Mode: {self.processing_mode}).")
                elif mode_changed:
                     logger.info(f"Mode changed to '{self.processing_mode}'. No text pasted this time.")
                if not mode_changed:
                     self.notification_manager.hide_overlay()
                self._last_paste_successful = False
            logger.info(f"Orchestrator state after processing: Mode='{self.processing_mode}', Next Hint='{self.next_stt_language_hint}'")
            # --- Always auto-reset to English after any German run (de-DE or de-CH) ---
            if self.next_stt_language_hint in ('de-DE', 'de-CH'):
                logger.info(f"🔄 Auto-resetting language hint to 'en' after German/Swiss German run (was: {self.next_stt_language_hint}).")
                self.next_stt_language_hint = 'en'
            # --- Always auto-reset processing_mode to 'normal' after Swiss German run ---
            if self.processing_mode == 'de-CH':
                logger.info("🔄 Auto-resetting processing mode to 'normal' after Swiss German run.")
                self.processing_mode = 'normal'
        except Exception as e:
            logger.exception("💥 Error during synchronous audio processing:")
            self.notification_manager.show_message("Error processing audio.", duration=3.0)
            self._last_paste_successful = False


    def _handle_ptt_cancel(self):
        # (Keep as is)
        logger.info(f"Orchestrator: _handle_ptt_cancel called.")
        self.cancel_requested = True
        if self.active_recording_thread and self.active_recording_thread.is_alive():
            logger.debug("Signaling AudioRecorder to stop due to cancel request.")
            self.audio_recorder.stop_recording()
            if self._playback_was_paused:
                logger.info("Playback was paused, resuming due to cancellation...")
                self.playback_manager.resume()
            self._playback_was_paused = False
        else:
             logger.debug("Cancel requested but no active recording thread found.")
             self._playback_was_paused = False
        self.notification_manager.show_message("Recording stopped", duration=1.0)

    def _handle_ctrl_press_during_ptt(self):
        # (Keep as is)
        logger.info("Orchestrator: Ctrl pressed during active recording.")
        if not self._playback_was_paused:
            logger.info("Pausing playback due to mid-recording Ctrl press...")
            self.playback_manager.pause()
            self._playback_was_paused = True
        else:
            logger.debug("Playback already paused, ignoring mid-recording Ctrl press.")

    def suppress_hotkeys(self, suppress: bool):
         # (Keep as is)
         if self.hotkey_manager:
             self.hotkey_manager.suppress(suppress)
         else:
             logger.warning("Attempted to set hotkey suppression, but manager not ready.")

    def _get_clipboard_content(self):
         # (Keep as is)
         return self.clipboard_manager.get_content()

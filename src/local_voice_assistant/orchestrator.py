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
from pynput.keyboard import Key, Controller as KeyboardController
# from types import MethodType # Keep if needed for dynamic methods elsewhere
import platform # Keep if needed

from .system_playback import SystemPlaybackManager
from .clipboard import ClipboardManager
from .llm_client import LLMClient
from .hotkey import HotkeyManager
from .audio_recorder import AudioRecorder
from .audio_processing import AudioProcessor
from .notification_manager import NotificationManager
from .api_client import NERServiceClient

# Import from config.py (for COMMANDS list)
import config as app_config # Use alias
from config import get_configured_signal_phrases
import multiprocessing
from .overlay_qt import OverlayWindow, build_overlay_text
import subprocess
import sys

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
    """Orchestrates the voice assistant components and workflow."""
    
    VALID_PTT_KEYS = {
        "option": {Key.alt, Key.alt_l, Key.alt_r},
        "cmd": {Key.cmd, Key.cmd_l, Key.cmd_r},
        "ctrl": {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
        "shift": {Key.shift, Key.shift_l, Key.shift_r},
    }
    DEFAULT_PTT_KEY_NAME = "option"
    DEFAULT_PROCESSING_MODE = "normal"

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
    ):
        """Initialize the voice assistant components and their interactions."""
        logger.debug("Orchestrator initializing...")
        
        # Core state
        self.min_ptt_duration = min_ptt_duration
        self.active_recording_thread = None
        self.cancel_requested = False
        self._playback_was_paused = False
        self.processing_mode = self.DEFAULT_PROCESSING_MODE
        self.language = language
        self.next_stt_language_hint = None
        
        # Initialize components
        self._init_components(
            model_size, device, compute_type, beam_size,
            language, sample_rate, vad_aggressiveness,
            mic_name, llm_provider, ptt_hotkey, ner_service_url
        )
        
        logger.debug("Orchestrator initialization complete.")

    def _init_components(self, model_size, device, compute_type, beam_size,
                        language, sample_rate, vad_aggressiveness,
                        mic_name, llm_provider, ptt_hotkey, ner_service_url):
        """Initialize all components with their dependencies."""
        # Audio components
        self.audio_capture = AudioCapture(
            sample_rate=sample_rate,
            channels=1,
            mic_name=mic_name
        )
        
        self.playback_manager = SystemPlaybackManager()
        self.clipboard_manager = ClipboardManager(self)
        
        self.audio_recorder = AudioRecorder(
            audio_capture=self.audio_capture,
            min_pause_duration=self.min_ptt_duration,
            playback_manager=self.playback_manager
        )
        
        self.vad = VAD(vad_aggressiveness)
        self.stt = SpeechToText(
            model_size=model_size,
            device=device,
            compute_type=compute_type,
            beam_size=beam_size
        )
        
        # Service clients
        self.llm_client = LLMClient(default_provider=llm_provider)
        
        # Start NER service in background if URL is provided
        if ner_service_url:
            from .ner_service import start_ner_service
            self.ner_service_thread = start_ner_service()
            self.ner_service_client = NERServiceClient(ner_service_url)
        else:
            self.ner_service_client = None
        
        # UI components
        overlay_instance = self._init_overlay()
        self.notification_manager = NotificationManager(
            overlay=overlay_instance,
            audio_capture=self.audio_capture
        )
        
        # Processing components
        self.audio_processor = AudioProcessor(
            stt=self.stt,
            initial_language=self.language,
            notification_manager=self.notification_manager,
            clipboard_manager=self.clipboard_manager,
            llm_client=self.llm_client,
            ner_service_client=self.ner_service_client,
            transcription_logger=logger
        )
        
        # Hotkey management
        ptt_key_set = self.VALID_PTT_KEYS.get(ptt_hotkey.lower(), self.VALID_PTT_KEYS[self.DEFAULT_PTT_KEY_NAME])
        self.hotkey_manager = HotkeyManager(
            ptt_keys=ptt_key_set,
            on_ptt_start=self._handle_ptt_start,
            on_ptt_stop=self._handle_ptt_stop,
            on_cancel=self._handle_ptt_cancel,
            on_ctrl_press_during_ptt=self._handle_ctrl_press_during_ptt,
            on_help_overlay=self._handle_help_overlay,
            on_stop_playback=self._handle_stop_playback,
            on_dot_enter=self._handle_dot_enter
        )

    def _init_overlay(self):
        """Initialize the overlay UI component."""
        try:
            overlay = get_overlay_instance()
            logger.info("✅ Overlay instance created.")
            return overlay
        except Exception as e:
            logger.error(f"❌ Failed to initialize overlay: {e}")
            return None

    def start(self):
        """Start the voice assistant."""
        logger.info("🤖 Assistant PTT mode starting...")
        try:
            self.hotkey_manager.start()
            self.notification_manager.show_message("Assistant Ready!", duration=2.0, group_id="startup_toast")
        except Exception as e:
            logger.exception(f"❌ Failed to start assistant: {e}")
            raise

    def stop(self):
        """Stop the voice assistant."""
        logger.info("Orchestrator stopping...")
        if self.hotkey_manager:
            self.hotkey_manager.stop()

    def _handle_ptt_start(self, ctrl_pressed: bool):
        """Handle PTT start event."""
        if self.active_recording_thread and self.active_recording_thread.is_alive():
            return
            
        self._playback_was_paused = False
        self.cancel_requested = False
        
        if ctrl_pressed:
            self.playback_manager.pause()
            self._playback_was_paused = True
            
        self.active_recording_thread = self.audio_recorder.start_recording()
        self._show_signal_phrases()

    def _handle_ptt_stop(self, ctrl_pressed: bool):
        """Handle PTT stop event."""
        frames, duration = self.audio_recorder.stop_recording()
        self.active_recording_thread = None
        
        if self._playback_was_paused:
            self.playback_manager.resume()
        self._playback_was_paused = False
        
        if self.cancel_requested:
            self.cancel_requested = False
            self.notification_manager.show_message("Cancelled", duration=1.0)
            return
            
        if not frames or duration < self.min_ptt_duration:
            return
            
        self._process_audio(frames, duration)

    def _handle_ptt_cancel(self):
        """Handle PTT cancel event."""
        self.cancel_requested = True
        if self.active_recording_thread and self.active_recording_thread.is_alive():
            self.audio_recorder.stop_recording()
            if self._playback_was_paused:
                self.playback_manager.resume()
            self._playback_was_paused = False
        self.notification_manager.show_message("Recording stopped", duration=1.0)

    def _handle_ctrl_press_during_ptt(self):
        """Handle Ctrl press during PTT."""
        if not self._playback_was_paused:
            self.playback_manager.pause()
            self._playback_was_paused = True

    def _handle_help_overlay(self, ctrl_pressed: bool):
        """Handle help overlay request."""
        self._show_overlay()

    def _handle_stop_playback(self, ctrl_pressed: bool):
        """Handle playback stop request."""
        self.notification_manager.show_message("Stopping playback...", duration=2.0)
        self.playback_manager.pause()

    def _handle_dot_enter(self):
        """Handle enter after paste request."""
        logger.debug("Orchestrator: Option+ArrowLeft detected - will send Enter after next paste")
        self.notification_manager.show_message("Will send Enter after paste", duration=1.0)

    def _show_signal_phrases(self):
        """Show configured signal phrases."""
        try:
            signal_phrases = get_configured_signal_phrases()
            if signal_phrases:
                display_string = " ⋅ ".join(signal_phrases)
                logger.info(f"🚦 Displaying start notification with signals: {display_string}")
        except Exception as e:
            logger.error(f"❌ Failed to get signal phrases: {e}")

    def _process_audio(self, frames, duration):
        """Process recorded audio."""
        self.notification_manager.show_message(f"Processing... [{duration:.2f}s]")
        
        try:
            result = self.audio_processor.process_audio(
                frames,
                self.processing_mode,
                self.next_stt_language_hint,
                self.DEFAULT_PROCESSING_MODE,
                frames
            )
            
            self._update_state_from_result(result)
            self._handle_paste_result(result)
            self._auto_reset_modes()
            
        except Exception as e:
            logger.exception("💥 Error during audio processing:")
            self.notification_manager.show_message("Error processing audio.", duration=3.0)

    def _update_state_from_result(self, result):
        """Update state from processing result."""
        self.processing_mode = result.get('new_processing_mode', self.processing_mode)
        self.next_stt_language_hint = result.get('new_stt_hint', None)

    def _handle_paste_result(self, result):
        """Handle paste result from processing."""
        text_to_paste = result.get('text_to_paste')
        paste_successful = result.get('paste_successful', False)
        
        if paste_successful and text_to_paste:
            self.clipboard_manager.copy_and_paste(text_to_paste)
            
            if self.hotkey_manager.should_send_enter_after_paste():
                kb = KeyboardController()
                kb.press(Key.enter)
                kb.release(Key.enter)
                self.hotkey_manager.clear_enter_after_paste()
                
            self.notification_manager.show_message(f"Pasted: {text_to_paste[:50]}", duration=2.0)
        else:
            self._handle_mode_change(result)

    def _handle_mode_change(self, result):
        """Handle mode change from processing result."""
        mode_changed = result.get('new_processing_mode') != self.processing_mode and result.get('new_processing_mode') is not None
        if mode_changed:
            logger.info(f"Mode changed to '{self.processing_mode}'. No text pasted this time.")
        else:
            self.notification_manager.hide_overlay()

    def _auto_reset_modes(self):
        """Auto-reset modes after processing."""
        if self.next_stt_language_hint in ('de-DE', 'de-CH'):
            self.next_stt_language_hint = 'en'
        if self.processing_mode == 'de-CH':
            self.processing_mode = 'normal'

    def _show_overlay(self):
        """Show the help overlay."""
        import subprocess
        import sys
        subprocess.Popen([
            sys.executable,
            "src/local_voice_assistant/overlay_qt.py"
        ])

    def suppress_hotkeys(self, suppress: bool):
        """Enable or disable hotkey suppression."""
        if self.hotkey_manager:
            self.hotkey_manager.suppress(suppress)

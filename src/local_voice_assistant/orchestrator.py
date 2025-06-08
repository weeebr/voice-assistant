import threading
import time
import logging
import os
# import string # <-- No longer needed directly? Check usage
# import numpy as np # <-- No longer needed directly? Check usage

from .audio_interface import AudioCapture
from .vad import VAD
from .stt import SpeechToText
# from .overlay_qt import OverlayManager, build_overlay_text  # Not needed with subprocess approach
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
from .signal_detector import SignalDetector
from .action_executor import ActionExecutor
from .toast import ToastManager

# Import from config.py (for COMMANDS list)
import config as app_config # Use alias
from config import get_configured_signal_phrases
import multiprocessing
import subprocess
import sys
from typing import Optional, Dict, Any

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
    """Orchestrates the voice assistant components."""

    def __init__(self, config: Dict[str, Any]):
        """Initialize the orchestrator with configuration."""
        logger.debug("Orchestrator initializing...")
        
        # Initialize components
        self.toast_manager = ToastManager()
        self.notification_manager = NotificationManager(None, None)
        self.clipboard_manager = ClipboardManager(self)
        self.llm_client = LLMClient(default_provider=config.get('llm_provider', 'google'))
        ner_url = config.get('ner_service_url')
        if ner_url:
            self.ner_service_client = NERServiceClient(ner_url)
        else:
            self.ner_service_client = None
        
        # Initialize SpeechToText
        self.stt = SpeechToText(
            model_size=config.get('model_size', 'small'),
            device=config.get('device', 'cpu'),
            compute_type=config.get('compute_type', 'int8'),
            beam_size=config.get('beam_size', 1)
        )
        # Initialize audio processor with correct arguments
        self.audio_processor = AudioProcessor(
            self.stt,
            self.notification_manager,
            self.clipboard_manager,
            self.llm_client,
            self.ner_service_client
        )
        
        # Initialize action executor
        self.action_executor = ActionExecutor(
            self.llm_client,
            self.ner_service_client,
            self.clipboard_manager,
            self.notification_manager
        )
        
        # Set up PTT keys to include both left and right Option keys if 'option' is selected
        ptt_hotkey = config.get('ptt_hotkey', 'option')
        if ptt_hotkey == 'option':
            ptt_keys = [keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r]
        else:
            # You can expand this for other hotkey types if needed
            ptt_keys = [keyboard.Key[ptt_hotkey]] if hasattr(keyboard.Key, ptt_hotkey) else []

        self.hotkey_manager = HotkeyManager(
            ptt_keys=ptt_keys,
            on_ptt_start=self._on_ptt_start,
            on_ptt_stop=self._on_ptt_stop,
            on_cancel=self._on_cancel,
            on_ctrl_press_during_ptt=self._on_ctrl_press_during_ptt,
            on_help_overlay=self._on_help_overlay,
            on_stop_playback=self._on_stop_playback,
            on_dot_enter=self._on_arrow_left_enter
        )
        
        # State
        self._is_recording = False
        self._current_mode = "normal"  # Default mode is now 'normal'
        self._current_stt_hint = None  # Default STT hint
        self._recording_thread = None
        self._stop_recording = threading.Event()
        
        # Initialize AudioRecorder
        self.audio_capture = AudioCapture(
            sample_rate=config.get('sample_rate', 16000),
            channels=1,
            mic_name=config.get('mic_name')
        )
        self.playback_manager = SystemPlaybackManager()
        self.audio_recorder = AudioRecorder(
            audio_capture=self.audio_capture,
            min_pause_duration=config.get('min_ptt_duration', 1.2),
            playback_manager=self.playback_manager
        )
        
        logger.info("✅ Orchestrator initialized")

    def _on_ptt_start(self, ctrl_pressed: bool):
        """Handle PTT start."""
        if self._is_recording:
            logger.warning("PTT start requested but already recording")
            return
            
        logger.info("🎙️ Starting recording...")
        self._is_recording = True
        self._stop_recording.clear()
        
        # Start recording in a separate thread
        self._recording_thread = threading.Thread(
            target=self._record_audio,
            args=(ctrl_pressed,),
            daemon=True
        )
        self._recording_thread.start()

    def _on_ptt_stop(self, ctrl_pressed: bool):
        """Handle PTT stop."""
        if not self._is_recording:
            logger.warning("PTT stop requested but not recording")
            return
            
        logger.info("🛑 Stopping recording...")
        self._stop_recording.set()
        if self._recording_thread:
            self._recording_thread.join(timeout=1.0)
        self._is_recording = False
        self._recording_thread = None

    def _on_cancel(self):
        """Handle recording cancellation."""
        logger.info("❌ Cancelling recording...")
        self._stop_recording.set()
        if self._recording_thread:
            self._recording_thread.join(timeout=1.0)
        self._is_recording = False
        self._recording_thread = None
        self.notification_manager.show_message("Recording cancelled")

    def _on_ctrl_press_during_ptt(self):
        """Handle Ctrl press during PTT."""
        if self._is_recording:
            logger.info("🎯 Ctrl pressed during PTT")
            self.notification_manager.show_message("Ctrl pressed - will paste immediately")

    def _on_help_overlay(self, ctrl_pressed: bool, hide: bool = False):
        """Handle help overlay toggle."""
        if hide:
            logger.info("👋 Hiding help overlay")
            # Overlay will auto-hide, nothing to do
            return
        logger.info("📋 Showing help overlay")
        self._show_overlay()

    def _on_stop_playback(self, ctrl_pressed: bool):
        """Handle stop playback request."""
        logger.info("⏹️ Stopping playback...")
        # TODO: Implement playback stop logic

    def _on_arrow_left_enter(self):
        """Handle arrow left request to send enter after paste."""
        logger.info("⏎ Enter will be sent after paste")
        # Don't clear the flag here - it will be cleared after the paste happens

    def _record_audio(self, ctrl_pressed: bool):
        """Record and process audio."""
        try:
            # Start recording
            self.audio_recorder.start_recording()
            # Wait for stop event
            self._stop_recording.wait()
            # Stop recording and get frames
            frames, duration = self.audio_recorder.stop_recording()
            self.notification_manager.show_message(f"Processing... [{duration:.2f}s]")
            # Process the recorded audio
            result = self.audio_processor.process_audio(
                frames,
                self._current_mode,
                self._current_stt_hint,
                self._current_mode,
                frames
            )
            if result:
                # Update mode and STT hint if changed
                if 'new_mode' in result:
                    self._current_mode = result['new_mode']
                if 'new_stt_hint' in result:
                    self._current_stt_hint = result['new_stt_hint']
                # Handle paste if successful
                if result.get('paste_successful'):
                    text_to_paste = result['text_to_paste']
                    if self.hotkey_manager.should_send_enter_after_paste():
                        self.clipboard_manager.copy_and_paste(text_to_paste, send_enter=True)
                        self.hotkey_manager.clear_enter_after_paste()
                    else:
                        self.clipboard_manager.copy_and_paste(text_to_paste)
                    self.notification_manager.show_message(f"Pasted: {text_to_paste[:50]}", duration=2.0, group_id="paste_toast")
        except Exception as e:
            logger.exception(f"Error during audio processing: {e}")
            self.notification_manager.show_message("Error processing audio")

    def start(self):
        """Start the orchestrator."""
        logger.info("🚀 Starting orchestrator...")
        self.hotkey_manager.start()
        self.notification_manager.show_message("Voice Assistant Ready!", as_toast=True)
        logger.info("✅ Orchestrator started")

    def stop(self):
        """Stop the orchestrator."""
        logger.info("🛑 Stopping orchestrator...")
        self.hotkey_manager.stop()
        if self._is_recording:
            self._on_cancel()
        logger.info("✅ Orchestrator stopped")

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
                self._current_mode,
                self._current_stt_hint,
                self._current_mode,
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
        if 'new_mode' in result:
            self._current_mode = result['new_mode']
        if 'new_stt_hint' in result:
            self._current_stt_hint = result['new_stt_hint']

    def _handle_paste_result(self, result):
        """Handle paste result from processing."""
        text_to_paste = result.get('text_to_paste')
        paste_successful = result.get('paste_successful', False)
        
        if paste_successful and text_to_paste:
            if self.hotkey_manager.should_send_enter_after_paste():
                self.clipboard_manager.copy_and_paste(text_to_paste, send_enter=True)
                self.hotkey_manager.clear_enter_after_paste()
            else:
                self.clipboard_manager.copy_and_paste(text_to_paste)
            
            self.notification_manager.show_message(f"Pasted: {text_to_paste[:50]}", duration=2.0, group_id="paste_toast")
        else:
            self._handle_mode_change(result)

    def _handle_mode_change(self, result):
        """Handle mode change from processing result."""
        mode_changed = 'new_mode' in result and result['new_mode'] != self._current_mode and result['new_mode'] is not None
        if mode_changed:
            logger.info(f"Mode changed to '{self._current_mode}'. No text pasted this time.")
            self._current_mode = result['new_mode']
        # Overlay auto-hides, no need to manually hide

    def _auto_reset_modes(self):
        """Auto-reset modes after processing."""
        if self._current_stt_hint in ('de-DE', 'de-CH'):
            self._current_stt_hint = 'en'
        if self._current_mode == 'de-CH':
            self._current_mode = 'normal'

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

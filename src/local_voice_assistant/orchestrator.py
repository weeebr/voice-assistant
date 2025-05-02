import threading
import time
import logging
import os
import string # <-- Add import
import numpy as np # <-- Add numpy import
# --- REMOVE sounddevice import, now handled by AudioRecorder ---
# import sounddevice as sd 

from .audio_interface import AudioCapture
from .vad import VAD
from .stt import SpeechToText
from .mac_overlay import get_overlay_instance
from pynput import keyboard # Keep pynput for Listener
from pynput.keyboard import Key # Keep Key for VALID_PTT_KEYS
from types import MethodType # For binding handlers if still used elsewhere, maybe removable?
# Keep MethodType for now in case it's needed by future config structures
import platform # Needed for macOS check potentially

# Import the configuration from the separate file
from .signal_config import SIGNAL_WORD_CONFIG
from .system_playback import SystemPlaybackManager # Added Import
from .clipboard import ClipboardManager # Added Import
from .llm_client import LLMClient # Added Import
from .hotkey import HotkeyManager # Added Import
from .audio_recorder import AudioRecorder # <-- Add new import
from .audio_processor import AudioProcessor # <-- Add new import
from .notification_manager import NotificationManager # <-- Add import

logger = logging.getLogger(__name__)

# --- Transcription Logging Setup ---
transcription_logger = logging.getLogger('TranscriptionLogger')
transcription_logger.setLevel(logging.INFO) # Log informational messages
transcription_logger.propagate = False 
try:
    # Use 'transcriptions.log' in the current working directory (where start.sh is run from)
    log_file_path = 'transcriptions.log' 
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    # Create a simple formatter - just the message (the transcription)
    formatter = logging.Formatter('%(message)s') 
    file_handler.setFormatter(formatter)
    # Add the handler to the transcription logger
    transcription_logger.addHandler(file_handler)
    logging.info(f"📝 Transcription logging configured to file: {log_file_path}")
except Exception as e:
    logging.error(f"❌ Failed to configure transcription file logging to {log_file_path}: {e}")
    # Optionally, disable the logger or handle the error appropriately
    transcription_logger = None # Disable if setup failed

# --- End Transcription Logging Setup ---

# --- Signal Word Mapping (REMOVED - Now in signal_config.py) ---

class Orchestrator:
    # Define valid PTT keys and their pynput mappings
    VALID_PTT_KEYS = {
        "option": {Key.alt, Key.alt_l, Key.alt_r},
        "cmd": {Key.cmd, Key.cmd_l, Key.cmd_r},
        "ctrl": {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
        "shift": {Key.shift, Key.shift_l, Key.shift_r},
        # Add other keys if needed (e.g., F-keys?)
    }
    DEFAULT_PTT_KEY_NAME = "option" # Fallback if config is invalid

    def __init__(self, config):
        logger.debug("Orchestrator initializing...")
        self.config = config
        self.min_ptt_duration = config.get('min_ptt_duration', 1.2)
        logger.info(f"Minimum PTT duration set to: {self.min_ptt_duration}s")
        # -----------------------------------------
        self.active_recording_thread = None
        self.cancel_requested = False
        self._last_paste_successful = False
        self.translation_mode = None
        self.next_stt_language_hint = None
        
        # --- Initialize Managers --- 
        self.playback_manager = SystemPlaybackManager()
        self.clipboard_manager = ClipboardManager(self) # Pass self for suppression flag access
        self.llm_client = LLMClient(config) # Initialize LLMClient
        # HotkeyManager needs to be initialized *after* we know the key
        # We will initialize it after audio components
        # self.hotkey_manager = HotkeyManager(...) # Defer initialization
        # -------------------------
        
        # --- Initialize Audio Components ---
        self.audio_capture = AudioCapture(
            sample_rate=config.get('sample_rate', 16000),
            channels=config.get('channels', 1),
            mic_name=config.get('mic_name')
        )
        configured_mic = self.config.get('mic_name') or 'Default'
        logger.info(f"🎤 Audio interface configured (Mic Config: '{configured_mic}', Rate: {self.audio_capture.sample_rate}, Channels: {self.audio_capture.channels})")
        
        self.audio_recorder = AudioRecorder(
            audio_capture=self.audio_capture, 
            min_pause_duration=self.min_ptt_duration, 
            playback_manager=self.playback_manager 
        )
        logger.debug("AudioRecorder initialized within Orchestrator.")

        self.vad = VAD(config.get('vad_aggressiveness', 2))
        logger.debug(f"VAD configured (Aggressiveness: {config.get('vad_aggressiveness', 2)})." )
        self.stt = SpeechToText(
            model_size=config.get('model_size', 'small'),
            device=config.get('device', 'cpu'),
            compute_type=config.get('compute_type', 'int8'),
            beam_size=config.get('beam_size', 1)
        )
        logger.info(f"🗣️ STT model loaded (Size: {config.get('model_size', 'small')}, Device: {config.get('device', 'cpu')}, Compute: {config.get('compute_type', 'int8')}, Beam: {config.get('beam_size', 1)})" )
        
        # Language setup 
        self.language = config.get('language', 'en-US')
        logger.info(f"✍️ Initial language set to: {self.language}")
        
        # --- Overlay initialization (temporary, will be passed to NotifManager) ---
        _overlay_instance = None
        try:
            _overlay_instance = get_overlay_instance()
            logger.info("✅ Overlay instance created.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize overlay: {e}")
        # --- Remove self.overlay attribute ---
        # self.overlay = None 
            
        # --- Initialize Notification Manager --- 
        self.notification_manager = NotificationManager(
            config=self.config,
            overlay=_overlay_instance, # Pass the created overlay instance
            audio_capture=self.audio_capture # Pass audio capture for sample rate
        )
        # -------------------------------------
        
        # --- Initialize Audio Processor --- 
        self.audio_processor = AudioProcessor(
            stt=self.stt,
            config=self.config,
            # Remove overlay and beep func, pass notification manager
            # overlay=self.overlay, 
            # orchestrator_beep_func=self._play_beep 
            notification_manager=self.notification_manager,
            clipboard_manager=self.clipboard_manager,
            llm_client=self.llm_client,
            transcription_logger=transcription_logger 
        )
        logger.debug("AudioProcessor initialized within Orchestrator.")
        
        # --- Initialize HotkeyManager (Now that other components are ready) --- 
        self.hotkey_manager = HotkeyManager(
            ptt_keys=self.VALID_PTT_KEYS[config.get('ptt_hotkey', self.DEFAULT_PTT_KEY_NAME).lower()],
            on_ptt_start=self._handle_ptt_start,
            on_ptt_stop=self._handle_ptt_stop,
            on_cancel=self._handle_ptt_cancel
        )
        # ---------------------------------------------------------------------
            
        logger.debug("Orchestrator initialization complete.")

    def start(self):
        """Starts the HotkeyManager listener and shows ready notification."""
        logger.info("🤖 Assistant PTT mode starting...")
        try:
            self.hotkey_manager.start() # Start the manager's listener
            logger.info("👂 Hotkey listener started via manager.")
        except Exception as e:
             logger.exception(f"❌ Failed to start hotkey listener via manager: {e}")
             raise # Re-raise critical error

        # --- Use Notification Manager --- 
        logger.debug("Using NotificationManager to show 'Start recording...'")
        # ------------------------------

    def stop(self):
         """Stops the HotkeyManager listener."""
         logger.info("Orchestrator stopping...")
         if self.hotkey_manager:
             self.hotkey_manager.stop()

    # --- Hotkey Callbacks (Called by HotkeyManager) --- 
    def _handle_ptt_start(self):
        """Callback executed by HotkeyManager when PTT key is pressed."""
        logger.debug("Orchestrator: _handle_ptt_start called.")
        # Check if a recording thread from AudioRecorder is already active
        if self.active_recording_thread and self.active_recording_thread.is_alive():
             logger.warning("PTT Start requested, but recording thread already active.")
             return
             
        self.cancel_requested = False
        self.active_recording_thread = self.audio_recorder.start_recording()
        
        # --- Show Signal Phrases Notification --- 
        try:
            signal_phrases = [
                cfg.get('signal_phrase')
                for cfg in SIGNAL_WORD_CONFIG.values()
                if cfg.get('signal_phrase') and cfg.get('action') != 'set_next_stt' and cfg.get('action') != 'set_mode'
            ]

            if signal_phrases:
                # Simple bulleted list
                message =" ⋅ ".join(sorted(signal_phrases))
                self.notification_manager.show_message(message)
            else:
                logger.debug("No signal phrases found in config to display.")
            self.notification_manager.show_message("Start recording... 🇨🇭 🇩🇪 🇺🇸 \n" + message)
        except Exception as e:
            logger.error(f"Failed to generate signal phrase list for notification: {e}")
        # ------------------------------------
        
        # Log is now handled inside audio_recorder.start_recording()

    def _handle_ptt_stop(self):
        """Callback executed by HotkeyManager when PTT key is released."""
        logger.debug("Orchestrator: _handle_ptt_stop called.")
        frames, duration = self.audio_recorder.stop_recording()
        self.active_recording_thread = None # Clear the tracked thread
        self.playback_manager.resume() # Resume playback after recording stops

        if self.cancel_requested:
            logger.info("🚫 Processing canceled via Esc key.")
            self.cancel_requested = False 
            # Maybe show a "Cancelled" message?
            self.notification_manager.show_message("Cancelled") 
        else:
            logger.info(f"⏱️ PTT duration: {duration:.2f} seconds.")
            # Process audio if duration meets minimum
            if frames and duration >= self.min_ptt_duration:
                 logger.info(f"✅ Duration OK ({duration:.2f}s >= {self.min_ptt_duration}s). Processing...")
                 # --- Use Notification Manager --- 
                 self.notification_manager.show_message(f"Processing... [{duration:.2f}s]")
                 # ------------------------------
                 threading.Thread(target=self._process_audio, args=(frames,), daemon=True).start()
            else:
                 # Handle insufficient duration or no frames
                 if not frames:
                     logger.warning("⚠️ No audio frames captured. Skipping.")
                 else:
                     logger.info(f"❌ Duration too short ({duration:.2f}s < {self.min_ptt_duration}s). Skipping.")
                 # --- Use Notification Manager to hide any interim message --- 
                 self.notification_manager.hide_overlay()
                 # ---------------------------------------------------------

    def _handle_ptt_cancel(self):
        """Callback executed by HotkeyManager when Esc is pressed during PTT."""
        logger.info(f"Orchestrator: _handle_ptt_cancel called.")
        self.cancel_requested = True
        # --- Use AudioRecorder to stop the recording loop --- 
        if self.active_recording_thread and self.active_recording_thread.is_alive():
            logger.debug("Signaling AudioRecorder to stop due to cancel request.")
            self.audio_recorder.stop_recording() 
            self.active_recording_thread = None
        # -------------------------------------------------
        # --- Resume playback if it was paused --- 
        self.playback_manager.resume()
        # ----------------------------------------
        # --- Use Notification Manager --- 
        self.notification_manager.show_message("Recording stopped")
        # ------------------------------
            
    # --- Suppression Mediation --- 
    def suppress_hotkeys(self, suppress: bool):
         """Called by other managers (e.g., Clipboard) to suppress hotkeys."""
         if self.hotkey_manager:
             self.hotkey_manager.suppress(suppress)
         else:
             logger.warning("Attempted to set hotkey suppression, but manager not ready.")
             
    def _process_audio(self, frames):
        """Delegates audio processing to AudioProcessor and handles results."""
        logger.debug("Orchestrator delegating processing to AudioProcessor...")
        
        # Call the processor, passing current state
        results = self.audio_processor.process_audio(
            frames,
            self.translation_mode, 
            self.next_stt_language_hint
        )
        
        # Update Orchestrator state based on results
        self.translation_mode = results['new_translation_mode']
        self.next_stt_language_hint = results['new_stt_hint']
        self._last_paste_successful = results['paste_successful']
        text_pasted = results['text_to_paste'] # For overlay logic
        
        logger.debug(f"Processing results received: Mode='{self.translation_mode}', NextHint='{self.next_stt_language_hint}', Pasted='{self._last_paste_successful}'")

        # --- Handle Final Notification (Using NotificationManager) --- 
        if self._last_paste_successful:
            logger.debug("Using NM to show 'Text pasted!'")
            self.notification_manager.show_message("Text pasted!")
        elif text_pasted is None and self.translation_mode in ["swiss_german", "german", "english"]: 
            logger.debug("Mode switch detected, overlay message likely already shown by processor/handler.")
            # Assume processor/handler showed confirmation via notification_manager
        else: # Hide if paste was skipped/failed and not a mode switch
            logger.debug("Paste unsuccessful or skipped. Using NM to hide overlay.")
            self.notification_manager.hide_overlay()
        # -------------------------------------------------------------

    # --- Wrapper for Clipboard Content --- 
    def _get_clipboard_content(self):
         """Provides access to clipboard content via the manager."""
         return self.clipboard_manager.get_content()

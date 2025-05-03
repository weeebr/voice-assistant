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
from .system_playback import SystemPlaybackManager # Added Import
from .clipboard import ClipboardManager # Added Import
from .llm_client import LLMClient # Added Import
from .hotkey import HotkeyManager # Added Import
from .audio_recorder import AudioRecorder # <-- Add new import
from .audio_processor import AudioProcessor # <-- Add new import
from .notification_manager import NotificationManager # <-- Add import
from .api_client import NERServiceClient

# --- Import from config.py --- 
import config as app_config # Use alias to avoid naming conflicts
from config import get_configured_signal_phrases # Import the specific function
# -----------------------------

logger = logging.getLogger(__name__)

# --- Transcription Logging Setup ---
transcription_logger = logging.getLogger('TranscriptionLogger')
transcription_logger.setLevel(logging.INFO)
transcription_logger.propagate = False 
try:
    log_file_path = 'transcriptions.log' 
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    # --- Use ISO 8601 format with Tab separator --- 
    formatter = logging.Formatter('%(asctime)s\t%(message)s', datefmt='%Y-%m-%dT%H:%M:%S') 
    # ---------------------------------------------
    file_handler.setFormatter(formatter)
    transcription_logger.addHandler(file_handler)
    logging.info(f"📝 Transcription logging configured to file: {log_file_path} (with timestamps)")
except Exception as e:
    logging.error(f"❌ Failed to configure transcription file logging to {log_file_path}: {e}")
    # Optionally, disable the logger or handle the error appropriately
    transcription_logger = None # Disable if setup failed

# --- End Transcription Logging Setup ---

class Orchestrator:
    # Define valid PTT keys and their pynput mappings
    VALID_PTT_KEYS = {
        "option": {Key.alt, Key.alt_l, Key.alt_r},
        "cmd": {Key.cmd, Key.cmd_l, Key.cmd_r},
        "ctrl": {Key.ctrl, Key.ctrl_l, Key.ctrl_r},
        "shift": {Key.shift, Key.shift_l, Key.shift_r},
        # Add other keys if needed (e.g., F-keys?)
    }
    DEFAULT_PTT_KEY_NAME = "option"
    DEFAULT_PROCESSING_MODE = "normal" # Changed from "llm"
    
    def __init__(self, config):
        logger.debug("Orchestrator initializing...")
        self.config = config
        self.min_ptt_duration = config.get('min_ptt_duration', 1.2)
        logger.info(f"Minimum PTT duration set to: {self.min_ptt_duration}s")
        # -----------------------------------------
        self.active_recording_thread = None
        self.cancel_requested = False
        self._last_paste_successful = False
        self.next_stt_language_hint = None
        self._playback_was_paused = False
        # --- Add new state --- 
        self.processing_mode = self.DEFAULT_PROCESSING_MODE
        logger.info(f"🚦 Initial processing mode set to: {self.processing_mode}")
        # --------------------
        
        # --- Initialize Managers --- 
        self.playback_manager = SystemPlaybackManager()
        self.clipboard_manager = ClipboardManager(self)
        self.llm_client = LLMClient(config)
        
        # <<< CHANGE Instantiation >>>
        ner_service_url = config.get('ner_service_url', 'http://localhost:5001/extract')
        logger.info(f"🧐 Configuring NERServiceClient to use service at: {ner_service_url}")
        self.ner_service_client = NERServiceClient(ner_service_url) # Use new class name and instance variable name
        # -----------------------------------------------------
        
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
            notification_manager=self.notification_manager,
            clipboard_manager=self.clipboard_manager,
            llm_client=self.llm_client,
            ner_service_client=self.ner_service_client, 
            transcription_logger=transcription_logger 
        )
        logger.debug("AudioProcessor initialized within Orchestrator.")
        
        # --- Initialize HotkeyManager (Now that other components are ready) --- 
        self.hotkey_manager = HotkeyManager(
            ptt_keys=self.VALID_PTT_KEYS[config.get('ptt_hotkey', self.DEFAULT_PTT_KEY_NAME).lower()],
            on_ptt_start=self._handle_ptt_start,
            on_ptt_stop=self._handle_ptt_stop,
            on_cancel=self._handle_ptt_cancel,
            on_ctrl_press_during_ptt=self._handle_ctrl_press_during_ptt # Pass new callback
        )
        # ---------------------------------------------------------------------
            
        logger.debug("Orchestrator initialization complete.")

    def start(self):
        """Starts the HotkeyManager listener and shows ready notification."""
        logger.info("🤖 Assistant PTT mode starting...")
        try:
            self.hotkey_manager.start() # Start the manager's listener
            logger.info("👂 Hotkey listener started via manager.")
            # --- Show Startup Toast --- 
            self.notification_manager.show_message("Assistant Ready!", duration=2.0, group_id="startup_toast")
            logger.info("🍞 Startup notification displayed.")
            # --------------------------
        except Exception as e:
             logger.exception(f"❌ Failed to start hotkey listener via manager: {e}")
             raise # Re-raise critical error

        # --- Use Notification Manager --- 
        # logger.debug("Using NotificationManager to show 'Start recording...'") # Removed redundant log
        # ------------------------------

    def stop(self):
         """Stops the HotkeyManager listener."""
         logger.info("Orchestrator stopping...")
         if self.hotkey_manager:
             self.hotkey_manager.stop()

    # --- Hotkey Callbacks (Called by HotkeyManager) --- 
    def _handle_ptt_start(self, ctrl_pressed: bool):
        """Callback executed by HotkeyManager when PTT key is pressed."""
        logger.debug(f"Orchestrator: _handle_ptt_start called (Ctrl: {ctrl_pressed}).")
        self._playback_was_paused = False # Reset flag at start
        self.cancel_requested = False # Reset flag at start
        # Check if a recording thread from AudioRecorder is already active
        if self.active_recording_thread and self.active_recording_thread.is_alive():
             logger.warning("PTT Start requested, but recording thread already active.")
             return
             
        # --- Conditionally Pause Playback --- 
        if ctrl_pressed:
            logger.info("Ctrl key detected with PTT start, pausing playback...")
            self.playback_manager.pause()
            self._playback_was_paused = True # Remember that we paused it
        # ------------------------------------
        
        # Start recording and keep the thread reference
        self.active_recording_thread = self.audio_recorder.start_recording()
        
        # --- Show Signal Phrases Notification (Using function from config.py) --- 
        try:
            # Call the imported function, passing the COMMANDS list from the imported config
            signal_phrases = get_configured_signal_phrases()
            
            if signal_phrases:
                # Create a concise string of phrases
                display_string = " ⋅ ".join(signal_phrases)
                logger.info(f"🚦 Displaying start notification with signals: {display_string}")
                self.notification_manager.show_message("Recording... 🇨🇭 🇩🇪 🇬🇧\n" + display_string)
        except Exception as e:
             # Log error and show default message if fetching/displaying fails
             logger.error(f"❌ Failed to get or display signal phrases from config.py: {e}")
        # --------------------------------------------------------------------

    def _handle_ptt_stop(self, ctrl_pressed: bool):
        """Callback executed by HotkeyManager when PTT key is released."""
        logger.debug(f"Orchestrator: _handle_ptt_stop called (Ctrl: {ctrl_pressed}).")

        # --- Stop Recording & Get Results ---
        frames, duration = self.audio_recorder.stop_recording()
        self.active_recording_thread = None # Clear the tracked thread
        
        # --- Conditionally Resume Playback --- 
        if self._playback_was_paused:
            logger.info("Playback was paused for this recording, resuming...")
            self.playback_manager.resume() 
        else:
             logger.debug("Playback was not paused for this recording, skipping resume.")
        self._playback_was_paused = False # Reset flag after handling stop
                # -------------------------------------

        # --- Handle Cancellation ---
        if self.cancel_requested:
            logger.info("🚫 Processing cancelled (Esc key pressed).")
            self.cancel_requested = False # Reset flag
            self.notification_manager.show_message("Cancelled", duration=1.0)
            return # Stop processing

        # --- Check Duration and Frames ---
        if not frames:
            logger.warning("⚠️ No audio frames captured after stop. Skipping.")
        if duration < self.min_ptt_duration:
            logger.info(f"❌ Duration too short ({duration:.2f}s < {self.min_ptt_duration}s). Skipping.")
            self.notification_manager.hide_overlay() # <-- FIX 1: Use hide_overlay
            return # Stop processing

        # --- Process Audio Synchronously ---
        logger.info(f"✅ Duration OK ({duration:.2f}s). Processing audio synchronously (Mode: {self.processing_mode})...")
        self.notification_manager.show_message(f"Processing... [{duration:.2f}s]")

        try:
            processing_result = self.audio_processor.process_audio(
                frames,
                self.processing_mode, # Pass current mode
                self.next_stt_language_hint,
                self.DEFAULT_PROCESSING_MODE # Pass default mode
            )

            # --- Update Orchestrator State --- 
            # Update mode based on result, default to current if not specified
            self.processing_mode = processing_result.get('new_processing_mode', self.processing_mode)
            self.next_stt_language_hint = processing_result.get('new_stt_hint', None)

            # --- Paste to Clipboard (Single Point) --- 
            text_to_paste = processing_result.get('text_to_paste')
            paste_successful = processing_result.get('paste_successful', False)

            if paste_successful and text_to_paste is not None:
                logger.info(f"Attempting paste (Mode: {self.processing_mode}): '{text_to_paste[:100]}...'")
                self.clipboard_manager.copy_and_paste(text_to_paste) # *** THE ONLY PASTE CALL ***
                self.notification_manager.show_message(f"Pasted: {text_to_paste[:50]}", duration=2.0)
                self._last_paste_successful = True
            else:
                # Log mode change even if nothing is pasted
                mode_changed = processing_result.get('new_processing_mode') != self.processing_mode and processing_result.get('new_processing_mode') is not None
                if not text_to_paste and not mode_changed:
                     logger.info(f"No text to paste and no mode change (Mode: {self.processing_mode}).")
                elif mode_changed:
                     logger.info(f"Mode changed to '{self.processing_mode}'. No text pasted this time.")
                # Hide processing message if nothing pasted and mode didn't change
                if not mode_changed:
                     self.notification_manager.hide_overlay()
                self._last_paste_successful = False
                
            # Log final state clearly
            logger.info(f"Orchestrator state after processing: Mode='{self.processing_mode}', Next Hint='{self.next_stt_language_hint}'")

        except Exception as e:
            logger.exception("💥 Error during synchronous audio processing:")
            self.notification_manager.show_message("Error processing audio.", duration=3.0)
            self._last_paste_successful = False
        # finally block removed as active_recording_thread is cleared earlier

    def _handle_ptt_cancel(self):
        """Callback executed by HotkeyManager when Esc is pressed during PTT."""
        logger.info(f"Orchestrator: _handle_ptt_cancel called.")
        self.cancel_requested = True # Set flag for _handle_ptt_stop to check
        
        # Check if the recording thread tracked by Orchestrator is active
        if self.active_recording_thread and self.active_recording_thread.is_alive():
        # if self.audio_recorder and self.audio_recorder.is_recording(): # <-- OLD INCORRECT CHECK
            logger.debug("Signaling AudioRecorder to stop due to cancel request.")
            # Call stop_recording but ignore the results here, let _handle_ptt_stop handle cleanup
            self.audio_recorder.stop_recording()
            # Ensure playback resumes if cancel happens mid-recording
            # --- Conditionally Resume on Cancel --- 
            if self._playback_was_paused: # If playback was paused by the corresponding start
                logger.info("Playback was paused, resuming due to cancellation...")
                self.playback_manager.resume()
            self._playback_was_paused = False # Reset flag
            # --------------------------------------
        else:
             logger.debug("Cancel requested but no active recording thread found.")
             # Reset flag even if no recording was active, just in case
             self._playback_was_paused = False 
        
        # --- Show Cancellation Notification --- 
        self.notification_manager.show_message("Recording stopped", duration=1.0)
        # ------------------------------------
        
        # Notification handled by _handle_ptt_stop when it sees cancel_requested flag

    # --- New Callback for Ctrl press during PTT --- 
    def _handle_ctrl_press_during_ptt(self):
        """Called by HotkeyManager when Ctrl is pressed while PTT is active."""
        logger.info("Orchestrator: Ctrl pressed during active recording.")
        if not self._playback_was_paused: # Only pause if not already paused
            logger.info("Pausing playback due to mid-recording Ctrl press...")
            self.playback_manager.pause()
            self._playback_was_paused = True # Set flag so resume works on PTT stop
        else:
            logger.debug("Playback already paused, ignoring mid-recording Ctrl press.")
    # ----------------------------------------------

    # --- Suppression Mediation --- 
    def suppress_hotkeys(self, suppress: bool):
         """Called by other managers (e.g., Clipboard) to suppress hotkeys."""
         if self.hotkey_manager:
             self.hotkey_manager.suppress(suppress)
         else:
             logger.warning("Attempted to set hotkey suppression, but manager not ready.")

    # --- Wrapper for Clipboard Content --- 
    def _get_clipboard_content(self):
         """Provides access to clipboard content via the manager."""
         return self.clipboard_manager.get_content()

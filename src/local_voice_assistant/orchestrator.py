import threading
import time
import logging
import subprocess
import os
import string # <-- Add import
import numpy as np # <-- Add numpy import
import sounddevice as sd # <-- Add sounddevice import
# Initialize Anthropic client for Swiss German translation (requires ANTHROPIC_API_KEY)
try:
    from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT, APIError
    import httpx
    _anthropic_client = None
    _api_key = os.getenv("ANTHROPIC_API_KEY") # Use env var
    if _api_key:
        _anthropic_client = Anthropic(api_key=_api_key)
        logging.info("🤖 Anthropic client initialized successfully.")
    else:
        logging.info("🤖 Anthropic client disabled: ANTHROPIC_API_KEY not set.")
except ImportError:
    _anthropic_client = None
    logging.info("🤖 Anthropic client disabled: 'anthropic' or 'httpx' package not installed.")
except Exception as e:
    logging.error(f"🤖❌ Anthropic init failed: {e}")
    _anthropic_client = None

from .audio_interface import AudioCapture
from .vad import VAD
from .stt import SpeechToText
from .mac_overlay import get_overlay_instance
from pynput import keyboard # Keep pynput for Listener
from pynput.keyboard import Controller, Key, Listener # Add Listener and Key
from types import MethodType # For binding handlers if still used elsewhere, maybe removable?
# Keep MethodType for now in case it's needed by future config structures
import platform # Needed for macOS check potentially

# Import the configuration from the separate file
from .signal_config import SIGNAL_WORD_CONFIG

# Get a logger instance for this module
logger = logging.getLogger(__name__)

# --- Transcription Logging Setup ---
# Create a dedicated logger for transcriptions
transcription_logger = logging.getLogger('TranscriptionLogger')
transcription_logger.setLevel(logging.INFO) # Log informational messages
# Prevent transcription logs from propagating to the root logger (optional but good practice)
transcription_logger.propagate = False 
# Create a handler that writes log records to a file ('a' for append)
# Ensure the log file has appropriate permissions if needed
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
    """
    Coordinates hotkey (Cmd+Esc cancel), audio capture, STT, and pasting.
    """
    # Minimum duration for a PTT press to be processed (in seconds)
    MIN_PTT_DURATION = 1.2  # Reduced from 1.2s to 0.2s for easier testing
    
    def __init__(self, config):
        logger.debug("Orchestrator initializing...")
        self.hotkey_suppressed = False # Used during paste simulation
        self.config = config
        self.ptt_start_time = None # Track start time of PTT press
        self.cmd_held = False      # Track if Cmd key is currently pressed
        self.cancel_requested = False # Track if Esc was pressed during Cmd hold
        self.recording_thread = None # Hold reference to the recording thread
        self.stop_recording_event = threading.Event() # Signal to stop recording
        self.listener_thread = None # Thread for the pynput listener
        self._last_paste_successful = False # Add flag to track successful paste
        self.translation_mode = None 
        # NEW state for next transcription only
        self.next_stt_language_hint = None 
        self.system_playback_paused = False # NEW: Track if we paused system audio
        self.pause_timer_triggered = False # NEW: Track if duration-based pause happened
        
        # Audio components
        self.audio = AudioCapture(
            sample_rate=config.get('sample_rate', 16000),
            channels=config.get('channels', 1),
            mic_name=config.get('mic_name')
        )
        # Log the configured mic name, and the actual sample rate/channels used by AudioCapture
        configured_mic = self.config.get('mic_name') or 'Default'
        logger.info(f"🎤 Audio interface configured (Mic Config: '{configured_mic}', Rate: {self.audio.sample_rate}, Channels: {self.audio.channels})")
        self.vad = VAD(config.get('vad_aggressiveness', 2)) # Keep VAD for potential future use or internal logic
        logger.debug(f"VAD configured (Aggressiveness: {config.get('vad_aggressiveness', 2)})." )
        self.stt = SpeechToText(
            model_size=config.get('model_size', 'small'),
            device=config.get('device', 'cpu'),
            compute_type=config.get('compute_type', 'int8'),
            beam_size=config.get('beam_size', 1)
        )
        logger.info(f"🗣️ STT model loaded (Size: {config.get('model_size', 'small')}, Device: {config.get('device', 'cpu')}, Compute: {config.get('compute_type', 'int8')}, Beam: {config.get('beam_size', 1)})")
        
        # Language setup (Post-processing removed)
        self.language = config.get('language', 'en-US')
        logger.info(f"✍️ Initial language set to: {self.language}")
        
        # Overlay initialization
        self.overlay = None
        try:
            self.overlay = get_overlay_instance()
            logger.info("✅ Overlay enabled.")
        except Exception as e:
            logger.error(f"❌ Failed to initialize overlay: {e}")
            self.overlay = None
            
        # Setup the global keyboard listener (but don't start it yet)
        # Note: Listener runs in its own thread managed by pynput
        self.keyboard_listener = Listener(on_press=self._on_press, on_release=self._on_release)
        # self._bind_signal_handlers() # Keep commented out/removed
        logger.debug("Orchestrator initialization complete.")

    def start(self):
        """Starts the keyboard listener and shows ready notification."""
        logger.info("🚀 Assistant PTT mode starting...")
        try:
            # Start the listener in a non-daemon thread so Python doesn't exit early
            # self.listener_thread = threading.Thread(target=self.keyboard_listener.run, daemon=False)
            # self.listener_thread.start()
            # Correction: pynput's Listener.start() runs it in its own managed thread already.
            self.keyboard_listener.start()
            logger.info("👂 Global keyboard listener started.")
        except Exception as e:
             logger.exception(f"❌ Failed to start keyboard listener: {e}")
             raise RuntimeError("Failed to start keyboard listener.") from e

        # Show "Ready" notification - without a group ID so it doesn't get replaced immediately
        if self.overlay:
            logger.debug("ATTEMPT: Showing 'Voice Assistant Ready' notification")
            self.overlay.show_message("Start recording...", group_id=None)

    def _on_press(self, key):
        """Callback for key press events from pynput Listener."""
        if self.hotkey_suppressed:
            # logger.debug("🔒 Key press suppressed (during paste).") # Can be noisy
            return
            
        # logger.debug(f"Key pressed: {key}") # Very noisy debug
        try:
            if key == Key.cmd:
                if not self.cmd_held:
                    logger.debug("Cmd pressed, starting recording...")
                    self.cmd_held = True
                    self.cancel_requested = False
                    self.stop_recording_event.clear() 
                    self.ptt_start_time = time.monotonic()
                    self.pause_timer_triggered = False # Reset the pause trigger flag
                    
                    # Start recording loop
                    self.recording_thread = threading.Thread(target=self._hotkey_recording_loop, args=(self.stop_recording_event,), daemon=True)
                    self.recording_thread.start()
                    logger.info("🎤 Recording START")
                    
                    # --- REMOVED immediate pause ---
                    # self._pause_system_playback() 
                    # ---------------------------
                    
                else:
                    # logger.debug("Cmd already held, ignoring press.") # Can be noisy
                    pass 
            elif key == Key.esc:
                if self.cmd_held:
                    logger.info("🛑 Esc pressed while Cmd held - Requesting cancellation.")
                    self.cancel_requested = True
                    self.stop_recording_event.set() # Signal recording loop to stop early
                    # Show cancellation notification
                    if self.overlay:
                        logger.debug("ATTEMPT: Showing 'Recording Canceled' notification")
                        # Use None group ID to ensure it shows independently if needed
                        self.overlay.show_message("Recording stopped", group_id=None) 
        except Exception as e:
            logger.exception(f"❌ Error in _on_press: {e}")

    def _on_release(self, key):
        """Callback for key release events from pynput Listener."""
        if self.hotkey_suppressed:
             # logger.debug("🔓 Key release suppressed (during paste).") # Can be noisy
             return
             
        # logger.debug(f"Key released: {key}") # Very noisy debug
        try:
            if key == Key.cmd:
                if self.cmd_held: # Only process release if we thought it was held
                    logger.debug("Cmd released, signaling recording loop to stop...")
                    self.cmd_held = False
                    self.stop_recording_event.set() # Signal recording loop to stop
                    logger.info("🖐️ Recording STOP signaled.")

                    # Wait for the recording thread to finish
                    if self.recording_thread is not None:
                        logger.debug("Waiting for recording thread to join...")
                        self.recording_thread.join(timeout=2.0) # Add a timeout
                        if self.recording_thread.is_alive():
                            logger.warning("⚠️ Recording thread did not join in time.")
                        else:
                            logger.debug("Recording thread joined.")
                        frames, duration = getattr(self.recording_thread, 'result', ([], 0))
                        self.recording_thread = None # Clear the thread reference
                    else:
                        logger.warning("⚠️ Cmd released, but no recording thread found.")
                        frames, duration = [], 0

                    # --- Resume system playback (if we paused it) ---
                    self._resume_system_playback()
                    # -----------------------------------------------

                    # Check if cancellation was requested *before* processing
                    if self.cancel_requested:
                        logger.info("🚫 Processing canceled via Esc key.")
                        # Reset flag for next time
                        self.cancel_requested = False 
                    else:
                        # Proceed with normal duration check and processing
                        logger.info(f"⏱️ PTT duration: {duration:.2f} seconds.")
                        if frames and duration >= self.MIN_PTT_DURATION:
                             logger.info(f"✅ Duration OK ({duration:.2f}s >= {self.MIN_PTT_DURATION}s). Processing...")
                             if self.overlay:
                                 logger.debug("ATTEMPT: Showing 'Processing your request...' notification (独立)")
                                 self.overlay.show_message("Processing your request...", group_id=None)
                             logger.debug("Starting _process_audio thread...")
                             threading.Thread(target=self._process_audio, args=(frames,), daemon=True).start()
                        else:
                             if not frames:
                                 logger.warning("⚠️ No audio frames captured. Skipping.")
                             else:
                                 # Log confirmation that duration check failed and no processing/notification is happening here
                                 logger.debug("--> Duration check FAILED. No processing/notification triggered from _on_release.")
                                 logger.info(f"❌ Duration too short ({duration:.2f}s < {self.MIN_PTT_DURATION}s). Skipping.")
                else:
                     # logger.debug("Cmd released, but wasn't marked as held.") # Can be noisy
                     pass
        except Exception as e:
            logger.exception(f"❌ Error in _on_release: {e}")

    def _hotkey_recording_loop(self, stop_event):
        """Captures audio frames until stop_event is set. Stores result on thread object."""
        logger.debug("🎧 Recording loop thread started.")
        frames = []
        stream = None
        start_time = self.ptt_start_time 
        duration = 0
        
        if start_time is None:
             logger.warning("⚠️ Recording loop started without valid start time.")
             threading.current_thread().result = (frames, duration)
             return 

        try:
            stream = self.audio.speech_audio_stream()
            logger.debug("🔊 Audio stream opened for PTT recording.")

            while not stop_event.is_set():
                # --- Check for duration-based pause ---
                now = time.monotonic()
                elapsed = now - start_time
                if not self.pause_timer_triggered and elapsed >= self.MIN_PTT_DURATION:
                    logger.info(f"⏱️ Recording duration threshold reached ({self.MIN_PTT_DURATION}s). Attempting pause.")
                    self._pause_system_playback() # Attempt pause now
                    self.pause_timer_triggered = True # Set flag so it only happens once
                # -------------------------------------

                try:
                    frame = next(stream)
                    frames.append(frame)
                except StopIteration:
                    logger.warning("⚠️ Audio stream ended unexpectedly during loop.")
                    break # Exit loop if stream ends
                 
            logger.debug(f"🏁 Recording loop finished (stop_event set: {stop_event.is_set()}). Captured {len(frames)} frames.")

        except Exception as e:
             logger.exception(f"💥 Error during hotkey recording stream: {e}")
        finally:
             # Close audio stream
             if hasattr(stream, 'close'):
                 try:
                      logger.debug("🔇 Attempting to close audio stream.")
                      stream.close()
                      logger.debug("🔇 Audio stream closed.")
                 except Exception as e:
                      logger.error(f"❌ Error closing audio stream: {e}")
             
             # Calculate duration *after* the loop
             end_time = time.monotonic()
             duration = end_time - start_time
             logger.debug(f"Recording loop calculated duration: {duration:.2f}s")
             # Store results on the thread object itself for retrieval after join
             threading.current_thread().result = (frames, duration)

    def _process_audio(self, frames):
        """Processes recorded audio frames: accumulates text, then copies/pastes once."""
        if not frames:
            logger.warning("🤔 Process audio called with no frames.")
            return

        logger.info("🔄 Starting audio processing pipeline...")
        self._last_paste_successful = False # Reset flag at the start of processing
       
        accumulated_raw_text = ""
        all_segments = []
        text_to_paste = None 
        chosen_signal_config = None  
        text_for_handler = None # Store the text meant for the handler
        threading.Thread(target=self._play_beep, daemon=True).start()


        try:
            # --- Determine STT Hint for THIS run and RESET the flag --- 
            hint_for_this_run = self.next_stt_language_hint
            default_stt_lang = self.config.get('language', 'en').split('-')[0]
            if hint_for_this_run:
                logger.info(f"🎙️ Using STT language hint for this run: '{hint_for_this_run}' (requested by previous command)")
                self.next_stt_language_hint = None # Reset for next time
            else:
                hint_for_this_run = default_stt_lang # Use default if no hint was set
                # logger.debug(f"Using default STT language hint: {hint_for_this_run}")
            
            # --- Main Segment Processing Loop (Use determined hint) ---
            logger.debug(f"Attempting STT with language hint: {hint_for_this_run}")
            segment_generator = self.stt.transcribe(frames, language=hint_for_this_run)

            for i, segment in enumerate(segment_generator):
                all_segments.append(segment)
                segment_text = segment.text.strip()
                if not segment_text:
                    continue

                sanitized_segment = self._sanitize_text(segment_text)
                accumulated_raw_text += (" " if accumulated_raw_text else "") + sanitized_segment

                logger.debug(f"Segment {i}: [{segment.start:.2f}s - {segment.end:.2f}s] '{sanitized_segment}'")

                # --- Notification Update (Using accumulated sanitized text) ---
                display_text = accumulated_raw_text
                display_text_short = display_text[-100:] if len(display_text) > 100 else display_text
                if self.overlay:
                    logger.debug(f"ATTEMPT: Showing interim notification: '... {display_text_short}'")
                    self.overlay.show_message(f"{display_text_short}...")

            # --- Post-Loop Processing ---
            final_full_sanitized_text = accumulated_raw_text.strip()
            logger.info(f"📝 Full transcription complete (Sanitized): '{final_full_sanitized_text}'")

            # --- Log the final transcription to file ---
            if transcription_logger and final_full_sanitized_text:
                transcription_logger.info(final_full_sanitized_text)
            # --- End logging ---

            final_text_check = final_full_sanitized_text.lower().translate(str.maketrans('', '', string.punctuation)).strip()

            # --- Initial Filtering ('you' and 'thank you') ---
            if final_text_check == "you":
                logger.info("🙅‍♀️ Detected only 'you', skipping.")
                text_to_paste = None 
            elif final_text_check == "thank you": # ADDED FILTER
                logger.info("🙏 Detected only 'thank you', skipping.")
                text_to_paste = None
            
            # --- Process Text if not filtered and not empty ---
            elif final_full_sanitized_text:
                chosen_signal_config = None 
                original_text_lower = final_full_sanitized_text.lower()
                potential_text_for_handler = final_full_sanitized_text # Default

                # --- Check for Signal Words --- 
                for config_key, config in SIGNAL_WORD_CONFIG.items(): 
                    signal_phrase = config.get('signal_phrase')
                    if not signal_phrase:
                        logger.warning(f"Config entry '{config_key}' missing 'signal_phrase'. Skipping.")
                        continue
                        
                    match_position = config.get('match_position', 'anywhere') 
                    match_found = False
                    
                    # Determine text for handler based on potential match FIRST
                    current_text_for_handler = final_full_sanitized_text # Default
                    signal_len = len(signal_phrase)

                    if match_position == 'start':
                         # Match ignoring case for the signal phrase itself at the start
                         if original_text_lower.startswith(signal_phrase):
                            match_found = True
                            # Extract text after the signal phrase
                            remainder = final_full_sanitized_text[signal_len:]
                            # Strip leading punctuation (like comma) and then whitespace
                            current_text_for_handler = remainder.lstrip(',.?!;:').strip()
                    elif match_position == 'end':
                         # Match ignoring case for the signal phrase itself at the end
                         if original_text_lower.endswith(signal_phrase):
                             match_found = True
                             # Extract text before the signal phrase
                             remainder = final_full_sanitized_text[:-signal_len]
                             # Strip trailing punctuation and then whitespace
                             current_text_for_handler = remainder.rstrip(',.?!;:').strip()
                    elif match_position == 'exact':
                         if final_text_check == signal_phrase:
                             match_found = True
                             # For exact match, handler usually gets the full original text
                             # (or maybe None/empty if it's just a command? Depends on handler)
                             current_text_for_handler = final_full_sanitized_text 
                    else: # 'anywhere' (default)
                        # Match ignoring case
                        if signal_phrase in original_text_lower:
                            match_found = True
                            # For anywhere match, handler gets full original text
                            current_text_for_handler = final_full_sanitized_text

                    if match_found:
                        logger.info(f"🚥 Signal detected: '{signal_phrase}' via config '{config_key}' (Match type: {match_position})")
                        chosen_signal_config = config
                        text_for_handler = current_text_for_handler 
                        break 
                
                # --- Perform Action Based on Signal (or Default) ---
                if chosen_signal_config:
                    action = chosen_signal_config.get('action', 'transform')

                    if action == 'set_mode':
                        new_mode = chosen_signal_config.get('mode_value')
                        overlay_msg = chosen_signal_config.get('overlay_message')
                        if self.overlay and overlay_msg:
                            self.overlay.show_message(overlay_msg, group_id=None)
                        if self.translation_mode != new_mode:
                            self.translation_mode = new_mode
                            logger.info(f"🛂 Mode set to: {self.translation_mode}")
                        else:
                            logger.info(f"🛂 Mode already {self.translation_mode}. No change needed.")
                        text_to_paste = None 
                    
                    elif action == 'set_next_stt':
                        new_hint = chosen_signal_config.get('stt_language_value')
                        overlay_msg = chosen_signal_config.get('overlay_message')
                        self.next_stt_language_hint = new_hint # Set hint for NEXT run
                        logger.info(f"🎙️ STT Language hint for NEXT transcription set to: '{self.next_stt_language_hint}'")
                        if self.overlay and overlay_msg: self.overlay.show_message(overlay_msg, group_id=None)
                        text_to_paste = None # Only setting state

                    elif action == 'set_next_stt_and_passthrough':
                        new_hint = chosen_signal_config.get('stt_language_value')
                        overlay_msg = chosen_signal_config.get('overlay_message')
                        # 1. Set STT Language hint for next time
                        self.next_stt_language_hint = new_hint
                        logger.info(f"🎙️ STT Language hint for NEXT transcription set to: '{self.next_stt_language_hint}' (via passthrough)")
                        if self.overlay and overlay_msg: self.overlay.show_message(overlay_msg, group_id=None)
                        # 2. Paste the remainder - Beep BEFORE setting text_to_paste
                        logger.info(f"⏩ Passing through remainder text for pasting: '{text_for_handler}'")
                        text_to_paste = text_for_handler
                            
                    elif action == 'transform':
                        # --- Translation Step (Applied BEFORE transformation handler) ---
                        # Note: This block is now primarily relevant if the SG translation mode 
                        # was set by an *exact* command earlier, and a *different* transform 
                        # command (like 'fix') is used subsequently.
                        # The SG translate command handler does its own translation.
                        effective_text_for_processing = text_for_handler 
                        if self.translation_mode == "swiss_german": 
                            logger.info(f"🇨🇭 Mode=SG. Attempting translation for: '{effective_text_for_processing}'")
                            if self.overlay: self.overlay.show_message("Translating (SG)...")
                            translated_text = self._translate_to_swiss_german(effective_text_for_processing)
                            if translated_text:
                                logger.info(f"🇨🇭 Translation successful: '{translated_text}'")
                                effective_text_for_processing = translated_text 
                            else:
                                logger.warning("⚠️ Translation failed/skipped. Using original/untranslated text for handler.")
                        
                        # --- Apply Transformation Handler ---
                        handler = chosen_signal_config.get('handler')
                        if callable(handler):
                            try:
                                logger.info(f"⚙️ Calling transformation handler...")
                                text_to_paste = handler(self, effective_text_for_processing) 
                                if text_to_paste is None:
                                     logger.warning(f"🤔 Handler returned None.")
                            except Exception as e:
                                logger.exception(f"💥 Error executing handler: {e}")
                                text_to_paste = None
                        else:
                            logger.error(f"❌ Configured handler for transform action is not callable: {handler}")
                            text_to_paste = None
                            
                    else:
                        logger.warning(f"⚠️ Unknown action '{action}' in signal config for '{final_full_sanitized_text}'. Doing nothing.")
                        text_to_paste = None
                        
                # --- No Signal Word Found (Default Behavior) ---
                else: 
                    effective_text_for_processing = final_full_sanitized_text # Use full text
                    # Apply translation ONLY if SG mode is active AND no other signal matched
                    if self.translation_mode == "swiss_german":
                        logger.info(f"🇨🇭 Mode=SG. Attempting translation for default text: '{effective_text_for_processing}'")
                        # ... (call _translate_to_swiss_german)
                        # ... (update effective_text_for_processing if successful)
                        pass 
                         
                    text_to_paste = effective_text_for_processing

            # --- Safety Check (Should not be needed with current logic, but good practice) ---
            # If text_to_paste ended up None unexpectedly after valid initial text.
            elif text_to_paste is None and final_full_sanitized_text: 
                 logger.warning(f"Text '{final_full_sanitized_text}' resulted in None for pasting unexpectedly.")

        except Exception as e:
            logger.exception(f"💥 Unhandled error in audio processing pipeline: {e}")
        finally:
            # --- Final Paste ---
            if text_to_paste: # Check if we have something valid to paste
                logger.info(f"✅ Proceeding to copy and paste: '{text_to_paste}'")
                self._copy_and_paste_final(text_to_paste)
            else:
                logger.info("🤷 No valid text to paste (empty, 'you', mode command, or error).")

            # --- Final Notification ---
            if self.overlay:
                 if self._last_paste_successful:
                     logger.debug("ATTEMPT: Showing 'Text pasted!' notification")
                     self.overlay.show_message("Text pasted!") # Shows after successful paste
                 elif text_to_paste is None and final_text_check in ["swiss german", "german", "english"]:
                     # Don't hide overlay immediately after mode switch, notification is already shown
                     logger.debug("Mode switch detected, overlay message already shown.")
                 else: # Hide if paste was skipped/failed (and not a mode switch)
                     logger.debug("Skipping 'Text pasted!' notification (paste unsuccessful or skipped). Hiding overlay.")
                     self.overlay.hide_overlay() # Or remove notification group? Needs testing.

            logger.info("🏁 Audio processing pipeline finished.")

    def _sanitize_text(self, text):
        """Performs basic text sanitization."""
        # Using simple replace, consider more robust sanitization if needed.
        return text.replace('ß', 'ss').replace('"', '"').replace("'", "'")

    def _copy_to_clipboard(self, text):
        """Copies the given text to the system clipboard using pbcopy."""
        if not text:
            logger.debug("Skipping clipboard copy for empty text.")
            return
        try:
            subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
            logger.info(f"📋✅ Copied final text to clipboard (Length: {len(text)}). ")
        except FileNotFoundError:
             logger.error("📋❌ pbcopy not found (macOS only). Cannot copy final text.")
        except subprocess.CalledProcessError as e:
            logger.error(f"📋❌ Failed to copy final text (pbcopy): {e}")
        except Exception as e:
            logger.error(f"📋💥 Unexpected error copying final text: {e}")

    def _simulate_paste_keystroke(self):
        """Simulates Cmd+V keystroke using pynput."""
        # Paste via Cmd+V (suppress hotkey listener during synthetic press)
        try:
            kb = Controller()
            self.hotkey_suppressed = True
            logger.debug("🔒 Suppressing hotkey for paste")
            try:
                # Simulate Cmd+V - ensure Controller and Key are imported at the top
                with kb.pressed(Key.cmd):
                    kb.press('v')
                    kb.release('v')
                logger.info("⌨️ Pasted via Cmd+V.") # Log paste action
                # Set success flag *after* successful paste simulation
                self._last_paste_successful = True 
            except Exception as e:
                 logger.error(f"⌨️❌ Error during paste simulation: {e}")
                 self._last_paste_successful = False # Ensure flag is false on error
            finally:
                 # Ensure suppression is always released
                 time.sleep(0.05) # Add tiny delay AFTER paste before re-enabling hotkey
                 self.hotkey_suppressed = False
                 logger.debug("🔓 Re-enabled hotkey after paste attempt")
        except NameError:
             logger.error("⌨️❌ pynput unavailable. Cannot simulate paste.")
             self._last_paste_successful = False
        except Exception as e:
            logger.error(f"⌨️💥 Failed to init pynput or paste: {e}")
            self._last_paste_successful = False

    # New method to handle the final copy and paste action
    def _copy_and_paste_final(self, text):
        """Copies the final text and simulates paste."""
        if not text:
            logger.debug("Skipping final copy/paste for empty text.")
            self._last_paste_successful = False
            return
        
        # Reset success flag before attempting
        self._last_paste_successful = False 
        
        # 1. Copy
        self._copy_to_clipboard(text) 
        
        # 2. Paste (only if copy likely succeeded - pbcopy raises errors)
        # Note: _copy_to_clipboard logs errors but doesn't return status. 
        # We'll assume if no exception stopped execution, copy worked.
        self._simulate_paste_keystroke() 
        
        # The _simulate_paste_keystroke method sets self._last_paste_successful

    def _translate_to_swiss_german(self, text):
        """Translates text to Swiss German using the Anthropic API."""
        if not _anthropic_client:
            logger.error("🤖❌ Anthropic client not available. Cannot translate.")
            return None
        if not text:
            logger.warning("⚠️ Translation requested for empty text. Skipping.")
            return None

        logger.debug(f"Sending to Anthropic for SG translation: '{text}'")
        try:
            # Improved prompt assuming input might be English or German
            prompt = (
                f"{HUMAN_PROMPT}Translate the following text into Swiss German (Schweizerdeutsch). "
                f"The input language might be English or German. Provide ONLY the Swiss German translation, "
                f"without any explanations, commentary, or preamble.\\n\\n"
                f"Input Text:\\n{text}\\n\\n"
                f"Swiss German Translation:{AI_PROMPT}"
            )
            
            # Use a model suitable for instruction following. claude-2.1 is okay,
            # but newer models like claude-3-sonnet or haiku might be better/faster/cheaper.
            # Let's stick with claude-2.1 for consistency for now.
            completion = _anthropic_client.completions.create(
                model="claude-2.1", 
                max_tokens_to_sample=300, # Adjust as needed
                prompt=prompt,
                temperature=0.3, # Lower temperature for more deterministic translation
            )
            
            translated_text = completion.completion.strip()
            logger.debug(f"🤖 Anthropic response received: '{translated_text}'")
            
            # Basic check: Ensure response isn't empty or just echoing input (Claude sometimes does this on failure)
            if not translated_text or translated_text.lower() == text.lower():
                 logger.warning(f"⚠️ Anthropic translation result seems empty or is identical to input. Original: '{text}', Result: '{translated_text}'")
                 return None # Treat as failure

            return translated_text

        except APIError as e:
            logger.error(f"🤖❌ Anthropic API error during translation: {e}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"🤖❌ Anthropic request timed out: {e}")
            return None
        except Exception as e:
            logger.exception(f"🤖💥 Unexpected error during Anthropic translation: {e}")
            return None

    def _get_llm_transformation(self, prompt_text):
        """Gets a transformation/response from the LLM using the provided prompt."""
        if not _anthropic_client:
            logger.error("🤖❌ Anthropic client not available. Cannot perform LLM transformation.")
            return None
        if not prompt_text:
            logger.warning("⚠️ LLM transformation requested with empty prompt. Skipping.")
            return None

        logger.debug(f"Sending prompt to Anthropic (Messages API): '{prompt_text[:100]}...'")
        try:
            # --- Messages API Structure ---
            messages = [
                {"role": "user", "content": prompt_text}
            ]
            
            # Call the messages.create method
            completion = _anthropic_client.messages.create(
                model="claude-3-haiku-20240307", 
                max_tokens=1000, # Note: param name is max_tokens now
                messages=messages,
                temperature=0.7, 
            )
            
            # Extract response text from the first content block
            if completion.content and len(completion.content) > 0:
                response_text = completion.content[0].text.strip()
                logger.debug(f"🤖 Anthropic response received (Messages API): '{response_text[:100]}...'")
                if not response_text:
                     logger.warning("⚠️ Anthropic LLM transformation result is empty.")
                     return None 
                return response_text
            else:
                logger.warning("⚠️ Anthropic response content is empty or missing.")
                return None

        except APIError as e:
            # Log the detailed error if possible
            try:
                error_details = e.body
            except Exception:
                error_details = "(Could not parse error body)"
            logger.error(f"🤖❌ Anthropic API error during LLM transformation: {e.status_code} - {error_details}")
            return None
        except httpx.TimeoutException as e:
            logger.error(f"🤖❌ Anthropic LLM transformation request timed out: {e}")
            return None
        except Exception as e:
            logger.exception(f"🤖💥 Unexpected error during Anthropic LLM transformation: {e}")
            return None

    def _play_beep(self):
        """Generates and plays a short beep sound in a separate thread."""
        try:
            samplerate = self.audio.sample_rate if self.audio else 16000 # Use audio interface rate or default
            frequency = 440  # Hz (A4 note)
            duration = 0.1   # seconds
            amplitude = 0.38 # Reduce amplitude slightly from 0.42

            t = np.linspace(0., duration, int(samplerate * duration), endpoint=False)
            waveform = amplitude * np.sin(2. * np.pi * frequency * t)

            # Ensure waveform is float32, required by some sounddevice backends
            waveform = waveform.astype(np.float32) 

            sd.play(waveform, samplerate)
            # sd.wait() # Don't wait here, let it play in the background
            logger.debug(f"🔊 Beep initiated (Freq: {frequency}Hz, Dur: {duration}s)")
        except AttributeError as e:
             # Handle case where self.audio might not be fully initialized if error occurs early
             logger.error(f"🔊 Error playing beep (Audio interface not ready?): {e}")
        except Exception as e:
            logger.error(f"🔊 Error playing beep sound: {e}")

    # --- System Playback Control --- 
    
    # AppleScript for native apps
    _APPLE_SCRIPT_PAUSE = """
    # Music
    try
        if application "Music" is running then
            tell application "Music" to pause
        end if
    end try
    # Spotify
    try
        if application "Spotify" is running then
            tell application "Spotify" to pause
        end if
    end try
    """ # NOTE: YouTube removed from here
    
    _APPLE_SCRIPT_RESUME = """
    # Music
    try
        if application "Music" is running then
            tell application "Music" to play
        end if
    end try
    # Spotify
    try
        if application "Spotify" is running then
            tell application "Spotify" to play
        end if
    end try
    """ # NOTE: YouTube removed from here

    # JXA for Chrome/YouTube
    _JXA_PAUSE_CHROME_YT = """ 
    (() => {
      try {
        const chrome = Application('Google Chrome Beta');
        if (!chrome.running()) { return; }
        chrome.windows().forEach((w) => {
          try {
            w.tabs().forEach((t) => {
              const url = t.url();
              if (url && url.includes('youtube.com/watch')) {
                try {
                  t.execute({javascript: "document.querySelector('video').pause();"});
                  // Optional: Add return here to only pause the first one found?
                } catch (e) { console.log('JS pause error: ' + e); }
              }
            });
          } catch (e) { /* Maybe not a browser window */ }
        });
      } catch (e) { console.log('Chrome JXA error: ' + e); }
    })();
    """
    
    _JXA_RESUME_CHROME_YT = """
    (() => {
      try {
        const chrome = Application('Google Chrome Beta');
        if (!chrome.running()) { return; }
        chrome.windows().forEach((w) => {
          try {
            w.tabs().forEach((t) => {
              const url = t.url();
              if (url && url.includes('youtube.com/watch')) {
                try {
                  t.execute({javascript: "document.querySelector('video').play();"});
                } catch (e) { console.log('JS play error: ' + e); }
              }
            });
          } catch (e) { /* Maybe not a browser window */ }
        });
      } catch (e) { console.log('Chrome JXA error: ' + e); }
    })();
    """

    def _pause_system_playback(self):
        if platform.system() != "Darwin":
            logger.debug("Skipping system playback pause (not on macOS).")
            return
            
        logger.debug("Attempting to pause system playback (Music/Spotify via AppleScript)...")
        paused_apple_apps = False
        try:
            # 1. Pause Music/Spotify via AppleScript
            process_as = subprocess.run(
                ['osascript', '-e', self._APPLE_SCRIPT_PAUSE],
                capture_output=True, text=True, check=False, timeout=2
            )
            if process_as.returncode == 0:
                logger.info("⏯️ Music/Spotify pause command sent.")
                paused_apple_apps = True # Mark if this part succeeded
            else:
                logger.warning(f"⏯️ Music/Spotify pause AS failed (code {process_as.returncode}): {process_as.stderr}")
        except Exception as e:
            logger.error(f"⏯️ Unexpected error pausing Music/Spotify (AS): {e}")

        logger.debug("Attempting to pause system playback (Chrome/YouTube via JXA)...")
        paused_jxa_apps = False
        try:
             # 2. Pause Chrome/YouTube via JXA
            process_jxa = subprocess.run(
                ['osascript', '-l', 'JavaScript'],
                input=self._JXA_PAUSE_CHROME_YT, 
                capture_output=True, text=True, check=False, timeout=3 # Slightly longer timeout?
            )
            if process_jxa.returncode == 0:
                logger.info("⏯️ Chrome/YouTube pause command sent.")
                paused_jxa_apps = True # Mark if this part succeeded
            else:
                logger.warning(f"⏯️ Chrome/YouTube pause JXA failed (code {process_jxa.returncode}): {process_jxa.stdout or process_jxa.stderr}")
        except Exception as e:
            logger.error(f"⏯️ Unexpected error pausing Chrome/YouTube (JXA): {e}")
            
        # Set the main flag only if at least one pause attempt seemed okay
        self.system_playback_paused = paused_apple_apps or paused_jxa_apps
        if not self.system_playback_paused:
             logger.warning("⏯️ Failed to pause any media application.")

            
    def _resume_system_playback(self):
        if not self.system_playback_paused:
            # ... (skip message)
            return
        if platform.system() != "Darwin":
            # ... (skip message)
            self.system_playback_paused = False 
            return
            
        logger.debug("Attempting to resume system playback (Music/Spotify via AppleScript)...")
        try:
            # 1. Resume Music/Spotify via AppleScript
            process_as = subprocess.run(
                ['osascript', '-e', self._APPLE_SCRIPT_RESUME],
                capture_output=True, text=True, check=False, timeout=2
            )
            if process_as.returncode == 0:
                logger.info("▶️ Music/Spotify resume command sent.")
            else:
                logger.warning(f"▶️ Music/Spotify resume AS failed (code {process_as.returncode}): {process_as.stderr}")
        except Exception as e:
            logger.error(f"▶️ Unexpected error resuming Music/Spotify (AS): {e}")

        logger.debug("Attempting to resume system playback (Chrome/YouTube via JXA)...")
        try:
            # 2. Resume Chrome/YouTube via JXA
            process_jxa = subprocess.run(
                ['osascript', '-l', 'JavaScript'],
                input=self._JXA_RESUME_CHROME_YT, 
                capture_output=True, text=True, check=False, timeout=3
            )
            if process_jxa.returncode == 0:
                logger.info("▶️ Chrome/YouTube resume command sent.")
            else:
                logger.warning(f"▶️ Chrome/YouTube resume JXA failed (code {process_jxa.returncode}): {process_jxa.stdout or process_jxa.stderr}")
        except Exception as e:
            logger.error(f"▶️ Unexpected error resuming Chrome/YouTube (JXA): {e}")
        finally:
            # Always reset the main flag after attempting resume
            self.system_playback_paused = False

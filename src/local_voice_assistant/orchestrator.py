import threading
import time
import logging
import subprocess
import os
import string # <-- Add import
# Initialize Anthropic client for Swiss German translation (requires ANTHROPIC_API_KEY)
try:
    from anthropic import Anthropic, HUMAN_PROMPT, AI_PROMPT
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

# Get a logger instance for this module
logger = logging.getLogger(__name__)

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
                    self.stop_recording_event.clear() # Ensure event is clear before starting
                    self.ptt_start_time = time.monotonic()
                    
                    # Start the recording loop in a separate thread
                    self.recording_thread = threading.Thread(target=self._hotkey_recording_loop, args=(self.stop_recording_event,), daemon=True)
                    self.recording_thread.start()
                    logger.info("🎤 Recording START")
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
        start_time = self.ptt_start_time # Use start time set in _on_press
        duration = 0
        
        if start_time is None:
             logger.warning("⚠️ Recording loop started without valid start time.")
             threading.current_thread().result = (frames, duration)
             return 

        try:
            stream = self.audio.speech_audio_stream()
            logger.debug("🔊 Audio stream opened for PTT recording.")

            while not stop_event.is_set():
                try:
                    frame = next(stream)
                    frames.append(frame)
                    # Add a small sleep to prevent tight loop if stream provides data very fast?
                    # time.sleep(0.001) 
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

        try:
            # REMOVED: Initial quick transcription block for trigger words
            # chunk_size = min(len(frames), 64000)
            # initial_chunk = frames[:chunk_size]
            # ... (removed initial self.stt.transcribe call and raw.strip()) ...

            # --- Main Segment Processing Loop ---
            target_hint = self.language.split('-', 1)[0].lower() if self.language else None
            segment_generator = self.stt.transcribe(frames, language=target_hint)

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

            # --- Final Check and Paste ---
            # Convert to lowercase, remove punctuation, and strip whitespace for the check
            final_text_check = final_full_sanitized_text.lower().translate(str.maketrans('', '', string.punctuation)).strip()
            if final_text_check == "you":
                logger.info("🙅‍♀️ Detected only 'you' (after cleaning), skipping paste and final clipboard update.")
            elif final_full_sanitized_text: # Check if original wasn't empty either
                logger.info(f"✅ Final check OK. Copying and pasting full text: '{final_full_sanitized_text}'")
                self._copy_and_paste_final(final_full_sanitized_text) # Call the single copy/paste method
            else:
                logger.info("🤷 No text transcribed, skipping paste.")

            # Trigger word checks skipped
            logger.debug("🔍 Trigger word checks skipped.")

        except Exception as e:
            logger.exception(f"💥 Unhandled error in audio processing pipeline: {e}")
        finally:
            # Final notification about completion - only show if text was actually pasted.
            if self.overlay:
                 if self._last_paste_successful:
                     logger.debug("ATTEMPT: Showing 'Text pasted!' notification")
                     self.overlay.show_message("Text pasted!")
                 else:
                      # Maybe show a generic "Processing complete" if nothing was pasted but it finished?
                      # Or just hide immediately? Let's hide for now.
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

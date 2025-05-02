import logging
import string
import threading

# --- Add potential imports needed by translation (if LLMClient doesn't handle all errors) ---
# import httpx # Might be needed if we catch httpx specific errors
# from anthropic import APIError # Might be needed for provider-specific errors
# ----------------------------------------------------------------------------------

# Import the signal word configuration
from .signal_config import SIGNAL_WORD_CONFIG

# Get a logger instance for this module
logger = logging.getLogger(__name__)

class AudioProcessor:
    """
    Handles the processing of recorded audio frames, including:
    - Speech-to-text transcription
    - Signal word detection and handling
    - Text transformations (including LLM calls)
    - State updates (translation mode, STT hints)
    - Interaction with overlay and clipboard
    """
    def __init__(self, stt, config, notification_manager, clipboard_manager, llm_client, transcription_logger):
        logger.debug("AudioProcessor initializing...")
        self.stt = stt
        self.config = config
        self.notification_manager = notification_manager
        self.clipboard_manager = clipboard_manager
        self.llm_client = llm_client
        self.transcription_logger = transcription_logger
        logger.debug("AudioProcessor initialized.")

    def process_audio(self, frames, current_translation_mode, current_stt_hint):
        """
        Processes recorded audio frames.
        
        Args:
            frames: A list of audio frames.
            current_translation_mode: The current translation mode from Orchestrator.
            current_stt_hint: The current STT language hint for the next run.

        Returns:
            A dictionary containing processing results:
            {
                'text_to_paste': str | None,
                'new_translation_mode': str | None,
                'new_stt_hint': str | None,
                'paste_successful': bool
            }
        """
        logger.info("🔄 Starting audio processing pipeline...")
        if not frames:
            logger.warning("🤔 Process audio called with no frames.")
            return {
                'text_to_paste': None,
                'new_translation_mode': current_translation_mode,
                'new_stt_hint': current_stt_hint,
                'paste_successful': False
            }
            
        # --- Initialize state for this run --- 
        text_to_paste = None
        paste_successful = False
        # Start with current state, these will be updated and returned
        new_translation_mode = current_translation_mode 
        new_stt_hint = current_stt_hint

        # --- Use NotificationManager for beep --- 
        self.notification_manager.play_beep()

        # --- Start of moved logic from Orchestrator._process_audio ---
        accumulated_raw_text = ""
        all_segments = []
        # Removed: text_to_paste = None (already initialized above)
        chosen_signal_config = None  
        text_for_handler = None # Store the text meant for the handler

        try:
            # --- Determine STT Hint for THIS run and RESET the flag --- 
            hint_for_this_run = new_stt_hint # Use the state passed in
            default_stt_lang = self.config.get('language', 'en').split('-')[0]
            if hint_for_this_run:
                logger.info(f"🎙️ Using STT language hint for this run: '{hint_for_this_run}' (requested by previous command)")
                new_stt_hint = None # Reset hint for the *next* run (will be returned)
            else:
                hint_for_this_run = default_stt_lang # Use default if no hint was set
            
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

                # --- Notification Update (Using NotificationManager) ---
                display_text = accumulated_raw_text
                display_text_short = display_text[-100:] if len(display_text) > 100 else display_text
                logger.debug(f"Using NM to show interim notification: '... {display_text_short}'")
                self.notification_manager.show_message(f"{display_text_short}...")

            # --- Post-Loop Processing ---
            final_full_sanitized_text = accumulated_raw_text.strip()
            logger.info(f"📝 Full transcription complete (Sanitized): '{final_full_sanitized_text}'")

            # --- Log the final transcription to file ---
            if self.transcription_logger and final_full_sanitized_text:
                self.transcription_logger.info(final_full_sanitized_text)
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
                         if original_text_lower.startswith(signal_phrase):
                            match_found = True
                            remainder = final_full_sanitized_text[signal_len:]
                            current_text_for_handler = remainder.lstrip(',.?!;:').strip()
                    elif match_position == 'end':
                         if original_text_lower.endswith(signal_phrase):
                             match_found = True
                             remainder = final_full_sanitized_text[:-signal_len]
                             current_text_for_handler = remainder.rstrip(',.?!;:').strip()
                    elif match_position == 'exact':
                         if final_text_check == signal_phrase:
                             match_found = True
                             current_text_for_handler = final_full_sanitized_text 
                    else: # 'anywhere' (default)
                        if signal_phrase in original_text_lower:
                            match_found = True
                            current_text_for_handler = final_full_sanitized_text

                    if match_found:
                        logger.info(f"🚥 Signal detected: '{signal_phrase}' via config '{config_key}' (Match type: {match_position})")
                        chosen_signal_config = config
                        text_for_handler = current_text_for_handler 
                        break 
                
                # --- Perform Action Based on Signal (or Default) ---
                if chosen_signal_config:
                    signal_phrase = chosen_signal_config.get('signal_phrase', 'Unknown') # Get phrase for message
                    logger.info(f"Confirmed signal match: '{signal_phrase}'")
                    # --- Show Signal Detected Notification --- 
                    self.notification_manager.show_message(f"🚥 Signal: '{signal_phrase}'")
                    # -----------------------------------------
                    action = chosen_signal_config.get('action', 'transform')

                    if action == 'set_mode':
                        new_mode = chosen_signal_config.get('mode_value')
                        overlay_msg = chosen_signal_config.get('overlay_message')
                        if overlay_msg: self.notification_manager.show_message(overlay_msg)
                        # Update the state variable to be returned
                        if new_translation_mode != new_mode: 
                            new_translation_mode = new_mode
                            logger.info(f"🛂 Mode set to: {new_translation_mode}")
                        else:
                            logger.info(f"🛂 Mode already {new_translation_mode}. No change needed.")
                        text_to_paste = None 
                    
                    elif action == 'set_next_stt':
                        hint_val = chosen_signal_config.get('stt_language_value')
                        overlay_msg = chosen_signal_config.get('overlay_message')
                        # Update the state variable to be returned
                        new_stt_hint = hint_val # Set hint for NEXT run
                        logger.info(f"🎙️ STT Language hint for NEXT transcription set to: '{new_stt_hint}'")
                        if overlay_msg: self.notification_manager.show_message(overlay_msg)
                        text_to_paste = None # Only setting state

                    elif action == 'set_next_stt_and_passthrough':
                        hint_val = chosen_signal_config.get('stt_language_value')
                        overlay_msg = chosen_signal_config.get('overlay_message')
                        # 1. Update STT hint to be returned
                        new_stt_hint = hint_val
                        logger.info(f"🎙️ STT Language hint for NEXT transcription set to: '{new_stt_hint}' (via passthrough)")
                        if overlay_msg: self.notification_manager.show_message(overlay_msg)
                        # 2. Set the remainder for pasting
                        logger.info(f"⏩ Passing through remainder text for pasting: '{text_for_handler}'")
                        text_to_paste = text_for_handler
                            
                    elif action == 'transform':
                        effective_text_for_processing = text_for_handler 
                        # --- Translation Step --- 
                        if new_translation_mode == "swiss_german": 
                            logger.info(f"🇨🇭 Mode=SG. Attempting translation via _translate_to_swiss_german: '{effective_text_for_processing}'")
                            # Notification manager call is now inside _translate_to_swiss_german
                            # self.notification_manager.show_message("Translating (SG)...") 
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
                                # --- Add LLM Call Notification if handler uses LLM --- 
                                # Heuristic: Check if handler is a lambda AND mentions llm_client 
                                # This is brittle; assumes LLM calls only happen via llm_client.transform_text
                                import inspect
                                try: 
                                    handler_source = inspect.getsource(handler)
                                    if 'llm_client.transform_text' in handler_source:
                                        self.notification_manager.show_message("🧠 Calling LLM...")
                                except (TypeError, OSError):
                                    logger.warning("Could not inspect handler source to determine if LLM call is likely.")
                                # -----------------------------------------------------
                                logger.info(f"⚙️ Calling transformation handler (lambda/function from config)...")
                                text_to_paste = handler(
                                    self.llm_client, 
                                    self.clipboard_manager, 
                                    effective_text_for_processing
                                ) 
                                # ----------------------------------------
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
                    effective_text_for_processing = final_full_sanitized_text
                    # Apply translation ONLY if SG mode is active AND no other signal matched
                    if new_translation_mode == "swiss_german":
                        # --- Call the refactored method --- 
                        logger.info(f"🇨🇭 Mode=SG. Attempting translation for default text via _translate_to_swiss_german: '{effective_text_for_processing}'")
                        if self.notification_manager: self.notification_manager.show_message("Translating (SG)...")
                        translated_text = self._translate_to_swiss_german(effective_text_for_processing)
                        # ---------------------------------
                        if translated_text:
                             logger.info(f"🇨🇭 Default translation successful: '{translated_text}'")
                             effective_text_for_processing = translated_text # Update text to paste
                        else:
                             logger.warning("⚠️ Default translation failed/skipped. Using original text.")
                    text_to_paste = effective_text_for_processing # Paste original or translated

            # --- Safety Check ---
            elif text_to_paste is None and final_full_sanitized_text: 
                 logger.warning(f"Text '{final_full_sanitized_text}' resulted in None for pasting unexpectedly.")

        except Exception as e:
            logger.exception(f"💥 Unhandled error in audio processing pipeline: {e}")
        finally:
            # --- Final Paste --- 
            if text_to_paste: # Check if we have something valid to paste
                logger.info(f"✅ Proceeding to copy and paste via ClipboardManager: '{text_to_paste}'")
                # Update local paste_successful based on manager result
                paste_successful = self.clipboard_manager.copy_and_paste(text_to_paste) 
            else:
                logger.info("🤷 No valid text to paste (empty, 'you', mode command, or error).")
                paste_successful = False # Ensure flag is false

        logger.info("🏁 Audio processing pipeline finished.")
        return {
            'text_to_paste': text_to_paste,
            'new_translation_mode': new_translation_mode,
            'new_stt_hint': new_stt_hint,
            'paste_successful': paste_successful
        }
        
    def _sanitize_text(self, text):
        """Performs basic text sanitization."""
        # Using simple replace, consider more robust sanitization if needed.
        return text.replace('ß', 'ss').replace('"', '"').replace("'", "'")

    # --- ADD Refactored _translate_to_swiss_german Method --- 
    def _translate_to_swiss_german(self, text):
        """Translates text to Swiss German using the configured LLM client."""
        if not text:
            logger.warning("⚠️ Swiss German translation requested for empty text. Skipping.")
            return None

        prompt = f"Translate the following English text into Swiss German (Schweizerdeutsch). Provide only the translation:\n\nEnglish Text: {text}"
        
        logger.debug(f"Attempting SG translation via LLMClient with prompt: '{prompt[:100]}...'")
        try:
            # --- Add LLM Call Notification --- 
            self.notification_manager.show_message("🧠 Calling LLM (for SG translation)...")
            # ---------------------------------
            translated_text = self.llm_client.transform_text(
                prompt,
                model_override='claude-3-haiku-20240307' # Example override
            )
            
            if translated_text:
                logger.info("✅ LLM translation successful.")
                return translated_text.strip()
            else:
                logger.warning("LLM translation returned empty result.")
                return None
        except Exception as e:
            # LLMClient should ideally log the specifics, but we log here too
            logger.exception(f"💥 Error during LLM translation call in _translate_to_swiss_german: {e}")
            return None

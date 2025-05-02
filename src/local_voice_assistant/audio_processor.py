import logging
import string
import threading
import json
import os
import time

# --- Add potential imports needed by translation (if LLMClient doesn't handle all errors) ---
# import httpx # Might be needed if we catch httpx specific errors
# from anthropic import APIError # Might be needed for provider-specific errors
# ----------------------------------------------------------------------------------

# Import the signal word configuration
# from .signal_config import SIGNAL_WORD_CONFIG

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
        
        # --- Load Signal Config from Python module (config.py) --- 
        self.signal_configs = [] # Initialize as an empty list
        try:
            # Import the module dynamically
            import config 
            # Reload the module in case it's changed since the app started (optional but safer)
            import importlib
            importlib.reload(config)
            
            # Attempt to access the expected variable (COMMANDS)
            if hasattr(config, 'COMMANDS') and isinstance(config.COMMANDS, list):
                self.signal_configs = config.COMMANDS # <-- Use correct variable name
                logger.info(f"✅ Loaded {len(self.signal_configs)} signal configurations from variable 'COMMANDS' in config.py")
            else:
                logger.error("❌ Found config.py, but variable 'COMMANDS' is missing or not a list. Signals disabled.")
        except ImportError:
            logger.error("❌ Failed to import config.py. Does it exist in the Python path? Signals disabled.")
            # If config.py is in the same directory, this shouldn't happen unless there's a syntax error
            # preventing import.
        except Exception as e:
            logger.exception(f"💥 Failed to load or process signal config from config.py: {e}")
        # --- Removed old file reading/JSON parsing logic ---
        
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

        # --- Use NotificationManager for beep (with delay) --- 
        # Add a small delay to allow audio system to settle
        time.sleep(0.1)
        # Re-enable beep
        self.notification_manager.play_beep()

        # --- Start of moved logic from Orchestrator._process_audio ---
        accumulated_raw_text = ""
        all_segments = []
        # Removed: text_to_paste = None (already initialized above)
        chosen_signal_config = None  
        text_for_handler = None # Store the text meant for the handler

        try:
            # --- Determine STT Hint for THIS run --- 
            # Use a different variable for the hint *for this run*
            hint_for_this_run = current_stt_hint # Start with hint passed from Orchestrator state
            default_stt_lang = self.config.get('language', 'en').split('-')[0]
            if hint_for_this_run:
                logger.info(f"🎙️ Using STT language hint for this run: '{hint_for_this_run}' (requested by previous command)")
                # DO NOT reset new_stt_hint here. Orchestrator will reset its state *after* getting results.
                # new_stt_hint = None # <--- REMOVED BUG
            else:
                hint_for_this_run = default_stt_lang # Use default if no hint was set for this run
            
            # --- Main Segment Processing Loop (Use determined hint_for_this_run) ---
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
                matched_signal_key = None # Keep track of the key for logging
                text_for_handler = final_full_sanitized_text # Default if no match strips text
                original_text_lower = final_full_sanitized_text.lower()

                # --- Check for Signal Words (using loaded config list) --- 
                for config in self.signal_configs: # Iterate directly over the list
                    signal_phrase_config = config.get('signal_phrase')
                    if not signal_phrase_config:
                        logger.warning(f"Signal config entry missing 'signal_phrase': {config}. Skipping.")
                        continue
                        
                    # Ensure signal_phrase_config is a list for uniform processing
                    phrases_to_check = []
                    if isinstance(signal_phrase_config, list):
                        phrases_to_check = signal_phrase_config
                    elif isinstance(signal_phrase_config, str):
                        phrases_to_check = [signal_phrase_config] # Wrap single string in a list
                    else:
                         logger.warning(f"Signal config 'signal_phrase' has invalid type ({type(signal_phrase_config)}): {config}. Skipping.")
                         continue

                    match_position = config.get('match_position', 'anywhere') 
                    match_found = False
                    matched_phrase_in_list = None # Store the specific phrase that matched
                    current_text_for_handler = final_full_sanitized_text # Reset for each potential match

                    # --- Loop through phrases for this config ---                    
                    for phrase in phrases_to_check:
                         if not phrase: continue # Skip empty strings in list
                         
                         phrase_lower = phrase.lower() # Lowercase for matching
                         signal_len = len(phrase)
                         
                         # --- Matching Logic (applied to each phrase) --- 
                         if match_position == 'start':
                              if original_text_lower.startswith(phrase_lower):
                                 match_found = True
                                 remainder = final_full_sanitized_text[signal_len:]
                                 current_text_for_handler = remainder.lstrip(',.?!;:').strip()
                         elif match_position == 'end':
                              if original_text_lower.endswith(phrase_lower):
                                  match_found = True
                                  remainder = final_full_sanitized_text[:-signal_len]
                                  current_text_for_handler = remainder.rstrip(',.?!;:').strip()
                         elif match_position == 'exact':
                              if final_text_check == phrase_lower:
                                  match_found = True
                                  current_text_for_handler = "" # Exact phrase usually doesn't pass text
                         else: # 'anywhere' (default) - Pass full text for processing
                             if phrase_lower in original_text_lower:
                                 match_found = True
                                 current_text_for_handler = final_full_sanitized_text
                         # ------------------------------------

                         if match_found:
                             matched_phrase_in_list = phrase # Store the phrase that actually matched
                             break # Found a match within this config's phrases, stop checking this config

                    # --- Process if a match was found for this config ---                    
                    if match_found:
                        logger.info(f"🚥 Signal detected: '{matched_phrase_in_list}' (via config '{config.get('name', 'Unnamed')}', Match type: {match_position})")
                        chosen_signal_config = config # Store the matched config dict
                        text_for_handler = current_text_for_handler 
                        break # Found a matching config, stop checking other configs
                
                # --- Perform Action Based on Signal (or Default) ---
                if chosen_signal_config:
                    # Use the matched phrase for context if needed, or config name
                    matched_signal_display = matched_phrase_in_list or chosen_signal_config.get('signal_phrase', 'Unknown')
                    overlay_msg = chosen_signal_config.get('overlay_message', f"🚥 Signal: '{matched_signal_display}'")
                    self.notification_manager.show_message(overlay_msg)
                    
                    action_list = chosen_signal_config.get('action', [])
                    # Use 'text' as the key for consistency with the template placeholder {text}
                    context = {
                        'text': text_for_handler or "", 
                        'clipboard': self.clipboard_manager.get_content() or ""
                    }
                    
                    text_to_paste = None
                    llm_requested = False
                    llm_model_override = None
                    
                    # --- Parse Actions and State Changes --- 
                    for action_item in action_list:
                        if not isinstance(action_item, str):
                            logger.warning(f"Invalid action item type for signal '{matched_signal_display}': {action_item}")
                            continue

                        parts = action_item.split(':', 1)
                        action_type = parts[0]
                        action_value = parts[1] if len(parts) > 1 else None
                        
                        if action_type == "llm":
                            llm_requested = True
                            llm_model_override = action_value # Store override (can be None)
                            logger.info(f"Action 'llm' requested for signal '{matched_signal_display}' (Override: {llm_model_override})")
                        elif action_type == "set_next_stt":
                            if action_value:
                                new_stt_hint = action_value
                                logger.info(f"🎙️ State Change: Setting next STT hint to '{new_stt_hint}' from signal '{matched_signal_display}'.")
                            else:
                                logger.error(f"❌ Invalid state action format for signal '{matched_signal_display}': {action_item}")
                        elif action_type == "set_translation_mode":
                            if action_value:
                                new_translation_mode = action_value
                                logger.info(f"🛂 State Change: Setting translation mode to '{new_translation_mode}' from signal '{matched_signal_display}'.")
                            else:
                                 logger.error(f"❌ Invalid state action format for signal '{matched_signal_display}': {action_item}")
                        # Add elif for other action types here if needed in future
                        # else: 
                        #     logger.warning(f"Unknown action type '{action_type}' for signal '{matched_signal_display}'")

                    # --- Determine Text Output (based ONLY on 'template') --- 
                    template = chosen_signal_config.get('template')
                    if template:
                        formatted_text = None
                        try:
                            formatted_text = template.format(**context)
                            logger.debug(f"Formatted template for signal '{matched_signal_display}': '{formatted_text[:100]}...'")
                        except KeyError as e:
                            logger.error(f"❌ Invalid placeholder {{{e}}} in template for signal '{matched_signal_display}'.")
                        except Exception as e:
                            logger.exception(f"💥 Error formatting template for signal '{matched_signal_display}': {e}")
                            formatted_text = template # Use raw template on formatting error? Or None?
                        
                        # Use the formatted text either for LLM or directly
                        if formatted_text is not None: # Proceed only if formatting was successful (or fallback used)
                            if llm_requested:
                                try:
                                    # --- Pass notification_manager to transform_text --- 
                                    # Notification is now handled *inside* LLMClient helpers
                                    # self.notification_manager.show_message(f"🧠 Calling LLM: {llm_model_override or self.config.get('llm_model') or '???'}")
                                    text_to_paste = self.llm_client.transform_text(
                                        formatted_text, 
                                        notification_manager=self.notification_manager, # <-- Pass it here
                                        model_override=llm_model_override
                                    )
                                except Exception as e:
                                    logger.exception(f"💥 Error during LLM action for signal '{matched_signal_display}': {e}")
                                    text_to_paste = None # Ensure failure results in None
                            else: # Not an LLM request, use the formatted text directly
                                logger.info(f"Using formatted template directly for signal '{matched_signal_display}'.")
                                text_to_paste = formatted_text 
                    else: # No 'template' found
                        logger.warning(f"⚠️ No 'template' key found for signal '{matched_signal_display}'. No text will be generated.")
                        text_to_paste = None

                # --- No Signal Word Found (Default Behavior) ---
                else: 
                    # Default is no action, just passthrough the original text.
                    # REMOVED: Implicit translation based on mode.
                    # effective_text_for_processing = final_full_sanitized_text
                    # if new_translation_mode == "swiss_german":
                    #     logger.info(f"🇨🇭 Mode=SG. Attempting translation for default text via _translate_to_swiss_german: '{effective_text_for_processing}'")
                    #     translated_text = self._translate_to_swiss_german(effective_text_for_processing)
                    #     if translated_text:
                    #          logger.info(f"🇨🇭 Default translation successful: '{translated_text}'")
                    #          effective_text_for_processing = translated_text
                    #     else:
                    #          logger.warning("⚠️ Default translation failed/skipped. Using original text.")
                    text_to_paste = final_full_sanitized_text # Directly assign the original text

            # --- Safety Check (If text is unexpectedly None) ---
            elif text_to_paste is None and final_full_sanitized_text: 
                 logger.warning(f"Text '{final_full_sanitized_text}' resulted in None for pasting unexpectedly after processing.")

        except Exception as e:
            logger.exception(f"💥 Unhandled error in audio processing pipeline: {e}")
            # Ensure state is returned even on error
            return {
                'text_to_paste': None,
                'new_translation_mode': current_translation_mode, # Return original state on error
                'new_stt_hint': current_stt_hint,
                'paste_successful': False
            }
        finally:
            # --- Final Paste --- 
            if text_to_paste:
                logger.info(f"✅ Proceeding to copy and paste via ClipboardManager: '{text_to_paste[:100]}...'")
                paste_successful = self.clipboard_manager.copy_and_paste(text_to_paste) 
            else:
                logger.info("🤷 No valid text to paste (result was None or empty).")
                paste_successful = False

        # --- Return results --- 
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

    # --- NEW Method to Get Signal Phrases ---
    def get_configured_signal_phrases(self):
        """
        Retrieves the list of 'signal_phrase' values from the loaded configuration.

        Returns:
            list[str]: A list of signal phrases configured in signal_config.json.
                       Returns an empty list if no config was loaded or no phrases are defined.
        """
        phrases = []
        if not self.signal_configs:
            logger.warning("⚠️ Signal config not loaded or empty, cannot retrieve phrases.")
            return []
            
        # Iterate directly over the list of config dicts
        for config_data in self.signal_configs:
            signal_phrase_config = config_data.get('signal_phrase')
            
            # Check if this config should be excluded based on action
            should_exclude = any(
                isinstance(action, str) and (
                    # or Check if action contains 'chairman' anywhere in the string
                    action.startswith('stt_language:') or 'chairman' in action
                )
                for action in (config_data.get('action') or [])
            )
            
            if should_exclude:
                 continue # Skip signals that only change state

            # Process phrases if not excluded
            if isinstance(signal_phrase_config, list):
                # Add all non-empty phrases from the list, excluding specific ones
                for phrase in signal_phrase_config:
                    if phrase and isinstance(phrase, str):
                        # --- Add exclusion for specific phrases --- 
                        if phrase.lower() not in ["chairman", "swiss chairman"]:
                            phrases.append(phrase)
                        # -----------------------------------------
                    elif phrase:
                         logger.warning(f"Non-string item found in signal_phrase list: {phrase} in {config_data.get('name', 'Unnamed')}")
            elif isinstance(signal_phrase_config, str) and signal_phrase_config:
                # Add the single non-empty phrase string, excluding specific ones
                # --- Add exclusion for specific phrases --- 
                if signal_phrase_config.lower() not in ["chairman", "swiss chairman"]:
                    phrases.append(signal_phrase_config)
                # -----------------------------------------
            elif signal_phrase_config: # Log if it's neither list nor string but not None/empty
                 logger.warning(f"Signal config '{config_data.get('name', 'Unnamed')}' has invalid type for 'signal_phrase': {type(signal_phrase_config)}")
            # else: Missing or empty signal_phrase, already warned in process_audio potentially
                
        logger.debug(f"Retrieved {len(phrases)} configured signal phrases to display.")
        return phrases

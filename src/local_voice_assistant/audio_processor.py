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
        self.signal_configs = []
        
        # --- Load Signal Config --- 
        try:
            import config as app_config # Import config.py
            import importlib
            importlib.reload(app_config)
            if hasattr(app_config, 'COMMANDS') and isinstance(app_config.COMMANDS, list):
                self.signal_configs = app_config.COMMANDS
                logger.info(f"✅ Loaded {len(self.signal_configs)} signal configurations from config.py")
                # --- Pre-process configs for faster lookup (Optional but good) --- 
                self.commands_by_name = {cfg.get("name"): cfg for cfg in self.signal_configs if cfg.get("name")}
                logger.debug(f"Pre-processed {len(self.commands_by_name)} commands by name.")
                # ----------------------------------------------------------------
            else:
                logger.error("❌ config.py has no 'COMMANDS' list. Signals disabled.")
        except ImportError:
            logger.error("❌ Failed to import config.py. Signals disabled.")
        except Exception as e:
            logger.exception(f"💥 Failed to load signal config from config.py: {e}")
        # ------------------------
        logger.debug("AudioProcessor initialized.")

    def process_audio(self, frames, current_processing_mode, current_stt_hint, default_processing_mode):
        """
        Processes recorded audio frames based on signal words and current mode.
        
        Args:
            frames: A list of audio frames.
            current_processing_mode: The current processing mode ('normal', 'llm', 'de-CH').
            current_stt_hint: The current STT language hint for the next run.
            default_processing_mode: The system's default processing mode (e.g., 'llm').

        Returns:
            A dictionary containing processing results:
            {
                'text_to_paste': str | None,
                'new_processing_mode': str,
                'new_stt_hint': str | None,
                'paste_successful': bool
            }
        """
        logger.info(f"🔄 Starting audio processing (Mode: {current_processing_mode}, Default: {default_processing_mode})...")
        if not frames:
            logger.warning("🤔 Process audio called with no frames.")
            return {
                'text_to_paste': None,
                'new_processing_mode': current_processing_mode,
                'new_stt_hint': current_stt_hint,
                'paste_successful': False
            }
            
        # --- Initialize state for this run --- 
        text_to_paste = None
        paste_successful = False
        # Start with current state, these will be updated by signal actions
        new_processing_mode = current_processing_mode
        new_stt_hint = current_stt_hint
        # This flag is determined *at the end*
        paste_successful = False 
        # --- Add flag to track if ONLY language hint was set by signal ---
        only_language_action = False 
        # ----------------------------------------------------------------

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
        text_for_signal_handler = None # Text remaining after signal phrase (if applicable)
        signal_match_found = False

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

            # --- Initial Filtering --- 
            if final_text_check == "you" or final_text_check == "thank you":
                logger.info("🙅‍♀️ Detected only filter words, skipping.")
                text_to_paste = None # Ensure nothing is pasted
            
            # --- Main Processing Logic --- 
            elif final_full_sanitized_text:
                # --- 1. Check for Signal Word Match FIRST --- 
                original_text_lower = final_full_sanitized_text.lower()
                for config in self.signal_configs:
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
                        signal_match_found = True
                        chosen_signal_config = config # Store the matched config dict
                        text_for_signal_handler = current_text_for_handler 
                        logger.info(f"🚥 Signal detected: '{matched_phrase_in_list}' (Config: '{config.get('name', 'Unnamed')}')")
                        break # Found a matching config, stop checking other configs
                
                # --- 2. Process Based on Match or Mode --- 
                if signal_match_found:
                    # --- 2a. Matched Signal: Execute its actions --- 
                    logger.debug(f"Executing actions for matched signal: {chosen_signal_config.get('name')}")
                    matched_signal_display = matched_phrase_in_list or chosen_signal_config.get('signal_phrase', 'Unknown')
                    overlay_msg = chosen_signal_config.get('overlay_message', f"🚥 Signal: '{matched_signal_display}'")
                    self.notification_manager.show_message(overlay_msg) # Show immediate feedback
                    
                    action_list = chosen_signal_config.get('action', [])
                    context = {
                        'text': text_for_signal_handler or "", 
                        'clipboard': self.clipboard_manager.get_content() or ""
                    }
                    
                    llm_requested_this_turn = False # Action for THIS turn
                    llm_params = {} # Store params like model override
                    mode_set_by_signal = None # Track mode set by action
                    hint_set_by_signal = None # Track hint set by action

                    # --- Parse Actions --- 
                    for action_item in action_list:
                        if not isinstance(action_item, str): continue
                        
                        action_type = action_item
                        action_value = None
                        param_key = None
                        param_value = None
                        
                        # Try splitting by ":" first
                        if ':' in action_item:
                            parts = action_item.split(':', 1)
                            action_type = parts[0]
                            raw_value = parts[1]
                            
                            # Check for param=value format in the value part
                            if '=' in raw_value:
                                param_parts = raw_value.split('=', 1)
                                param_key = param_parts[0]
                                param_value = param_parts[1]
                                # Value for the action itself is considered None if params exist
                                action_value = None 
                            else:
                                # No "=", so the whole part after ":" is the value
                                action_value = raw_value
                        # else: Action is simple, like "llm"

                        # --- Process Parsed Action --- 
                        if action_type == "llm":
                            llm_requested_this_turn = True 
                            if param_key == "model":
                                llm_params['model_override'] = param_value
                                logger.info(f"LLM model override parsed from action: {param_value}")
                            # Add other llm params here if needed
                        elif action_type == "mode":
                            if action_value:
                                new_processing_mode = action_value 
                                mode_set_by_signal = new_processing_mode
                                logger.info(f"🚦 State Change Action: Setting NEXT processing mode to '{new_processing_mode}'.")
                            else: logger.error("Invalid mode action format (needs :value)")
                        elif action_type == "language": 
                             if action_value:
                                 new_stt_hint = action_value
                                 hint_set_by_signal = new_stt_hint # Track hint set
                                 logger.info(f"🎙️ State Change Action: Setting NEXT STT hint to '{new_stt_hint}'.")
                             else: logger.error("Invalid language action format (needs :value)")
                        # Add other actions here
                        
                    # --- Determine final mode/hint to return --- 
                    # Mode only changes if explicitly set
                    if mode_set_by_signal is None:
                        new_processing_mode = current_processing_mode 
                    # Hint only changes if explicitly set 
                    if hint_set_by_signal is None:
                        new_stt_hint = current_stt_hint
                        
                    # --- Generate Text Output (if template exists AND llm requested) --- 
                    template = chosen_signal_config.get('template')
                    if template and llm_requested_this_turn:
                        try:
                            formatted_text_for_llm = template.format(**context)
                            # Use model override from config as base, override with parsed action param if exists
                            final_model_override = llm_params.get('model_override', chosen_signal_config.get('llm_model_override'))
                            logger.info(f"🧠 Calling LLM for signal '{chosen_signal_config.get('name')}' (Model: {final_model_override or 'Default'})...")
                            text_to_paste = self.llm_client.transform_text(
                                formatted_text_for_llm,
                                notification_manager=self.notification_manager,
                                model_override=final_model_override
                            )
                        except Exception as e:
                            logger.exception(f"💥 Error formatting/calling LLM for signal: {e}")
                            text_to_paste = None 
                    elif template and not llm_requested_this_turn:
                        # Template exists but LLM not requested - this case might need refinement.
                        # Should it format and paste directly? Or is template only for LLM?
                        # For now, let's assume template implies LLM is needed, so do nothing if llm action missing.
                        logger.warning(f"Template found for signal '{chosen_signal_config.get('name')}' but no 'llm' action specified. Ignoring template.")
                        text_to_paste = None
                    elif not template and llm_requested_this_turn:
                        # LLM requested but no template? Maybe just pass raw text?
                        logger.warning(f"'llm' action specified for signal '{chosen_signal_config.get('name')}' but no template found. Sending raw text (if any)...")
                        text_to_paste = self.llm_client.transform_text(
                                context['text'], # Send remaining text after signal phrase
                                notification_manager=self.notification_manager,
                                model_override=llm_params.get('model_override') # Use parsed param if exists
                            )
                    else:
                        # No template and no LLM requested = likely just state change
                        logger.info("Signal matched. No template/LLM action. Likely just state change.")
                        text_to_paste = None # Ensure nothing is pasted

                else:
                    # --- 2b. No Signal Matched: Apply Current Mode's Default Behavior --- 
                    logger.info(f"🚫 No signal detected. Applying default behavior for mode: {current_processing_mode}")
                    
                    # --- Handle Specific Modes --- 
                    if current_processing_mode == 'de-CH': # Use locale code
                        logger.info("🇨🇭 Mode = de-CH. Looking up config and calling LLM...")
                        # Use the pre-processed lookup
                        sg_config = self.commands_by_name.get("mode:de-CH") 
                        if sg_config and sg_config.get('template'):
                             # ... (rest of de-CH logic using sg_config) ...
                             template = sg_config.get('template')
                             model_override = sg_config.get('llm_model_override')
                             context = {'text': final_full_sanitized_text, 'clipboard': ''}
                             try:
                                 formatted_text_for_llm = template.format(**context)
                                 text_to_paste = self.llm_client.transform_text(
                                     formatted_text_for_llm,
                                     notification_manager=self.notification_manager,
                                     model_override=model_override
                                 )
                             except Exception as e:
                                 logger.exception("💥 Error formatting/calling LLM for de-CH mode")
                                 text_to_paste = None
                        else:
                             logger.error("❌ Could not find config or template for 'mode:de-CH' to apply mode.")
                             text_to_paste = None
                             
                    # --- Check for "llm" mode --- 
                    elif current_processing_mode == 'llm':
                        # --- Handle LLM Mode --- 
                        logger.info("🧠 Mode = llm. Sending text to LLM chat...")
                        try:
                            prompt_for_llm = f"User said: {final_full_sanitized_text}"
                            logger.debug(f"Formatted prompt for llm mode: {prompt_for_llm[:100]}...")
                            text_to_paste = self.llm_client.transform_text(
                                prompt_for_llm,
                                notification_manager=self.notification_manager
                            )
                        except Exception as e:
                            logger.exception("💥 LLM Error during llm mode processing")
                            text_to_paste = None
                    # -------------------------
                            
                    else: 
                        # --- Default "Normal" Mode (Passthrough) --- 
                        if current_processing_mode != 'normal':
                             logger.warning(f"Unknown processing mode '{current_processing_mode}'. Defaulting to normal passthrough.")
                             
                        logger.info(" Mode = normal (Default). Passing through text.")
                        text_to_paste = final_full_sanitized_text

            # else: final_full_sanitized_text was empty, text_to_paste remains None

        except Exception as e:
            logger.exception(f"💥 Unhandled error in audio processing pipeline: {e}")
            # Ensure state is returned even on error
            return {
                'text_to_paste': None,
                'new_processing_mode': current_processing_mode, # Return original state on error
                'new_stt_hint': current_stt_hint,
                'paste_successful': False
            }

        # --- Final Determination of paste_successful flag --- 
        paste_successful = text_to_paste is not None and text_to_paste != ""
        logger.info(f"🏁 Audio processing finished. Returning: paste_successful={paste_successful}, mode='{new_processing_mode}', hint='{new_stt_hint}'")
        return {
            'text_to_paste': text_to_paste,
            'new_processing_mode': new_processing_mode,
            'new_stt_hint': new_stt_hint,
            'paste_successful': paste_successful
        }
        
    def _sanitize_text(self, text):
        """Performs basic text sanitization."""
        # Using simple replace, consider more robust sanitization if needed.
        return text.replace('ß', 'ss').replace('"', '"').replace("'", "'")

    # --- Method removed, moved to config.py ---
    # def get_configured_signal_phrases(self):
    #     ...
    # --- End removed method ---
 
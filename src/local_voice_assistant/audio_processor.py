import logging
import string
import threading
import json
import os
import time
from typing import List, Tuple, Optional, Dict, Any

# --- Local Imports ---
from .stt import SpeechToText
from .llm_client import LLMClient
from .api_client import NERServiceClient # Assuming ner_service_client is updated
from .notification_manager import NotificationManager
from .clipboard import ClipboardManager
transcription_logger = logging.getLogger('TranscriptionLogger')
from .json_formatter import format_ner_json_custom # <<< Import new formatter >>>
from .signal_detector import find_matching_signal
from .action_parser import parse_actions
from .action_executor import ActionExecutor

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
    def __init__(self, stt, config, notification_manager, clipboard_manager, llm_client, ner_service_client, transcription_logger):
        logger.debug("AudioProcessor initializing...")
        self.stt = stt
        self.config = config
        self.notification_manager = notification_manager
        self.clipboard_manager = clipboard_manager
        self.llm_client = llm_client
        self.ner_service_client = ner_service_client
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

        # <<< Initialize ActionExecutor >>>
        self.action_executor = ActionExecutor(
            config=self.config, # Pass overall config if needed by executor
            llm_client=self.llm_client,
            ner_service_client=self.ner_service_client,
            clipboard_manager=self.clipboard_manager,
            notification_manager=self.notification_manager
        )
        # ------------------------------
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

                # --- Notification Update (Using NotificationManager) ---
                display_text = accumulated_raw_text
                display_text_short = display_text[-100:] if len(display_text) > 100 else display_text
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
                # --- 1. Check for Signal Word Match using new function --- 
                chosen_signal_config, text_for_signal_handler = find_matching_signal(
                    final_full_sanitized_text,
                    self.signal_configs
                )
                signal_match_found = chosen_signal_config is not None
                # <<< REMOVE signal detection loop >>>
                # ----------------------------------------------------------
                
                # --- 2. Process Based on Match or Mode --- 
                if signal_match_found:
                    # --- 2a. Signal Matched: Parse and Execute Actions --- 
                    overlay_msg = chosen_signal_config.get('overlay_message', "Processing signal...")
                    self.notification_manager.show_message(overlay_msg)
                    action_config_list = chosen_signal_config.get('action', [])
                    context = {
                        'text': text_for_signal_handler or "", 
                        'clipboard': self.clipboard_manager.get_content() or ""
                    }
                    parsed_actions = parse_actions(action_config_list)
                    
                    # <<< Call ActionExecutor >>>
                    text_to_paste, paste_successful, new_processing_mode, new_stt_hint = \
                        self.action_executor.execute_actions(
                            parsed_actions=parsed_actions,
                            context=context,
                            chosen_signal_config=chosen_signal_config,
                            current_processing_mode=current_processing_mode,
                            current_stt_hint=current_stt_hint
                        )
                    # <<< REMOVE Action Execution Loop and Logic >>>
                    # --------------------------------------------
                        
                else:
                    # --- 2b. No Signal Matched: Re-introduce Default Mode Logic --- 
                    logger.info(f"🚫 No signal detected. Applying default behavior for mode: {current_processing_mode}")
                    
                    # Reset vars for this path (ActionExecutor didn't run)
                    text_to_paste = None 
                    paste_successful = False 
                    
                    # Apply default logic based on mode
                    if current_processing_mode == 'de-CH':
                        # Find the config for de-CH mode to get template/model
                        # This assumes a command named "mode:de-CH" exists in config.py
                        ch_config = self.commands_by_name.get("mode:de-CH") 
                        if ch_config and ch_config.get('template'):
                             logger.info("🇨🇭 Mode = de-CH. Calling LLM with specific config...")
                             template = ch_config.get('template')
                             model_override = ch_config.get('llm_model_override')
                             # Note: Default modes might not have access to clipboard context easily
                             context = {'text': final_full_sanitized_text, 'clipboard': ''} 
                             try:
                                 prompt = template.format(**context)
                                 text_to_paste = self.llm_client.transform_text(prompt, self.notification_manager, model_override=model_override)
                             except Exception as e:
                                 logger.exception("💥 Error formatting/calling LLM for de-CH mode")
                        else:
                             logger.error("❌ Could not find config or template for 'mode:de-CH' to apply default behavior.")
                             
                    elif current_processing_mode == 'llm':
                        logger.info("🧠 Mode = llm. Sending text to default LLM chat...")
                        try:
                            prompt_for_llm = f"User said: {final_full_sanitized_text}" 
                            text_to_paste = self.llm_client.transform_text(
                                prompt_for_llm,
                                notification_manager=self.notification_manager
                            )
                        except Exception as e:
                            logger.exception("💥 LLM Error during llm mode processing")
                            
                    else: # Default "Normal" Mode (Passthrough)
                        if current_processing_mode != 'normal':
                             logger.warning(f"Unknown processing mode '{current_processing_mode}'. Defaulting to normal passthrough.")
                        logger.info(" Mode = normal (Default). Passing through text.")
                        text_to_paste = final_full_sanitized_text

                    # Determine success for default modes
                    if text_to_paste is not None and text_to_paste != "": paste_successful = True
                    logger.debug(f"[DEBUG] Default Mode Handler: paste_successful={paste_successful}")
                    # Mode/Hint remain unchanged if no signal matched
                    new_processing_mode = current_processing_mode
                    new_stt_hint = current_stt_hint 
                    # --- END Re-introduced Default Mode Logic ---

            # else: final_full_sanitized_text was empty or filtered out
                     
        except Exception as e:
            logger.exception(f"💥 Unhandled error in audio processing pipeline: {e}")
            text_to_paste = None # Ensure no paste on error
            paste_successful = False # Ensure no paste on error
            logger.debug(f"[DEBUG] Exception Handler: paste_successful set to False.")
            # Return original state on error
            return {
                'text_to_paste': None,
                'new_processing_mode': current_processing_mode, # Return original state on error
                'new_stt_hint': current_stt_hint,
                'paste_successful': False
            }

        # --- Return results --- 
        # Values determined within the specific action/default logic should persist
        # <<< ADD Final DEBUG Log for text_to_paste >>>
        logger.debug(f"[DEBUG] text_to_paste value before return: '{text_to_paste}'")
        logger.debug(f"[DEBUG] Final Value: paste_successful={paste_successful} before return.")
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
 
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
    def __init__(self,
                 stt: SpeechToText,
                 notification_manager: NotificationManager,
                 clipboard_manager: ClipboardManager,
                 llm_client: LLMClient,
                 ner_service_client: NERServiceClient,
                 transcription_logger,
                 initial_language: str # Add initial language param
                 ):
        logger.debug("AudioProcessor initializing...")
        self.stt = stt
        self.notification_manager = notification_manager
        self.clipboard_manager = clipboard_manager
        self.llm_client = llm_client
        self.ner_service_client = ner_service_client
        self.transcription_logger = transcription_logger
        self.default_stt_language = initial_language.split('-')[0] if initial_language else 'en' # Store default 2-letter code
        logger.info(f"AudioProcessor initialized with default STT language: {self.default_stt_language}")
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
            # --- Determine STT Hint for THIS run (Use stored default) --- 
            hint_for_this_run = current_stt_hint # Start with hint passed from Orchestrator state
            # Use the default stored in __init__ instead of reading config
            # default_stt_lang = self.config.get('language', 'en').split('-')[0] # <-- REMOVE config read
            if not hint_for_this_run: # If no hint was set for *this* specific run
                hint_for_this_run = self.default_stt_language # Use the instance default
            
            logger.info(f"🎙️ Using STT language hint for this run: '{hint_for_this_run}'")
            # ----------------------------------------------------------
            
            # --- Main Segment Processing Loop --- 
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
                    
                    # Use the correct method name: execute_actions
                    action_results = self.action_executor.execute_actions(parsed_actions, context, chosen_signal_config)
                    
                    # Update state based on action results
                    new_processing_mode = action_results.get('new_mode', new_processing_mode)
                    new_stt_hint = action_results.get('new_stt_hint', new_stt_hint)
                    text_to_paste = action_results.get('text_to_paste', text_to_paste)
                    paste_successful = action_results.get('paste_successful', paste_successful)
                    # --- Update language action flag ---
                    only_language_action = action_results.get('only_language_action', False)
                    # -----------------------------------

                else:
                    # --- 2b. No Signal Match: Process based on current_processing_mode --- 
                    if current_processing_mode == 'normal':
                        logger.info("No signal detected, mode is 'normal'. Pasting raw text.")
                        text_to_paste = final_full_sanitized_text
                        paste_successful = True # Assume success if pasting raw text
                    elif current_processing_mode == 'llm':
                        logger.info("No signal detected, mode is 'llm'. Sending to default LLM.")
                        self.notification_manager.show_message("🧠 Sending to LLM...")
                        # Use llm_client.transform_text directly (no specific template)
                        transformed_text = self.llm_client.transform_text(
                            prompt=final_full_sanitized_text,
                            notification_manager=self.notification_manager
                        )
                        text_to_paste = transformed_text
                        paste_successful = text_to_paste is not None
                    elif current_processing_mode == 'de-CH':
                        logger.info("No signal detected, mode is 'de-CH'. Using translation template.")
                        self.notification_manager.show_message("🇨🇭 Translating...")
                        # Retrieve the specific command config for 'de-CH'
                        translation_command_config = self.commands_by_name.get('mode:de-CH')
                        if translation_command_config and translation_command_config.get('template'):
                            context = {'text': final_full_sanitized_text}
                            prompt = translation_command_config['template'].format(**context)
                            model_override = translation_command_config.get('llm_model_override')
                            transformed_text = self.llm_client.transform_text(
                                prompt=prompt,
                                notification_manager=self.notification_manager,
                                model_override=model_override
                            )
                            text_to_paste = transformed_text
                            paste_successful = text_to_paste is not None
                        else:
                            logger.error("Could not find 'mode:de-CH' command config or template for translation.")
                            text_to_paste = f"Error: Config for mode '{current_processing_mode}' missing."
                            paste_successful = False
                    else:
                        logger.warning(f"Unknown processing mode '{current_processing_mode}' and no signal matched.")
                        text_to_paste = f"Error: Unknown mode '{current_processing_mode}'"
                        paste_successful = False
                        new_processing_mode = default_processing_mode # Revert to default on error

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
 
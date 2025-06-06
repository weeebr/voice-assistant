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
                 ner_service_client: NERServiceClient = None,
                 transcription_logger=None,
                 initial_language: str = None,
                 sample_rate: int = 16000
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

    def process_audio(
        self,
        frames,
        current_processing_mode,
        current_stt_hint,
        default_processing_mode,
        original_frames=None  # Add parameter for original frames
    ):
        """
        Process audio frames and return results.

        Args:
            frames: Audio frames to process
            current_processing_mode: Current processing mode
            current_stt_hint: Current STT language hint
            default_processing_mode: Default processing mode
            original_frames: Original audio frames for potential re-running STT

        Returns:
            Dict containing:
            {
                'text_to_paste': str or None,
                'new_processing_mode': str,
                'new_stt_hint': str or None,
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

            # --- Apply output cleaning for filter phrases ---
            cleaned_text = self.clipboard_manager.clean_output_text(final_full_sanitized_text)
            if not cleaned_text:
                logger.info("🙅‍♀️ Detected only filter words or empty after cleaning, skipping.")
                text_to_paste = None
            # --- Main Processing Logic --- 
            elif cleaned_text:
                # --- 1. Check for Signal Word Match using new function --- 
                chosen_signal_config, text_for_signal_handler = find_matching_signal(
                    cleaned_text,
                    self.signal_configs
                )
                logger.debug(f"[DEBUG] Signal detection: chosen_signal_config={chosen_signal_config}, text_for_signal_handler='{text_for_signal_handler}'")
                signal_match_found = chosen_signal_config is not None
                # <<< REMOVE signal detection loop >>>
                # ----------------------------------------------------------
                # --- 2. Process Based on Match or Mode --- 
                if signal_match_found:
                    logger.debug(f"[DEBUG] Before actions: text_for_signal_handler='{text_for_signal_handler}'")
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
                    logger.debug(f"[DEBUG] After actions: text_for_signal_handler='{text_for_signal_handler}', action_results={action_results}")
                    
                    # --- Get new state for THIS run ---
                    new_processing_mode = action_results.get('new_mode', new_processing_mode)
                    new_stt_hint = action_results.get('new_stt_hint', new_stt_hint)
                    only_language_action = action_results.get('only_language_action', False)
                    
                    # --- If we have a new hint, re-run STT immediately ---
                    if new_stt_hint and new_stt_hint != current_stt_hint:
                        logger.info(f"🔄 Re-running STT with new hint: '{new_stt_hint}'")
                        try:
                            # Re-run STT on the original frames with the new hint
                            segment_generator = self.stt.transcribe(frames, language=new_stt_hint)
                            all_segments = []
                            for segment in segment_generator:
                                all_segments.append(segment)
                            
                            # Get the full text with new hint
                            full_text = " ".join(segment.text.strip() for segment in all_segments)
                            logger.info(f"📝 Re-transcribed with new hint: '{full_text}'")
                            
                            # Always strip the signal word from the re-transcribed text
                            signal_word = chosen_signal_config.get('signal_phrase', [''])[0].lower()
                            signal_pos = full_text.lower().find(signal_word)
                            if signal_pos != -1:
                                # Get text after signal word and clean it
                                remainder_text = full_text[signal_pos + len(signal_word):].strip()
                                # Remove any leading punctuation or whitespace
                                remainder_text = remainder_text.lstrip(',.?!;: ')
                                logger.info(f"📝 After stripping signal word: '{remainder_text}'")
                                cleaned_text = self.clipboard_manager.clean_output_text(remainder_text)
                            else:
                                # If signal word not found in re-transcribed text, use original text
                                logger.warning(f"Signal word '{signal_word}' not found in re-transcribed text, using original text")
                                cleaned_text = self.clipboard_manager.clean_output_text(full_text.strip())
                            
                            if cleaned_text:
                                if new_processing_mode == 'normal':
                                    text_to_paste = cleaned_text
                                    paste_successful = True
                                elif new_processing_mode == 'llm':
                                    self.notification_manager.show_message("🧠 Sending to LLM...")
                                    transformed_text = self.llm_client.transform_text(
                                        prompt=cleaned_text,
                                        notification_manager=self.notification_manager
                                    )
                                    text_to_paste = transformed_text
                                    paste_successful = text_to_paste is not None
                                elif new_processing_mode == 'de-CH':
                                    self.notification_manager.show_message("🇨🇭 Translating...")
                                    translation_command_config = self.commands_by_name.get('mode:de-CH')
                                    if translation_command_config and translation_command_config.get('template'):
                                        context = {'text': cleaned_text}
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
                                        text_to_paste = f"Error: Config for mode '{new_processing_mode}' missing."
                                        paste_successful = False
                                else:
                                    logger.warning(f"Unknown processing mode '{new_processing_mode}'.")
                                    text_to_paste = f"Error: Unknown mode '{new_processing_mode}'"
                                    paste_successful = False
                            else:
                                logger.info("🙅‍♀️ No text after cleaning, skipping output.")
                                text_to_paste = None
                                paste_successful = False
                        except Exception as e:
                            logger.error(f"Failed to re-run STT with new hint: {e}")
                            text_to_paste = None
                            paste_successful = False
                    else:
                        # No new hint, process as before
                        if text_for_signal_handler:
                            cleaned_text = self.clipboard_manager.clean_output_text(text_for_signal_handler.strip())
                            if cleaned_text:
                                if new_processing_mode == 'normal':
                                    text_to_paste = cleaned_text
                                    paste_successful = True
                                elif new_processing_mode == 'llm':
                                    self.notification_manager.show_message("🧠 Sending to LLM...")
                                    transformed_text = self.llm_client.transform_text(
                                        prompt=cleaned_text,
                                        notification_manager=self.notification_manager
                                    )
                                    text_to_paste = transformed_text
                                    paste_successful = text_to_paste is not None
                                elif new_processing_mode == 'de-CH':
                                    self.notification_manager.show_message("🇨🇭 Translating...")
                                    translation_command_config = self.commands_by_name.get('mode:de-CH')
                                    if translation_command_config and translation_command_config.get('template'):
                                        context = {'text': cleaned_text}
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
                                        text_to_paste = f"Error: Config for mode '{new_processing_mode}' missing."
                                        paste_successful = False
                                else:
                                    logger.warning(f"Unknown processing mode '{new_processing_mode}'.")
                                    text_to_paste = f"Error: Unknown mode '{new_processing_mode}'"
                                    paste_successful = False
                            else:
                                logger.info("🙅‍♀️ No text after cleaning, skipping output.")
                                text_to_paste = None
                                paste_successful = False
                        else:
                            logger.info("🙅‍♀️ No remaining text after signal, skipping output.")
                            text_to_paste = None
                            paste_successful = False
                else:
                    # No signal word found, process in current mode
                    if current_processing_mode == 'normal':
                        text_to_paste = cleaned_text
                        paste_successful = True
                    elif current_processing_mode == 'llm':
                        self.notification_manager.show_message("🧠 Sending to LLM...")
                        transformed_text = self.llm_client.transform_text(
                            prompt=cleaned_text,
                            notification_manager=self.notification_manager
                        )
                        text_to_paste = transformed_text
                        paste_successful = text_to_paste is not None
                    elif current_processing_mode == 'de-CH':
                        self.notification_manager.show_message("🇨🇭 Translating...")
                        translation_command_config = self.commands_by_name.get('mode:de-CH')
                        if translation_command_config and translation_command_config.get('template'):
                            context = {'text': cleaned_text}
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
                        logger.warning(f"Unknown processing mode '{current_processing_mode}'.")
                        text_to_paste = f"Error: Unknown mode '{current_processing_mode}'"
                        paste_successful = False
                
                # Return early since we've handled the remainder with new mode/hint
                logger.debug(f"[DEBUG] text_to_paste value before return: '{text_to_paste}'")
                logger.debug(f"[DEBUG] Final Value: paste_successful={paste_successful} before return.")
                logger.info(f"🏁 Audio processing finished. Returning: paste_successful={paste_successful}, mode='{new_processing_mode}', hint='{new_stt_hint}'")
                return {
                    'text_to_paste': text_to_paste,
                    'new_processing_mode': new_processing_mode,
                    'new_stt_hint': new_stt_hint,
                    'paste_successful': paste_successful 
                }
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
 
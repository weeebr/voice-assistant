"""Executes parsed actions based on detected signals."""
import logging
from typing import List, Dict, Tuple, Optional, Any

# Import necessary components used by actions
from .llm_client import LLMClient
from .api_client import NERServiceClient
from .clipboard import ClipboardManager
from .json_formatter import format_ner_json_custom

logger = logging.getLogger(__name__)

class ActionExecutor:
    def __init__(self, 
                 # config: Dict[str, Any], # <-- REMOVE unused config param
                 llm_client: LLMClient, 
                 ner_service_client: NERServiceClient, 
                 clipboard_manager: ClipboardManager,
                 notification_manager: Any):
        """Initializes the ActionExecutor with necessary dependencies."""
        # self.config = config # <-- REMOVE unused assignment
        self.llm_client = llm_client
        self.ner_service_client = ner_service_client
        self.clipboard_manager = clipboard_manager
        self.notification_manager = notification_manager 
        logger.debug("ActionExecutor initialized.")

    def execute_actions(
        self,
        parsed_actions: List[Dict[str, Any]], 
        context: Dict[str, Any], 
        chosen_signal_config: Dict[str, Any],
        # Remove unused parameters if they truly aren't needed
        # current_processing_mode: str, 
        # current_stt_hint: Optional[str]
    ) -> Dict[str, Any]: # Return a dictionary for clarity
        """
        Executes a list of parsed actions and determines the output and state changes.

        Args:
            parsed_actions: List of parsed action dictionaries from ActionParser.
            context: Dictionary containing 'text' (remainder) and 'clipboard'.
            chosen_signal_config: The configuration dictionary of the matched signal.

        Returns:
            A dictionary containing results and state changes:
            {
                'text_to_paste': str | None,
                'paste_successful': bool,
                'new_mode': str | None,        # Only present if mode changed
                'new_stt_hint': str | None,    # Only present if hint changed
                'only_language_action': bool # True if only language hint was set
            }
        """
        text_to_paste = None
        paste_successful = False
        # Store changes, don't assume defaults from parameters
        new_processing_mode = None 
        new_stt_hint = None
        only_language_action = False # Track if ONLY hint changed
        
        llm_params = {} # Specific params for LLM call within this execution

        logger.debug(f"Executing {len(parsed_actions)} parsed actions...")

        action_types_executed = set()

        for parsed_action in parsed_actions:
            action_type = parsed_action.get('type')
            action_value = parsed_action.get('value')
            params = parsed_action.get('params', {})
            
            if not action_type: continue
            action_types_executed.add(action_type)

            # --- Action Execution Logic (Refined) --- 
            if action_type == "llm":
                logger.info(f"🎬 Executing Action: {action_type}")
                if "model" in params: llm_params['model_override'] = params["model"]
                template = chosen_signal_config.get('template')
                prompt = None
                text_for_signal_handler = context.get('text', '') 
                if template:
                    try: prompt = template.format(**context)
                    except Exception as e: logger.warning(f"LLM template error: {e}")
                elif text_for_signal_handler: prompt = text_for_signal_handler
                
                if prompt: 
                    model_override = llm_params.get('model_override') 
                    text_to_paste = self.llm_client.transform_text(prompt, self.notification_manager, model_override=model_override)
                    paste_successful = bool(text_to_paste)
                else: 
                    logger.warning("LLM action requested but no valid prompt generated (no template/text).")
                    paste_successful = False

            elif action_type == "mode":
                logger.info(f"🎬 Executing Action: {action_type}:{action_value}")
                if action_value:
                    new_processing_mode = action_value # Store the mode change
                    logger.info(f"🚦 State Change: NEXT mode requested='{new_processing_mode}'")
                else: logger.error("Invalid mode action: needs value (e.g., mode:llm)")
            
            elif action_type == "language": 
                 logger.info(f"🎬 Executing Action: {action_type}:{action_value}")
                 if action_value:
                     new_stt_hint = action_value # Store the hint change
                     logger.info(f"🎙️ State Change: NEXT STT hint requested='{new_stt_hint}'")
                 else: logger.error("Invalid language action: needs value (e.g., language:de-DE)")
            
            elif action_type == "process_template":
                logger.info(f"🎬 Executing Action: {action_type}")
                template_text = chosen_signal_config.get('template')
                if template_text:
                    try: 
                        text_to_paste = template_text.format(**context)
                        paste_successful = True
                    except Exception as e: 
                        logger.warning(f"Template formatting error: {e}")
                        text_to_paste = f"Error: Template formatting failed ({e})" 
                        paste_successful = False
                else: 
                    logger.warning(f"process_template action requires 'template' in config.")
                    text_to_paste = "Error: process_template action missing template."
                    paste_successful = False
                    
            elif action_type == "ner_extract":
                logger.info(f"🎬 Executing Action: {action_type} with params {params}")
                ner_error = None # Store potential errors
                types_input_str = ""
                
                if params.get("types_source") == "spoken":
                    types_input_str = context.get('text', '').strip().rstrip('.,!?;:') 
                    if not types_input_str: ner_error = "No types after signal."
                elif "types" in params:
                    types_input_str = params["types"]
                else:
                    ner_error = "Missing NER types config."
                
                input_text = None
                if not ner_error:
                    input_template = chosen_signal_config.get("template")
                    if input_template:
                        try: input_text = input_template.format(**context)
                        except Exception as e: ner_error = f"Template error ({e})."
                    else: 
                        input_text = self.clipboard_manager.get_content()
                        if input_text is None: ner_error = "No clipboard."
                        elif not input_text.strip(): ner_error = "Clipboard empty."

                if not ner_error and input_text is not None:
                    try: 
                        ner_threshold = float(params.get('threshold', 0.5)) 
                        ner_result_dict = self.ner_service_client.extract_and_format_entities(
                            text=input_text, types_input=types_input_str, threshold=ner_threshold)
                        text_to_paste = format_ner_json_custom(ner_result_dict)
                        paste_successful = "error" not in ner_result_dict 
                    except Exception as e:
                        logger.exception(f"🚨 Error during NER call/format: {e}")
                        ner_error = "NER processing error."
                        
                # Handle final result based on error state
                if ner_error:
                     text_to_paste = format_ner_json_custom({"error": ner_error})
                     paste_successful = False
                elif text_to_paste is None: # Should have text if no error
                     logger.warning("NER action finished without error but no text generated.")
                     text_to_paste = format_ner_json_custom({"error": "Unknown NER failure."})
                     paste_successful = False
            
            elif action_type == "speak":
                logger.info(f"🎬 Executing Action: {action_type}")
                # Support language/model selection via action_value (e.g., 'speak:en')
                lang = action_value or "de"
                # Map language to model (expand as needed)
                model_map = {
                    "de": "tts_models/de/thorsten/tacotron2-DDC",
                    "en": "tts_models/en/ljspeech/tacotron2-DDC",
                    # Add more mappings as needed
                }
                model = model_map.get(lang, model_map["de"])
                paste_successful = False  # Always False for TTS-only
                text_to_paste = None  # No text to paste, just TTS
            
            # ... other actions ...

        # --- Determine if only language hint was set --- 
        action_types_executed.discard("language") # Ignore language for this check
        if new_stt_hint is not None and not action_types_executed: # If hint changed AND no other actions ran
            only_language_action = True
        # -----------------------------------------------

        logger.debug(f"Finished executing actions. Result: paste={paste_successful}, mode_req={new_processing_mode}, hint_req={new_stt_hint}, only_lang={only_language_action}")
        
        # --- Return dictionary of results/state changes --- 
        results = {
            'text_to_paste': text_to_paste,
            'paste_successful': paste_successful,
            'only_language_action': only_language_action
        }
        if new_processing_mode is not None:
            results['new_mode'] = new_processing_mode
        if new_stt_hint is not None:
            results['new_stt_hint'] = new_stt_hint
            
        return results

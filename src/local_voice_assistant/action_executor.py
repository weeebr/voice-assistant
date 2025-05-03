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
                 config: Dict[str, Any],
                 llm_client: LLMClient, 
                 ner_service_client: NERServiceClient, 
                 clipboard_manager: ClipboardManager,
                 notification_manager: Any):
        """Initializes the ActionExecutor with necessary dependencies."""
        self.config = config # Overall config if needed
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
        current_processing_mode: str,
        current_stt_hint: Optional[str]
    ) -> Tuple[Optional[str], bool, str, Optional[str]]:
        """
        Executes a list of parsed actions and determines the output.

        Args:
            parsed_actions: List of parsed action dictionaries from ActionParser.
            context: Dictionary containing 'text' (remainder) and 'clipboard'.
            chosen_signal_config: The configuration dictionary of the matched signal.
            current_processing_mode: The processing mode active when the signal was detected.
            current_stt_hint: The STT hint active when the signal was detected.

        Returns:
            A tuple containing:
            - text_to_paste: The final text result, if any.
            - paste_successful: Boolean indicating if pasting should occur.
            - new_processing_mode: The potentially updated processing mode for the next cycle.
            - new_stt_hint: The potentially updated STT hint for the next cycle.
        """
        text_to_paste = None
        paste_successful = False
        # Start with current state, updated by actions
        new_processing_mode = current_processing_mode 
        new_stt_hint = current_stt_hint
        llm_params = {} # Specific params for LLM call within this execution

        logger.debug(f"Executing {len(parsed_actions)} parsed actions...")

        for parsed_action in parsed_actions:
            action_type = parsed_action.get('type')
            action_value = parsed_action.get('value')
            params = parsed_action.get('params', {})
            
            if not action_type: continue

            # --- Action Execution Logic --- 
            if action_type == "llm":
                logger.info(f"🎬 Executing Action: {action_type}")
                if "model" in params: llm_params['model_override'] = params["model"]
                template = chosen_signal_config.get('template')
                prompt = None
                # Use handler text from context if available
                text_for_signal_handler = context.get('text', '') 
                if template:
                    try: prompt = template.format(**context)
                    except Exception as e: logger.warning(f"LLM template error: {e}")
                elif text_for_signal_handler: prompt = text_for_signal_handler
                
                if prompt: 
                    model_override = llm_params.get('model_override') 
                    # Assuming transform_text handles internal errors and returns None/str
                    text_to_paste = self.llm_client.transform_text(prompt, self.notification_manager, model_override=model_override)
                    paste_successful = bool(text_to_paste)
                    logger.debug(f"[DEBUG] LLM Action Result: paste_successful={paste_successful}")
                else: 
                    logger.warning("LLM action requested but no valid prompt generated (no template/text).")
                    paste_successful = False

            elif action_type == "mode":
                logger.info(f"🎬 Executing Action: {action_type}:{action_value}")
                if action_value:
                    new_processing_mode = action_value
                    logger.info(f"🚦 State Change: NEXT mode='{new_processing_mode}'")
                else: logger.error("Invalid mode action: needs value (e.g., mode:llm)")
            
            elif action_type == "language": 
                 logger.info(f"🎬 Executing Action: {action_type}:{action_value}")
                 if action_value:
                     new_stt_hint = action_value
                     logger.info(f"🎙️ State Change: NEXT STT hint='{new_stt_hint}'")
                 else: logger.error("Invalid language action: needs value (e.g., language:de-DE)")
            
            elif action_type == "process_template":
                logger.info(f"🎬 Executing Action: {action_type}")
                template_text = chosen_signal_config.get('template')
                if template_text:
                    try: 
                        text_to_paste = template_text.format(**context)
                        paste_successful = True
                        logger.debug(f"[DEBUG] Template Action Result: paste_successful={paste_successful}")
                    except Exception as e: 
                        logger.warning(f"Template formatting error: {e}")
                        text_to_paste = f"Error: Template formatting failed ({e})" # Provide error in output
                        paste_successful = False
                else: 
                    logger.warning(f"process_template action requires 'template' in config.")
                    text_to_paste = "Error: process_template action missing template."
                    paste_successful = False
                    
            elif action_type == "ner_extract":
                logger.info(f"🎬 Executing Action: {action_type} with params {params}")
                types_input_str = ""
                # Determine types string based on params
                if params.get("types_source") == "spoken":
                    types_input_str = context.get('text', '').strip().rstrip('.,!?;:') 
                    if not types_input_str: text_to_paste = format_ner_json_custom({"error": "No types after signal."}) 
                elif "types" in params:
                    types_input_str = params["types"]
                else:
                    text_to_paste = format_ner_json_custom({"error": "Missing NER types config."})
                
                # Proceed if types are valid so far
                if types_input_str and text_to_paste is None: 
                    input_text = None
                    input_template = chosen_signal_config.get("template")
                    if input_template: # Get text from template if provided
                        try: input_text = input_template.format(**context)
                        except Exception as e: text_to_paste = format_ner_json_custom({"error": f"Template error ({e})."})
                    else: # Default to clipboard if no template
                        input_text = self.clipboard_manager.get_content()
                        if input_text is None: text_to_paste = format_ner_json_custom({"error": "No clipboard."})
                        elif not input_text.strip(): text_to_paste = format_ner_json_custom({"error": "Clipboard empty."})
                    
                    # Proceed if input text is valid so far
                    if input_text is not None and text_to_paste is None: 
                        try: 
                            ner_threshold = float(params.get('threshold', 0.5)) 
                            ner_result_dict = self.ner_service_client.extract_and_format_entities(
                                text=input_text, types_input=types_input_str, threshold=ner_threshold)
                            
                            # Format result and set final state
                            text_to_paste = format_ner_json_custom(ner_result_dict)
                            paste_successful = "error" not in ner_result_dict 
                            logger.debug(f"[DEBUG] NER Action Result: paste_successful={paste_successful}")
                        except Exception as e:
                            logger.exception(f"🚨 Error during NER call/format: {e}")
                            text_to_paste = format_ner_json_custom({"error": "NER processing error."})
                            paste_successful = False
                
                # If any error occurred setting text_to_paste, ensure failure state
                if text_to_paste is not None and "error" in text_to_paste.lower():
                    paste_successful = False
                elif text_to_paste is None and not paste_successful: # Ensure failure if no text AND not already success
                     paste_successful = False 
                     # Might set a default error if text is None here?
                     # text_to_paste = format_ner_json_custom({"error": "Unknown NER action failure."}) 
                
                # End ner_extract
            
            # ... other actions ...
            
            # --- IMPORTANT: Allow only ONE output-generating action? ---
            # If multiple actions (e.g., ner_extract AND process_template) are in config,
            # the last one to run will determine text_to_paste/paste_successful.
            # Decide if this is desired behavior or if we should break after the first output action.
            # For now, we let the last one win.
            # ------------------------------------------------------------

        logger.debug(f"Finished executing actions. Result: paste={paste_successful}, mode={new_processing_mode}, hint={new_stt_hint}")
        return text_to_paste, paste_successful, new_processing_mode, new_stt_hint 

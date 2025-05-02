import logging

# Get a logger instance (assuming orchestrator might configure the root logger)
# Alternatively, configure a specific logger here if needed.
logger = logging.getLogger(__name__)

# --- Shared Handler Functions ---

# Handler for setting SG mode (optional?) and TRANSLATING the remainder via LLM
def _handle_set_sg_mode_and_translate(self_ref, remaining_text):
    logger.debug("Executing shared '_handle_set_sg_mode_and_translate'")
    # Refined prompt: Less restrictive, clearly labels input.
    prompt = (
        f"Please translate the following text into Swiss German (Schweizerdeutsch). "
        f"Input Text: {remaining_text}"
        # Removed the potentially problematic "providing ONLY the translation" part.
    )
    if self_ref.overlay: self_ref.overlay.show_message("🧠 Translating to SG...")
    # Optionally set the mode if we want future default translations?
    # self_ref.translation_mode = "swiss_german" 
    return self_ref._get_llm_transformation(prompt)

# Handler for passthrough (used by English command)
def _handle_passthrough(self_ref, remaining_text):
    logger.debug("Executing '_handle_passthrough' handler")
    return remaining_text

# --- Signal Word Configuration ---
# Defines actions triggered by keywords or exact phrases.
# 'signal_phrase': The text to match against.
# 'match_position': 'exact', 'start', 'anywhere' (default), 'end'.
# 'action': 
#    'transform': Apply handler function to remainder.
#    'set_mode': Set self.translation_mode (for SG translation) for future use.
#    'set_next_stt': Set language hint ONLY for the *next* transcription.
#    'set_next_stt_and_passthrough': Set hint for next AND paste remainder now.

folders_to_ignore = [".git", "venv", "node_modules"]
folders_to_ignore_string = ' '.join([f"-o -path {folder}" for folder in folders_to_ignore])
# Corrected: Use {{}} for literal braces in f-string for find command
find_command = f"`find . \( {folders_to_ignore_string} \) -prune -o -type f -exec wc -l {{}} +`"

SIGNAL_WORD_CONFIG = {
    # == State Setting Commands (Exact Match Only - For NEXT utterance) ==
    "swiss_german_mode_only": {
        "signal_phrase": "swiss german", 
        "match_position": "exact",
        "action": "set_mode", # Still sets persistent translation mode
        "mode_value": "swiss_german",
        "overlay_message": "Mode: 🇨🇭"
    },
    "german_stt_only": { 
        "signal_phrase": "german",
        "match_position": "exact", 
        "action": "set_next_stt", # SET NEXT ONLY
        "stt_language_value": "de",
        "overlay_message": "Mode: 🇩🇪"
    },
    "english_stt_only": { 
        "signal_phrase": "english",
        "match_position": "exact", 
        "action": "set_next_stt", # SET NEXT ONLY
        "stt_language_value": "en",
        "overlay_message": "Mode: 🇬🇧"
    },
    
    # == Text Transformation Keywords (Operate on transcribed text) ==
    "big_files_command": { 
        "signal_phrase": "big files",
        "match_position": "start", 
        "action": "transform",    
        # No LLM needed, clipboard not needed
        "handler": lambda llm_client, clipboard_manager, recorded_text: f"""Use the following command to find our largest files: `{find_command}`. Then, start with the largest files and refactor our codebase enforcing:
- to not lose or break existing logic
- to have a well-organized project structure, following best practise of the current tech stack
- to have no DRY violations, no unused code, no unused imports
- all files are atomic and serve a single purpose
- all files to not have more than 300 lines of code"""
    },
    "short_summary_command": {
        # NOTE: The signal phrase was "fix" above, which seems wrong for summarize.
        # Changed to "summarize". Please verify.
        "signal_phrase": "short", 
        "match_position": "start", 
        "action": "transform",
        # Use LLMClient, also gets clipboard content
        "handler": lambda llm_client, clipboard_manager, recorded_text: llm_client.transform_text(
            f"Summarize the following text in bullet points using mostly keywords or very short phrases: {clipboard_manager.get_content()}", # Use clipboard_manager
            # Example: Override to a faster model for summarization if desired
            # model_override="claude-3-haiku-20240307" 
        )
    }
}

# --- Define Handlers Referenced Above ---

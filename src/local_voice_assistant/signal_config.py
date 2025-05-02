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
    "fix_command": { 
        "signal_phrase": "fix",
        "match_position": "start", 
        "action": "transform",    
        "handler": lambda self_ref, recorded_text: (
            logger.debug("Executing 'fix_command' lambda handler"),
            (self_ref.overlay.show_message("🧠 Asking Fix Expert...") if self_ref.overlay else None),
            self_ref._get_llm_transformation(f"Act as a world-renowned expert... Task: {recorded_text}")
        )
    },
    "debug_command": {
        "signal_phrase": "debug",
        "match_position": "anywhere", 
        "action": "transform",
        "handler": lambda self_ref, recorded_text: (
            logger.debug("Executing 'debug_command' lambda handler"),
            (self_ref.overlay.show_message("🧠 Asking Debug Expert...") if self_ref.overlay else None),
            self_ref._get_llm_transformation(f"Act as a senior software engineer... Issue: {recorded_text}")
        )
    },
    "email_command": {
        "signal_phrase": "email",
        "action": "transform",
        "handler": lambda self_ref, recorded_text: (
            logger.debug("Executing 'email_command' lambda handler"),
            f"Subject: \n\nBody:\n{recorded_text}"
        )
    },
    "reply_command": {
        "signal_phrase": "reply",
        "match_position": "start", 
        "action": "transform",
        "handler": lambda self_ref, recorded_text: (
            logger.debug("Executing 'reply_command' lambda handler"),
            f"Subject: Re: \n\n{recorded_text}"
        )
    },
    "explain_command": {
        "signal_phrase": "explain",
        "action": "transform",
        "handler": lambda self_ref, recorded_text: (
            logger.debug("Executing 'explain_command' lambda handler"),
            (self_ref.overlay.show_message("🧠 Asking Explainer...") if self_ref.overlay else None),
            self_ref._get_llm_transformation(f"Explain the following concept clearly... Topic: {recorded_text}")
        )
    },
    "summarize_command": {
        "signal_phrase": "summarize",
        "match_position": "start", 
        "action": "transform",
        "handler": lambda self_ref, recorded_text: (
            logger.debug("Executing 'summarize_command' lambda handler"),
            (self_ref.overlay.show_message("🧠 Summarizing...") if self_ref.overlay else None),
            self_ref._get_llm_transformation(f"Summarize the key points concisely: {recorded_text}")
        )
    }
}

# --- Define Handlers Referenced Above ---

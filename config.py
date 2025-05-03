import logging

logger = logging.getLogger(__name__)

COMMANDS = [
  {
    "name": "language:de",
    "signal_phrase": ["german", "chairman"],
    "match_position": "exact",
    "action": ["language:de-DE", "mode:normal"],
    "overlay_message": "STT Hint: 🇩🇪 (Mode: Normal)"
  },
  {
    "name": "language:en",
    "signal_phrase": "english",
    "match_position": "exact",
    "action": ["language:en-US", "mode:normal"],
    "overlay_message": "STT Hint: 🇬🇧 (Mode: Normal)"
  },
  {
    "name": "mode:de-CH",
    "signal_phrase": ["swiss german", "swiss chairman"],
    "match_position": "start",
    "action": ["mode:de-CH"],
    "template": "Translate the following English text into Central Swiss German (Schweizerdeutsch). Provide only the translation:\n\nEnglish Text: {text}",
    "llm_model_override": "claude-3-haiku-20240307",
    "overlay_message": "Mode: 🇨🇭 Translate"
  },
  {
    "name": "mode:llm",
    "signal_phrase": "llm",
    "match_position": "exact",
    "action": ["mode:llm"],
    "overlay_message": "Mode: 🧠 LLM"
  },
  {
    "name": "command:big_files",
    "signal_phrase": "big files",
    "match_position": "start",
    "action": [],
    "template": """Use the following command to find our largest files:
`find . \( -false -o -path .git -o -path ./venv -o -path node_modules \) -prune -o -type f -exec wc -l {} + | cat | sort -nr`.

Then, start with the largest files and refactor our codebase enforcing:
- to not lose or break existing logic
- to have a well-organized project structure, following best practise of the current tech stack
- to have no DRY violations, no unused code, no unused imports
- all files are atomic and serve a single purpose
- all files to not have more than 300 lines of code
"""},
  {
    "name": "command:short_summary",
    "signal_phrase": "short",
    "match_position": "start",
    "action": ["llm"],
    "template": "Summarize the following text in bullet points using mostly keywords or very short phrases: {clipboard}"
  },
  
]

# --- Function moved from AudioProcessor ---
def get_configured_signal_phrases():
    """
    Retrieves the list of 'signal_phrase' values from a commands list.

    Args:
        commands_list (list): The list of command configuration dictionaries.

    Returns:
        list[str]: A list of signal phrases suitable for display.
                   Returns an empty list if the list is empty or no phrases are defined.
    """
    phrases = []
        
    # Iterate directly over the list of config dicts
    for config_data in COMMANDS:
        signal_phrase_config = config_data.get('signal_phrase')
        
        # Check if this config should be excluded based on action
        should_exclude = any(
            isinstance(action, str) and (
                # Check if action starts with 'stt_language:' or contains 'chairman'
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
        # else: Missing or empty signal_phrase, log handled elsewhere potentially
            
    logger.debug(f"Retrieved {len(phrases)} configured signal phrases to display from config.py.")
    return phrases
# --- End moved function ---

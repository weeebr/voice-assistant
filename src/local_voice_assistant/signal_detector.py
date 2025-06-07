"""Handles detecting signal phrases within transcribed text based on configuration."""
import logging
from typing import List, Dict, Tuple, Optional
import string

logger = logging.getLogger(__name__)

def find_matching_signal(text: str, signal_configs: List[Dict]) -> Tuple[Optional[Dict], Optional[str]]:
    """
    Iterates through signal configurations to find the first match in the text.

    Args:
        text: The transcribed text (assumed sanitized).
        signal_configs: The list of signal configuration dictionaries.

    Returns:
        A tuple containing: 
        - The matched configuration dictionary (or None if no match).
        - The remaining text after the signal phrase (or None if no match/not applicable).
    """
    if not text:
        return None, None

    original_text_lower = text.lower()
    # Prepare text for exact matching (lowercase, no punctuation)
    text_for_exact_match = original_text_lower.translate(str.maketrans('', '', string.punctuation)).strip()

    for config in signal_configs:
        signal_phrase_config = config.get('signal_phrase')
        if not signal_phrase_config:
            logger.warning(f"Signal config entry missing 'signal_phrase': {config}. Skipping.")
            continue
            
        # Ensure signal_phrase_config is a list for uniform processing
        phrases_to_check = []
        if isinstance(signal_phrase_config, list):
            phrases_to_check = signal_phrase_config
        elif isinstance(signal_phrase_config, str):
            phrases_to_check = [signal_phrase_config]  # Wrap single string in a list
        else:
             logger.warning(f"Signal config 'signal_phrase' has invalid type ({type(signal_phrase_config)}): {config}. Skipping.")
             continue

        match_position = config.get('match_position', 'anywhere') 
        
        # --- Loop through phrases for this config ---                    
        for phrase in phrases_to_check:
             if not phrase: continue  # Skip empty strings in list
             
             # Pre-processed phrase (lowercase, no punctuation) for exact matching
             phrase_lower = phrase.lower()
             phrase_exact = phrase_lower.translate(str.maketrans('', '', string.punctuation)).strip()
             signal_len = len(phrase)
             match_found = False
             text_for_handler = text  # Default based on 'anywhere'
             
             # --- Matching Logic (applied to each phrase) --- 
             if match_position == 'start':
                  if original_text_lower.startswith(phrase_lower):
                     match_found = True
                     remainder = text[signal_len:]
                     text_for_handler = remainder.lstrip(',.?!;: ').strip()
                     # If remainder is empty, return None to indicate no text to process
                     if not text_for_handler:
                         text_for_handler = None
             elif match_position == 'end':
                  if original_text_lower.endswith(phrase_lower):
                      match_found = True
                      remainder = text[:-signal_len]
                      text_for_handler = remainder.rstrip(',.?!;: ').strip()
                      # If remainder is empty, return None to indicate no text to process
                      if not text_for_handler:
                          text_for_handler = None
             elif match_position == 'exact':
                  if text_for_exact_match == phrase_exact:
                      match_found = True
                      text_for_handler = None  # Exact phrase doesn't pass text
             else:  # 'anywhere' (default) - Pass full text for processing
                 if phrase_lower in original_text_lower:
                     match_found = True
                     # For 'anywhere', text_for_handler remains the original full text
                     # Only return None if the text is empty after cleaning
                     cleaned_text = text.strip()
                     if not cleaned_text:
                         text_for_handler = None
             # ------------------------------------

             if match_found:
                 matched_phrase_in_list = phrase  # Store the phrase that actually matched
                 logger.info(f"🚥 Signal detected: '{matched_phrase_in_list}' (Config: '{config.get('name', 'Unnamed')}', Mode: '{match_position}')")
                 return config, text_for_handler  # Return matched config and remaining text

    # If no match found after checking all configs
    return None, None 

class SignalDetector:
    """Minimal SignalDetector class for compatibility. Wraps find_matching_signal."""
    def __init__(self, signal_configs):
        self.signal_configs = signal_configs or []

    def find(self, text):
        from .signal_detector import find_matching_signal
        return find_matching_signal(text, self.signal_configs) 

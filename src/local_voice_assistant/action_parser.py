"""Parses action strings from configuration into a structured format."""
import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

def parse_actions(action_config_list: List[str]) -> List[Dict[str, Any]]:
    """
    Parses a list of action strings into a list of dictionaries.
    Example input: ["mode:llm", "ner_extract:types_source=spoken,threshold=0.4"]
    Example output: [
        {'type': 'mode', 'value': 'llm', 'params': {}},
        {'type': 'ner_extract', 'value': None, 'params': {'types_source': 'spoken', 'threshold': '0.4'}}
    ]
    """
    parsed_actions = []
    if not isinstance(action_config_list, list):
        logger.error(f"Action config is not a list: {action_config_list}")
        return []

    for action_item in action_config_list:
        if not isinstance(action_item, str):
            logger.warning(f"Ignoring non-string action item: {action_item}")
            continue
        
        action_type = action_item
        action_value = None
        params = {}
        
        # Try splitting by ":" first for type:value or type:param=val,...
        if ':' in action_item:
            parts = action_item.split(':', 1)
            action_type = parts[0].strip()
            value_part = parts[1].strip()
            
            # Check if value_part contains parameters (key=value pairs)
            if '=' in value_part:
                param_pairs = value_part.split(',') # Split potential multiple params by comma
                for pair in param_pairs:
                    if '=' in pair:
                        key_value = pair.split('=', 1)
                        key = key_value[0].strip()
                        value = key_value[1].strip()
                        if key: # Ensure key is not empty
                            params[key] = value
                        else:
                             logger.warning(f"Ignoring parameter with empty key in action: {action_item}")
                    else:
                        # If a part after ":" has no "=", treat it as a simple value 
                        # if no other params were found yet. This is ambiguous.
                        # Let's prioritize params. If simple value expected, don't use "=" or ",".
                        if not params and pair.strip():
                             action_value = pair.strip()
                             # If we found a simple value, stop looking for params in this item
                             # break # This break might be too aggressive if mixed format intended
                             logger.warning(f"Action item '{action_item}' has mixed format after ':'. Treating '{action_value}' as value and ignoring potential subsequent params.")
                # If we found parameters, the primary action_value is considered None
                if params:
                    action_value = None
            else:
                # No "=", so the whole part after ":" is the simple value
                action_value = value_part
        # else: Action is simple type, like "llm", action_value is None, params is {}

        if not action_type:
            logger.warning(f"Ignoring action item with empty type: {action_item}")
            continue

        parsed_actions.append({
            'type': action_type,
            'value': action_value,
            'params': params
        })
        logger.debug(f"Parsed action: type='{action_type}', value='{action_value}', params={params}")

    return parsed_actions 

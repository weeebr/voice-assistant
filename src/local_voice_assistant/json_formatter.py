import json
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

def format_ner_json_custom(data: Dict[str, Any]) -> str:
    """
    Formats the NER result dictionary (now with dynamic label keys and 'hits')
    into a custom JSON-like string representation.
    - List values (representing entity types) are formatted on a single line.
    - Dictionary value ('hits') is formatted across multiple lines with indentation.
    - Handles error cases by returning standard JSON.
    - Returns "{}" if data is empty or contains only empty lists/hits.
    """
    if "error" in data:
        try: return json.dumps(data, indent=2)
        except TypeError as e:
             logger.error(f"Failed to format NER error result: {e}")
             return '{"error": "Failed to format NER error result."}'

    # If api_client returned {}, it means nothing was found
    if not data: 
        return "{}"

    list_item_parts = []
    hits_block_str = "" # Initialize empty hits string

    # --- Process all keys --- 
    # Sort keys first, treating 'hits' specially if present
    sorted_keys = sorted(data.keys())
    if "hits" in sorted_keys:
        sorted_keys.remove("hits") # Process hits last
        sorted_keys.append("hits") 
    
    for key in sorted_keys:
        value = data[key]
        
        # --- Handle 'hits' dictionary --- 
        if key == "hits":
            if isinstance(value, dict) and value: # Check if dict and not empty
                hits_item_parts = []
                # Sort hits by entity text (key) for consistent output
                for k, v in sorted(value.items()): 
                    try:
                        key_str = json.dumps(k)
                        value_str = json.dumps(v)
                        # Indent items within the hits block
                        hits_item_parts.append(f"    {key_str}: {value_str}") 
                    except TypeError as e:
                        logger.error(f"Failed to serialize item '{k}' in hits dict: {e}")
                        
                if hits_item_parts:
                    # Join parts with comma+newline, add outer braces and indentation for the block
                    hits_block_str = f'"hits": {{\n' + ",\n".join(hits_item_parts) + "\n  }"
            elif value: # It exists but isn't a dict? Log warning.
                logger.warning(f"Expected 'hits' value to be a dict, got {type(value)}. Skipping hits formatting.")
            # else: hits key exists but dict is empty, so skip it
            
        # --- Handle list categories (dynamic labels) --- 
        elif isinstance(value, list): # Treat any other key with a list value as an entity type
             # Note: api_client should have removed empty lists already
             if value: # Double check list isn't empty
                try:
                    # Use json.dumps on the list for correct single-line format & escaping
                    list_str = json.dumps(value)
                    key_str = json.dumps(key) # Dump the dynamic label key
                    list_item_parts.append(f'{key_str}: {list_str}')
                except TypeError as e:
                     logger.error(f"Failed to serialize list for key '{key}' to JSON: {e}")
        
        # --- Handle other unexpected data types (log warning) --- 
        else:
             logger.warning(f"Unexpected data type for key '{key}' in NER results: {type(value)}. Skipping.")

    # --- Combine the parts --- 
    all_parts = list_item_parts # Start with the sorted list items
    if hits_block_str:
        all_parts.append(hits_block_str)

    if not all_parts:
        # If after processing, nothing was eligible for formatting
        return "{}" 

    # Join the top-level items with commas and newlines, add outer braces
    body = ",\n  ".join(all_parts)
    return f"{{\n  {body}\n}}" 

import logging
from collections import Counter, defaultdict
import requests
import json
import re # Import re for whitespace normalization
from typing import Dict, List, Any # Add typing imports

logger = logging.getLogger(__name__)

# <<< RENAMED CLASS >>>
class NERServiceClient:
    """Handles NER extraction by calling an external NER service and formats the output."""

    def __init__(self, ner_service_url):
        """
        Initializes the NERServiceClient.

        Args:
            ner_service_url: The URL of the external NER service endpoint (e.g., http://localhost:5001/extract).
        """
        self.service_url = ner_service_url
        if not ner_service_url:
            # <<< UPDATED Class Name in Log >>>
            logger.error("NERServiceClient initialized without a service URL. Extraction will fail.")
        else:
            logger.info(f"NERServiceClient configured to use service: {self.service_url}")

    # <<< Revert to previous formatting logic with hits >>>
    # <<< REFACTORED Method to be Dynamic >>>
    def _format_grouped_entities(self, raw_grouped_entities: defaultdict) -> Dict[str, Any]:
        """
        Formats entities dynamically based on NER labels.
        Output includes a 'hits' map and keys for each found label.
        """
        # 1. Initialize dynamic results structure
        results = {"hits": {}}
        # Use a temporary dict to store lists of unique names per label
        unique_names_by_label = defaultdict(set) 
        
        # 2. Process raw entities (preserving original case)
        for label, entity_counter in raw_grouped_entities.items():
            if not label: # Skip if label is empty
                 logger.warning("Skipping entity group with empty label.")
                 continue
            
            # Ensure the label key exists in results before adding to its set
            if label not in unique_names_by_label:
                 unique_names_by_label[label] = set() # Initialize the set for the label

            for entity_text, count in entity_counter.items(): # entity_text has original case
                # Add/Update count in the global hits dictionary
                results["hits"][entity_text] = results["hits"].get(entity_text, 0) + count
                
                # Add to the set for this label if unique for that label
                if entity_text not in unique_names_by_label[label]:
                    unique_names_by_label[label].add(entity_text)

        # 3. Convert sets to sorted lists and add to results
        for label, name_set in unique_names_by_label.items():
            if name_set: # Only add if the list is not empty
                 results[label] = sorted(list(name_set))
            # else: Don't add the key if the list ended up empty
        
        # 4. Clean up empty 'hits' only if no other labels were found
        label_keys_found = [k for k in results if k != "hits"]
        if not results["hits"] and not label_keys_found:
             del results["hits"]
             logger.info("No entities found, returning empty dictionary for formatter.")
             return {} # Return empty dict if nothing was found at all
        elif not results["hits"]:
             # Hits is empty, but other labels were found, remove the empty hits dict
             del results["hits"] 
             logger.info(f"Processed entities into {len(label_keys_found)} labels, but no hits recorded (unexpected).")
        elif results["hits"]:
             # Use len(label_keys_found) which correctly counts labels excluding "hits"
             logger.info(f"Processed {len(results['hits'])} unique mentions into {len(label_keys_found)} final labels.")
        
        return results

    # Method signature remains the same
    def extract_and_format_entities(self, text: str, types_input: str, threshold=0.5) -> Dict[str, Any]:
        """Calls the NER /extract endpoint, processes results, formats with hits.""" 
        if not self.service_url:
            logger.error("Cannot call NER service: Service URL is not configured.")
            return {"error": "NER service URL not configured."}
        
        try:
            params = {'text': text, 'types': types_input, 'threshold': str(threshold)}
            endpoint_url = self.service_url 
            logger.info(f"Attempting to send NER request to {endpoint_url}")
            logger.debug(f"Request details - URL: {endpoint_url}, Params: {params}")
            
            # <<< Add logging immediately before the request >>>
            logger.debug("Calling requests.get...")
            response = requests.get(endpoint_url, params=params, timeout=10)
            # <<< Add logging immediately after the request >>>
            logger.debug(f"requests.get finished. Status code: {response.status_code}")
            
            response.raise_for_status() # Check for HTTP errors (4xx, 5xx)
            
            # <<< Add logging for successful response before JSON decode >>>
            logger.debug("Request successful (HTTP 2xx). Attempting to decode JSON...")
            entities = response.json()
            logger.debug(f"Successfully decoded JSON response.")
            logger.info(f"🧐 NER Service (/extract) returned {len(entities)} raw entity mentions.")

            if not isinstance(entities, list):
                logger.error(f"Invalid response format from NER service: Expected list, got {type(entities)}")
                return {"error": "Invalid response format from NER service."}
            if not entities:
                logger.info(f"No entities found by NER service for types: '{types_input}'")
                return {"message": f"No entities found for types: '{types_input}'"}

            # --- Process Entities PRESERVING ORIGINAL CASE --- 
            raw_grouped_entities = defaultdict(lambda: Counter())
            for entity in entities:
                if not isinstance(entity, dict) or not all(k in entity for k in ('label', 'text')):
                    logger.warning(f"Skipping invalid entity dict format from service: {entity}")
                    continue
                label = entity['label']
                original_text = entity['text']
                if not isinstance(original_text, str):
                     logger.warning(f"Entity text is not a string, skipping: {original_text}")
                     continue
                sanitized_text = ' '.join(original_text.strip().split())
                if sanitized_text:
                    raw_grouped_entities[label][sanitized_text] += 1
                else:
                    logger.debug(f"Entity text became empty after sanitization: '{original_text}'")
            # -----------------------------------------------------

            # --- Format using the REVERTED helper --- 
            formatted_results = self._format_grouped_entities(raw_grouped_entities)
            
            # <<< Add check for empty results AFTER formatting >>>
            if not formatted_results:
                # _format_grouped_entities returns {} if nothing was processed
                return {"message": f"No entities found for types: '{types_input}'"}
            else:
                return formatted_results

        # --- Error Handling --- 
        except requests.exceptions.ConnectionError as e:
             # <<< More specific logging for ConnectionError >>>
             logger.error(f"❌ CONNECTION FAILED to NER service at {endpoint_url}. Is the service running? Details: {e}")
             return {"error": "NER service is unavailable or starting up."}
        except requests.exceptions.Timeout as e:
            logger.error(f"❌ Request to NER service (/extract) timed out ({endpoint_url}). Details: {e}")
            return {"error": "NER service request timed out."}
        except requests.exceptions.RequestException as e:
            # Log the specific status code if available
            status_code = e.response.status_code if e.response is not None else "N/A"
            logger.error(f"❌ NER service (/extract) request failed. Status: {status_code}. Error: {e}")
            # Check for specific 400 error from service (e.g., no valid types)
            if e.response is not None and e.response.status_code == 400:
                 try:
                     error_data = e.response.json()
                     error_msg = error_data.get("error", "Client request error (400)")
                     logger.error(f"❌ NER service returned 400 error (/extract): {error_msg}")
                     return {"error": error_msg}
                 except json.JSONDecodeError:
                      logger.error(f"❌ NER service returned 400 but failed to parse error JSON.")
                      return {"error": "Invalid types specified or client request error."}
            else:
                error_msg = f"NER service (/extract) request failed ({type(e).__name__})."
                logger.error(f"❌ Request to NER service (/extract) failed: {e}")
                return {"error": error_msg}
        except json.JSONDecodeError as e:
             # <<< Add logging for JSON decode failure >>>
             logger.error(f"❌ Failed to decode JSON response from NER service ({endpoint_url}). Response text: '{response.text[:200]}...'. Error: {e}")
             return {"error": "Invalid JSON response from NER service."}
        except Exception as e:
            # <<< Log unexpected errors during the request/response phase >>>
            logger.exception(f"🚨 Unexpected error during NER HTTP request/response processing: {e}")
            # Fall through to formatting/processing error handling below?
            # Let's return a specific error here
            return {"error": "Unexpected error during NER service communication."}

        # --- FORMATTING PHASE --- 
        try: 
            # ... (existing formatting logic calling _format_grouped_entities) ...
            raw_grouped_entities = defaultdict(lambda: Counter())
            # ... (entity processing loop) ...
            formatted_results = self._format_grouped_entities(raw_grouped_entities)
            # ... (check for empty results) ...
            return formatted_results
        except Exception as e:
            # <<< Log unexpected errors specifically during formatting >>>
            logger.exception(f"🚨 Unexpected error during NER result formatting phase: {e}")
            return {"error": "Unexpected error formatting NER results."}
            
    # --- REMOVE REDUNDANT METHOD --- 
    # def extract_with_parsed_types(self, text: str, types_string: str, threshold=0.5) -> Dict[str, Any]:
    #    ...
    # --- END REMOVED METHOD --- 

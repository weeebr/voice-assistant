import logging
import os

# Attempt to import LLM libraries
try:
    from anthropic import Anthropic, APIError
    # httpx is a dependency of anthropic
    import httpx 
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

try:
    import google.generativeai as genai
    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

logger = logging.getLogger(__name__)

class LLMClient:
    """Manages initialization and interaction with different LLM providers."""

    # Default model IDs if not overridden
    DEFAULT_GOOGLE_MODEL = "gemini-1.5-pro-latest" 
    DEFAULT_ANTHROPIC_MODEL = "claude-3-haiku-20240307"
    
    # --- NEW: Keywords for dynamic provider detection ---
    PROVIDER_KEYWORDS = {
        'anthropic': ['claude'],
        'google': ['gemini'],
        # Add more if needed, e.g., 'openai': ['gpt']
    }
    # ----------------------------------------------------

    def __init__(self, config):
        """Initializes the LLM clients based on configuration and API keys."""
        self.config = config
        self.provider = config.get('llm_provider', 'anthropic').lower() # Default configured provider
        self._anthropic_client = None
        self._google_client = None

        # Initialize Anthropic client (if available and key set)
        if ANTHROPIC_AVAILABLE:
            _anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
            if _anthropic_api_key:
                try:
                    self._anthropic_client = Anthropic(api_key=_anthropic_api_key)
                    logger.info("🤖 Anthropic client initialized successfully (Claude).")
                except Exception as e:
                    logger.error(f"🤖❌ Anthropic init failed: {e}")
            # Keep warnings concise
            # else: logger.warning("🤖 Anthropic client disabled: ANTHROPIC_API_KEY not set.")
        # else: logger.warning("🤖 Anthropic client disabled: 'anthropic' package not installed.")

        # Initialize Google client (if available and key set)
        if GOOGLE_AVAILABLE:
            _google_api_key = os.getenv("GOOGLE_API_KEY")
            if _google_api_key:
                try:
                    genai.configure(api_key=_google_api_key)
                    # Store the configured genai module itself
                    self._google_client_module = genai 
                    logger.info("✨ Google AI client initialized successfully (Gemini).")
                except Exception as e:
                    logger.error(f"✨❌ Google AI init failed: {e}")
            # Keep warnings concise
            # else: logger.warning("✨ Google AI client disabled: GOOGLE_API_KEY not set.")
        # else: logger.warning("✨ Google AI client disabled: 'google-generativeai' package not installed.")

        # Log final status
        provider_status = []
        if self._anthropic_client: provider_status.append("Anthropic(✅)")
        if hasattr(self, '_google_client_module'): provider_status.append("Google(✅)")
        logger.info(f"LLM Client Status: Default Provider='{self.provider}', Available=[{', '.join(provider_status)}]")
        
        # Log potential issues clearly
        if self.provider == 'google' and not hasattr(self, '_google_client_module'):
             logger.error(f"LLM provider set to 'google' but client failed to initialize!")
        elif self.provider == 'anthropic' and not self._anthropic_client:
             logger.error(f"LLM provider set to 'anthropic' but client failed to initialize!")


    def transform_text(self, prompt: str, model_override: str | None = None) -> str | None:
        """
        Sends the prompt to an LLM provider and returns the text response.
        Dynamically selects the provider based on model_override if possible, 
        otherwise uses the default configured provider.
        """
        
        if not prompt:
            logger.warning("⚠️ LLM transformation requested with empty prompt. Skipping.")
            return None

        target_provider = self.provider # Start with the default
        final_model_id = None
        is_dynamic_selection = False

        # --- Dynamic Provider Selection Logic ---
        if model_override:
            model_override_lower = model_override.lower()
            for provider_key, keywords in self.PROVIDER_KEYWORDS.items():
                if any(keyword in model_override_lower for keyword in keywords):
                    # Check if the client for the detected provider is actually available
                    client_available = False
                    if provider_key == 'anthropic' and self._anthropic_client:
                        client_available = True
                    elif provider_key == 'google' and hasattr(self, '_google_client_module'):
                        client_available = True
                    # Add elif for other providers here
                        
                    if client_available:
                        if target_provider != provider_key:
                             logger.info(f"🔄 Dynamically switching provider to '{provider_key}' based on model_override: '{model_override}'")
                        target_provider = provider_key
                        is_dynamic_selection = True
                        break # Use first match
                    else:
                        logger.warning(f"Keyword for provider '{provider_key}' detected in override '{model_override}', but client is not available. Falling back.")
        # ----------------------------------------

        # Determine the final model ID to use
        if target_provider == 'google':
            final_model_id = model_override if model_override else self.DEFAULT_GOOGLE_MODEL
        elif target_provider == 'anthropic':
            final_model_id = model_override if model_override else self.DEFAULT_ANTHROPIC_MODEL
        # Add elif for other providers
        else:
             logger.error(f"❌ Invalid LLM provider determined: '{target_provider}'. Cannot proceed.")
             return None

        # Log the final decision
        logger.info(f"LLM Transformation: Provider='{target_provider}'{'(Dynamic)' if is_dynamic_selection else '(Default)'}, Model='{final_model_id}'")
        
        # --- Call Appropriate Helper Method ---
        if target_provider == 'google':
            if hasattr(self, '_google_client_module'):
                return self._call_google(prompt, final_model_id)
            else:
                 logger.error("✨❌ Google AI client not available for transformation.")
                 return None
        elif target_provider == 'anthropic':
            if self._anthropic_client:
                 return self._call_anthropic(prompt, final_model_id)
            else:
                 logger.error("🤖❌ Anthropic client not available for transformation.")
                 return None
        # Add elif for other providers
        else:
            # This case should technically be caught earlier, but acts as a safeguard
            logger.error(f"❌ Cannot call unknown provider '{target_provider}'.")
            return None
            
    # --- Private Helper Methods for API Calls ---

    def _call_google(self, prompt: str, model_id: str) -> str | None:
        """Handles the API call to Google Gemini."""
        logger.debug(f"Sending prompt to Google Gemini (Model: {model_id}): '{prompt[:100]}...'")
        try:
            # Get the model instance from the stored module
            model = self._google_client_module.GenerativeModel(model_id) 
            response = model.generate_content(prompt)
            
            # Enhanced response handling (same as before)
            if hasattr(response, 'text') and response.text:
                response_text = response.text.strip()
            elif hasattr(response, 'parts') and response.parts:
                 try:
                     response_text = ''.join(part.text for part in response.parts).strip()
                     if not response_text:
                          logger.warning(f"⚠️ Google Gemini response parts contained no text (Model: {model_id}).")
                          return None
                 except Exception as extract_err:
                     logger.error(f"Failed to extract text from Gemini parts: {extract_err}")
                     logger.warning(f"Raw parts: {response.parts}")
                     return None 
            else:
                logger.warning(f"⚠️ Google Gemini response structure unexpected or empty (Model: {model_id}). Response: {response}")
                return None 

            logger.debug(f"✨ Google Gemini response received (Model: {model_id}): '{response_text[:100]}...'")
            return response_text

        except Exception as e:
            # Check for specific Google API errors if the library provides them, otherwise generic
            # Example check (needs actual exception types from google.api_core.exceptions if available)
            # if isinstance(e, google.api_core.exceptions.NotFound):
            #     logger.error(f"✨❌ Google API Error: Model '{model_id}' not found or not supported. {e}")
            # elif isinstance(e, google.api_core.exceptions.PermissionDenied):
            #      logger.error(f"✨❌ Google API Error: Permission denied (check API key?). {e}")
            # else:
            logger.exception(f"✨💥 Unexpected error during Google Gemini transformation (Model: {model_id}): {e}")
            return None

    def _call_anthropic(self, prompt: str, model_id: str) -> str | None:
        """Handles the API call to Anthropic Claude."""
        logger.debug(f"Sending prompt to Anthropic Claude (Model: {model_id}): '{prompt[:100]}...'")
        try:
            messages = [{"role": "user", "content": prompt}]
            # Use the stored client instance directly
            completion = self._anthropic_client.messages.create(
                model=model_id, 
                max_tokens=self.config.get('anthropic_max_tokens', 1000), # Make max_tokens configurable
                messages=messages,
                temperature=self.config.get('anthropic_temperature', 0.7), # Make temperature configurable
            )
            
            # Response handling (same as before)
            if completion.content and len(completion.content) > 0 and hasattr(completion.content[0], 'text'):
                response_text = completion.content[0].text.strip()
                if not response_text:
                     logger.warning(f"⚠️ Anthropic LLM transformation result is empty (Model: {model_id}).")
                     return None 
                logger.debug(f"🤖 Anthropic response received (Model: {model_id}, Messages API): '{response_text[:100]}...'")
                return response_text
            else:
                logger.warning(f"⚠️ Anthropic response content is empty or missing expected structure (Model: {model_id}). Response: {completion}")
                return None

        except APIError as e:
            error_details = "(Could not parse error body)"
            try: error_details = e.body
            except Exception: pass
            logger.error(f"🤖❌ Anthropic API error (Model: {model_id}): {e.status_code} - {error_details}")
            return None
        except Exception as e:
            logger.exception(f"🤖💥 Unexpected error during Anthropic transformation (Model: {model_id}): {e}")
            return None

# --- Removed old monolithic transform_text logic ---

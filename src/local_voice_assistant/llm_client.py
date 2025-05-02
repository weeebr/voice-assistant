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
    DEFAULT_GOOGLE_MODEL = "gemini-1.5-pro-latest" # Changed default to stable 1.5 Pro
    # DEFAULT_GOOGLE_MODEL = "gemini-2.5-pro-exp-03-25" # Keep 2.5 available via override
    DEFAULT_ANTHROPIC_MODEL = "claude-3-haiku-20240307"

    def __init__(self, config):
        """Initializes the LLM clients based on configuration and API keys."""
        self.config = config
        self.provider = config.get('llm_provider', 'anthropic').lower()
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
            else:
                logger.warning("🤖 Anthropic client disabled: ANTHROPIC_API_KEY not set.")
        else:
             logger.warning("🤖 Anthropic client disabled: 'anthropic' package not installed.")

        # Initialize Google client (if available and key set)
        if GOOGLE_AVAILABLE:
            _google_api_key = os.getenv("GOOGLE_API_KEY")
            if _google_api_key:
                try:
                    genai.configure(api_key=_google_api_key)
                    self._google_client = genai # Use the configured module
                    logger.info("✨ Google AI client initialized successfully (Gemini).")
                except Exception as e:
                    logger.error(f"✨❌ Google AI init failed: {e}")
            else:
                logger.warning("✨ Google AI client disabled: GOOGLE_API_KEY not set.")
        else:
            logger.warning("✨ Google AI client disabled: 'google-generativeai' package not installed.")

        logger.info(f"Configured LLM provider: '{self.provider}'")
        if self.provider == 'google' and not self._google_client:
             logger.error(f"LLM provider set to 'google' but client failed to initialize!")
        elif self.provider == 'anthropic' and not self._anthropic_client:
             logger.error(f"LLM provider set to 'anthropic' but client failed to initialize!")


    def transform_text(self, prompt: str, model_override: str | None = None) -> str | None:
        """Sends the prompt to the configured LLM provider and returns the text response."""
        
        if not prompt:
            logger.warning("⚠️ LLM transformation requested with empty prompt. Skipping.")
            return None

        logger.info(f"LLM Transformation request using provider: {self.provider}")

        # --- Google Gemini ---
        if self.provider == 'google':
            if not self._google_client:
                logger.error("✨❌ Google AI client not available for transformation.")
                return None

            model_id = model_override if model_override else self.DEFAULT_GOOGLE_MODEL
            logger.debug(f"Sending prompt to Google Gemini (Model: {model_id}): '{prompt[:100]}...'" + (" (Overridden)" if model_override else ""))
            
            try:
                model = self._google_client.GenerativeModel(model_id)
                # Simple text generation, add safety settings or other params if needed later
                response = model.generate_content(prompt)
                
                # Enhanced response handling for Gemini
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
                         return None # Could not extract text
                else:
                    logger.warning(f"⚠️ Google Gemini response structure unexpected or empty (Model: {model_id}). Response: {response}")
                    return None 

                logger.debug(f"✨ Google Gemini response received (Model: {model_id}): '{response_text[:100]}...'" + (" (Overridden)" if model_override else ""))
                return response_text

            except Exception as e:
                # Consider adding more specific Google API exception handling later if possible
                logger.exception(f"✨💥 Unexpected error during Google Gemini transformation (Model: {model_id}): {e}")
                return None

        # --- Anthropic Claude ---
        elif self.provider == 'anthropic':
            if not self._anthropic_client:
                logger.error("🤖❌ Anthropic client not available for transformation.")
                return None

            model_id = model_override if model_override else self.DEFAULT_ANTHROPIC_MODEL
            logger.debug(f"Sending prompt to Anthropic Claude (Model: {model_id}): '{prompt[:100]}...'" + (" (Overridden)" if model_override else ""))
            
            try:
                messages = [{"role": "user", "content": prompt}]
                completion = self._anthropic_client.messages.create(
                    model=model_id, 
                    max_tokens=1000, # Adjust as needed
                    messages=messages,
                    temperature=0.7, 
                )
                
                if completion.content and len(completion.content) > 0 and hasattr(completion.content[0], 'text'):
                    response_text = completion.content[0].text.strip()
                    if not response_text:
                         logger.warning(f"⚠️ Anthropic LLM transformation result is empty (Model: {model_id}).")
                         return None 
                    logger.debug(f"🤖 Anthropic response received (Model: {model_id}, Messages API): '{response_text[:100]}...'" + (" (Overridden)" if model_override else ""))
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
        
        # --- Invalid Provider ---
        else:
            logger.error(f"❌ Invalid LLM provider configured: '{self.provider}'. Use 'google' or 'anthropic'.")
            return None 

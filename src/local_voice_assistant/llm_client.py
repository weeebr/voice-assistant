import logging
import os
import sys

# Attempt to import LLM libraries
try:
    from anthropic import Anthropic, APIError
    # httpx is a dependency of anthropic
    import httpx 
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# <<< REMOVED: Top-level Google import block >>>
# try:
#     import google.generativeai as genai
#     GOOGLE_AVAILABLE = True
# except ImportError as e:
#     print(f"!!! DEBUG: FAILED to import google.generativeai: {e}", file=sys.stderr)
#     GOOGLE_AVAILABLE = False

# --- NEW: Add OpenAI ---    
try:
    import openai
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
# -----------------------

logger = logging.getLogger(__name__)

class LLMClient:
    """Manages initialization and interaction with different LLM providers."""

    # Default model IDs if not overridden
    DEFAULT_GOOGLE_MODEL = "gemini-1.5-flash" 
    DEFAULT_ANTHROPIC_MODEL = "claude-3-haiku-20240307"
    DEFAULT_OPENAI_MODEL = "gpt-4o" # <-- Added OpenAI default
    
    # --- NEW: Keywords for dynamic provider detection ---
    PROVIDER_KEYWORDS = {
        'anthropic': ['claude'],
        'google': ['gemini'],
        'openai': ['gpt'], # <-- Added OpenAI keywords
        # Add more if needed, e.g., 'openai': ['gpt']
    }
    # ----------------------------------------------------

    def __init__(self, default_provider: str):
        """Initializes the LLM clients based on API keys and default provider."""
        self.provider = default_provider.lower() # Use passed default provider
        self._anthropic_client = None
        self._google_client_module = None
        self._openai_client = None

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

        # Initialize Google client (if API key set)
        _google_api_key = os.getenv("GOOGLE_API_KEY")
        if _google_api_key:
            _genai_module = None # Temp variable for imported module
            try:
                # <<< MOVED: Import google.generativeai here >>>
                import google.generativeai as genai
                _genai_module = genai # Store imported module if successful
            except ImportError as e:
                logger.error(f"✨❌ Failed to import google.generativeai package. Is it installed correctly? Error: {e}")
                # Keep self._google_client_module as None
            
            # Only proceed if import succeeded
            if _genai_module:
                try:
                    _genai_module.configure(api_key=_google_api_key)
                    # Store the configured genai module itself
                    self._google_client_module = _genai_module 
                    logger.info("✨ Google AI client initialized successfully (Gemini).")
                except Exception as e:
                    logger.error(f"✨❌ Google AI configure failed: {e}")
                    # Keep self._google_client_module as None
            # Print final status after attempt
            # print(f"!!! DEBUG: Google client module AFTER init attempt: {self._google_client_module}", file=sys.stderr)
        else:
            logger.warning("✨ Google AI client disabled: GOOGLE_API_KEY not set.")
            # Ensure it's None if key wasn't set
            self._google_client_module = None 

        # --- NEW: Initialize OpenAI client --- 
        if OPENAI_AVAILABLE:
            logger.debug("Attempting to initialize OpenAI client...")
            _openai_api_key = os.getenv("OPENAI_API_KEY")
            if _openai_api_key:
                try:
                    self._openai_client = openai.OpenAI(api_key=_openai_api_key)
                    logger.info("○ OpenAI client initialized successfully (GPT).")
                except Exception as e:
                    # Log the specific error during OpenAI client creation
                    logger.error(f"○❌ OpenAI client initialization failed: {e}", exc_info=True)
            else:
                logger.warning("○ OpenAI client disabled: OPENAI_API_KEY not found in environment.")
        else:
             logger.warning("○ OpenAI client disabled: 'openai' package not installed or import failed.")
        # ------------------------------------

        # Log final status
        provider_status = []
        if self._anthropic_client: provider_status.append("Anthropic(✅)")
        if self._google_client_module is not None: provider_status.append("Google(✅)")
        if self._openai_client: provider_status.append("OpenAI(✅)") # <-- Added OpenAI status
        logger.info(f"LLM Client Status: Default Provider='{self.provider}', Available=[{', '.join(provider_status) if provider_status else 'None'}]")
        
        # Log potential issues clearly
        if self.provider == 'google' and self._google_client_module is None:
             logger.error(f"LLM provider set to 'google' but client failed to initialize!")
        elif self.provider == 'anthropic' and not self._anthropic_client:
             logger.error(f"LLM provider set to 'anthropic' but client failed to initialize!")
        elif self.provider == 'openai' and not self._openai_client: # <-- Added OpenAI check
             logger.error(f"LLM provider set to 'openai' but client failed to initialize!")


    def transform_text(self, prompt: str, notification_manager, model_override: str | None = None) -> str | None:
        """
        Sends the prompt to an LLM provider and returns the text response.
        Dynamically selects the provider based on model_override if possible, 
        otherwise uses the default configured provider.
        Also triggers a notification via the provided notification_manager.
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
                    elif provider_key == 'google' and self._google_client_module is not None:
                        client_available = True
                    elif provider_key == 'openai' and self._openai_client: # <-- Check OpenAI client
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
        elif target_provider == 'openai': # <-- Added OpenAI model ID
             final_model_id = model_override if model_override else self.DEFAULT_OPENAI_MODEL
        # Add elif for other providers
        else:
             logger.error(f"❌ Invalid LLM provider determined: '{target_provider}'. Cannot proceed.")
             return None

        # Log the final decision
        logger.info(f"LLM Transformation: Provider='{target_provider}'{'(Dynamic)' if is_dynamic_selection else '(Default)'}, Model='{final_model_id}'")
        
        # --- Call Appropriate Helper Method ---
        if target_provider == 'google':
            if self._google_client_module is not None:
                # Pass notification_manager down
                return self._call_google(prompt, final_model_id, notification_manager)
            else:
                 logger.error("✨❌ Google AI client not available for transformation.")
                 return None
        elif target_provider == 'anthropic':
            if self._anthropic_client:
                 # Pass notification_manager down
                 return self._call_anthropic(prompt, final_model_id, notification_manager)
            else:
                 logger.error("🤖❌ Anthropic client not available for transformation.")
                 return None
        elif target_provider == 'openai': # <-- Added OpenAI dispatch
            if self._openai_client:
                 # Pass notification_manager down
                 return self._call_openai(prompt, final_model_id, notification_manager)
            else:
                 logger.error("○❌ OpenAI client not available for transformation.")
                 return None
        # Add elif for other providers
        else:
            # This case should technically be caught earlier, but acts as a safeguard
            logger.error(f"❌ Cannot call unknown provider '{target_provider}'.")
            return None
            
    # --- Private Helper Methods for API Calls ---

    def _call_google(self, prompt: str, model_id: str, notification_manager) -> str | None:
        """Handles the API call to Google Gemini, including notification."""
        # --- Add Check: Ensure client module is not None --- 
        # This is an extra safeguard, shouldn't be needed if transform_text checks work
        if self._google_client_module is None:
            logger.error("✨❌ _call_google invoked but google_client_module is None!")
            return None
        # ----------------------------------------------------
        
        # --- Show Notification --- 
        if notification_manager:
             notification_manager.show_message(f"🧠 Calling Google: {model_id}")
        else:
            logger.warning("NotificationManager not provided to _call_google")
        # -----------------------
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

    def _call_anthropic(self, prompt: str, model_id: str, notification_manager) -> str | None:
        """Handles the API call to Anthropic Claude, including notification."""
        # --- Show Notification --- 
        if notification_manager:
             notification_manager.show_message(f"🧠 Calling Anthropic: {model_id}")
        else:
            logger.warning("NotificationManager not provided to _call_anthropic")
        # -----------------------
        logger.debug(f"Sending prompt to Anthropic Claude (Model: {model_id}): '{prompt[:100]}...'")
        try:
            # --- Get settings from environment variables with defaults ---
            try:
                max_tokens = int(os.getenv('ANTHROPIC_MAX_TOKENS', '1000'))
                temperature = float(os.getenv('ANTHROPIC_TEMPERATURE', '0.7'))
            except ValueError:
                logger.warning("Invalid numeric value for ANTHROPIC_MAX_TOKENS or ANTHROPIC_TEMPERATURE env var. Using defaults.")
                max_tokens = 1000
                temperature = 0.7
            # ------------------------------------------------------------
            logger.debug(f"Anthropic params: max_tokens={max_tokens}, temperature={temperature}")

            messages = [{"role": "user", "content": prompt}]
            completion = self._anthropic_client.messages.create(
                model=model_id,
                max_tokens=max_tokens, # Use value from env var or default
                messages=messages,
                temperature=temperature, # Use value from env var or default
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

    # --- NEW: Helper for OpenAI --- 
    def _call_openai(self, prompt: str, model_id: str, notification_manager) -> str | None:
        """Handles the API call to OpenAI GPT, including notification."""
        # --- Show Notification --- 
        if notification_manager:
             notification_manager.show_message(f"🧠 Calling OpenAI: {model_id}")
        else:
            logger.warning("NotificationManager not provided to _call_openai")
        # -----------------------
        logger.debug(f"Sending prompt to OpenAI GPT (Model: {model_id}): '{prompt[:100]}...'")
        try:
            # --- Get settings from environment variables with defaults ---
            try:
                max_tokens = int(os.getenv('OPENAI_MAX_TOKENS', '1000'))
                temperature = float(os.getenv('OPENAI_TEMPERATURE', '0.7'))
            except ValueError:
                logger.warning("Invalid numeric value for OPENAI_MAX_TOKENS or OPENAI_TEMPERATURE env var. Using defaults.")
                max_tokens = 1000
                temperature = 0.7
            # ------------------------------------------------------------
            logger.debug(f"OpenAI params: max_tokens={max_tokens}, temperature={temperature}")

            messages = [{"role": "user", "content": prompt}]
            completion = self._openai_client.chat.completions.create(
                model=model_id,
                messages=messages,
                max_tokens=max_tokens, # Use value from env var or default
                temperature=temperature, # Use value from env var or default
            )
            
            if completion.choices and len(completion.choices) > 0 and completion.choices[0].message:
                response_text = completion.choices[0].message.content
                if response_text:
                    response_text = response_text.strip()
                    if not response_text:
                         logger.warning(f"⚠️ OpenAI LLM transformation result is empty (Model: {model_id}).")
                         return None 
                    logger.debug(f"○ OpenAI response received (Model: {model_id}): '{response_text[:100]}...'")
                    return response_text
                else:
                     logger.warning(f"⚠️ OpenAI response message content is empty (Model: {model_id}).")
                     return None
            else:
                logger.warning(f"⚠️ OpenAI response choices are empty or missing expected structure (Model: {model_id}). Response: {completion}")
                return None
        # Refine error handling based on OpenAI library specifics
        except openai.APIError as e:
             logger.error(f"○❌ OpenAI API error (Model: {model_id}): {e.status_code} - {e.message}")
             return None
        except Exception as e:
            logger.exception(f"○💥 Unexpected error during OpenAI transformation (Model: {model_id}): {e}")
            return None

# --- Removed old monolithic transform_text logic ---
 
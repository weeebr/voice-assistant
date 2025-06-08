import logging
import subprocess
import time
import os
from pynput.keyboard import Controller, Key # Requires pynput
import re

logger = logging.getLogger(__name__)

class ClipboardManager:
    """Handles clipboard interactions (copy, paste, get content) and simulations."""

    def __init__(self, owner):
        """Initialize the Clipboard Manager.

        Args:
            owner: A reference to the owning object (e.g., Orchestrator) 
                   that has the 'hotkey_suppressed' attribute.
        """
        self.owner = owner # To access hotkey_suppressed flag
        try:
            self.kb_controller = Controller()
        except Exception as e:
            logger.error(f"⌨️💥 Failed to initialize pynput Controller: {e}. Paste/Backspace simulation will fail.")
            self.kb_controller = None

        # Pre-compile exclusion regexes for performance
        # Each tuple contains (pattern, description)
        self.exclusion_patterns = [
            (re.compile(r"^\s*thanks? for watching[.!?]?\s*$", re.IGNORECASE), "thanks for watching"),
            (re.compile(r"^\s*thank you[.!?]?\s*$", re.IGNORECASE), "thank you"),
            (re.compile(r"^\s*vielen dank[.!?]?\s*$", re.IGNORECASE), "vielen dank"),
            (re.compile(r"^\s*Das war's für heute\.?\s*Bis zum nächsten Mal\.?\s*Tschüss?[.!?]?\s*$", re.IGNORECASE), "Das war's für heute. Bis zum nächsten Mal. Tschüss."),
            (re.compile(r"^\s*Das war's für heute\.?\s*Bis zum nächsten Mal[.!?]?\s*$", re.IGNORECASE), "Das war's für heute. Bis zum nächsten Mal."),
            (re.compile(r"^\s*Das war's für heute[.!?]?\s*$", re.IGNORECASE), "Das war's für heute"),
            (re.compile(r"^\s*Danke fürs Zuhören[.!?]?\s*$", re.IGNORECASE), "Danke fürs Zuhören"),
            (re.compile(r"^\s*See you later[.!?]?\s*$", re.IGNORECASE), "See you later"),
            (re.compile(r"^\s*you[.!?]?\s*$", re.IGNORECASE), "you")
        ]

        # Read clipboard delay from environment variable, default to 0.05
        self.clipboard_delay = float(os.getenv('CLIPBOARD_DELAY', '0.05'))

    def contains_filter_phrase(self, text):
        """Check if text contains any filter phrases."""
        for pattern, description in self.exclusion_patterns:
            if pattern.search(text):
                logger.info(f"🚫 Filter phrase detected: '{description}' in text: '{text}'")
                return True
        return False

    def clean_output_text(self, text):
        # Check if text contains filter phrases - if so, return empty string to suppress paste
        if self.contains_filter_phrase(text):
            logger.info("🚫 Filter phrase detected - suppressing paste")
            return ""
        # Otherwise return the text as-is
        return text.strip()

    def get_content(self):
        """Reads text content from the system clipboard using pbpaste."""
        logger.debug("📋 Attempting to read clipboard content...")
        try:
            process = subprocess.run(
                ['pbpaste'],
                capture_output=True,
                text=True, 
                check=False, 
                timeout=1 
            )
            if process.returncode == 0:
                clipboard_text = process.stdout.strip()
                logger.info(f"📋✅ Read clipboard content (Length: {len(clipboard_text)}).")
                return self.clean_output_text(clipboard_text)
            else:
                logger.warning(f"📋⚠️ pbpaste returned non-zero code ({process.returncode}). Assuming empty or non-text clipboard. Stderr: {process.stderr.strip()}")
                return ""
        except FileNotFoundError:
             logger.error("📋❌ pbpaste not found (macOS only). Cannot read clipboard.")
             return None
        except subprocess.TimeoutExpired:
             logger.error("📋❌ pbpaste command timed out.")
             return None
        except Exception as e:
            logger.error(f"📋💥 Unexpected error reading clipboard: {e}")
            return None

    def copy(self, text):
        """Copies the given text to the system clipboard using pbcopy."""
        if not text:
            logger.debug("Skipping clipboard copy for empty text.")
            return False # Indicate failure
        try:
            subprocess.run(['pbcopy'], input=text.encode('utf-8'), check=True)
            logger.info(f"📋✅ Copied text to clipboard (Length: {len(text)}).")
            return True # Indicate success
        except FileNotFoundError:
             logger.error("📋❌ pbcopy not found (macOS only). Cannot copy text.")
        except subprocess.CalledProcessError as e:
            logger.error(f"📋❌ Failed to copy text (pbcopy): {e}")
        except Exception as e:
            logger.error(f"📋💥 Unexpected error copying text: {e}")
        return False # Indicate failure

    def copy_and_paste(self, text, send_enter=False):
        """Copies the given text and then simulates Cmd+V paste."""
        if not text:
            logger.debug("Skipping copy/paste for empty text.")
            return False
        
        try:
            # Check for filter phrases first
            if self.contains_filter_phrase(text):
                logger.info("🚫 Filter phrase detected - suppressing entire paste")
                return False
            
            # Copy text as-is (no cleaning/removal)
            copy_success = self.copy(text)
            
            if not copy_success:
                logger.warning("Skipping paste because copy failed.")
                return False
                
            # Allow a tiny moment for clipboard to update system-wide using configurable delay
            time.sleep(self.clipboard_delay)
            
            # Perform paste
            paste_success = self.paste_cmd_v()
            
            if paste_success:
                logger.info("✅ Copy and paste completed successfully")
                
                # Send Enter if requested
                if send_enter:
                    time.sleep(self.clipboard_delay)
                    self._send_enter()
                    logger.info("⏎ Sent Enter after paste")
                
                return True
            else:
                logger.error("❌ Paste failed after successful copy")
                return False
                
        except Exception as e:
            logger.error(f"💥 Error during copy/paste operation: {e}")
            return False

    def _simulate_keystroke(self, action_name, key_action_func):
        """Internal helper to simulate keystrokes with suppression and error handling."""
        if not self.kb_controller:
            logger.error(f"⌨️❌ pynput Controller not available. Cannot simulate {action_name}.")
            return False

        try:
            # Suppress hotkeys before action
            self.owner.suppress_hotkeys(True)
            logger.debug(f"🔒 Hotkey suppression enabled for {action_name}")
            
            # Perform the action
            key_action_func(self.kb_controller)
            logger.debug(f"⌨️✅ {action_name} simulation successful")
            
            # Add a small delay after action using configurable delay
            time.sleep(self.clipboard_delay)
            
            return True
            
        except Exception as e:
            logger.error(f"⌨️❌ Error during {action_name} simulation: {e}")
            return False
            
        finally:
            # Always re-enable hotkeys
            time.sleep(self.clipboard_delay)  # Use configurable delay for better reliability
            self.owner.suppress_hotkeys(False)
            logger.debug(f"🔓 Hotkey suppression disabled after {action_name}")

    def paste_cmd_v(self):
        """Simulates Cmd+V keystroke."""
        def action(kb):
            with kb.pressed(Key.cmd):
                kb.press('v')
                kb.release('v')
        return self._simulate_keystroke("Cmd+V Paste", action)

    def backspace(self):
        """Simulates a Backspace key press."""
        def action(kb):
            kb.press(Key.backspace)
            kb.release(Key.backspace)
        return self._simulate_keystroke("Backspace", action)
    
    def _send_enter(self):
        """Simulates an Enter key press."""
        def action(kb):
            kb.press(Key.enter)
            kb.release(Key.enter)
        return self._simulate_keystroke("Enter", action)
 
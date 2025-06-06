import logging
import subprocess
import time
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

    def clean_output_text(self, text):
        exclusion_phrases = [
            r"\bthanks? for watching\b",
            r"\bthank you\b",
            r"\byou\b"
        ]
        # Remove phrases and any trailing punctuation/spaces
        def remove_phrases(s):
            s_clean = s
            for pattern in exclusion_phrases:
                # Match phrase plus any trailing punctuation and whitespace
                s_clean = re.sub(pattern + r'[.!?,;:…\s]*', '', s_clean, flags=re.IGNORECASE)
            # Remove extra spaces left by removals
            return re.sub(r'\s+', ' ', s_clean).strip()
        return remove_phrases(text)

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

    def _simulate_keystroke(self, action_name, key_action_func):
        """Internal helper to simulate keystrokes with suppression and error handling."""
        if not self.kb_controller:
            logger.error(f"⌨️❌ pynput Controller not available. Cannot simulate {action_name}.")
            return False

        try:
            self.owner.suppress_hotkeys(True) # Call owner method
            logger.debug(f"🔒 Requesting hotkey suppression for {action_name} simulation.")
            key_action_func(self.kb_controller)
            logger.debug(f"⌨️✅ {action_name} simulation successful.")
            return True
        except Exception as e:
            logger.error(f"⌨️❌ Error during {action_name} simulation: {e}")
            return False
        finally:
            time.sleep(0.05) # Delay before re-enabling listener
            self.owner.suppress_hotkeys(False) # Call owner method
            logger.debug(f"🔓 Requesting hotkey unsuppression after {action_name} simulation.")

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
        # Use a slightly shorter delay for backspace potentially
        # Note: Delay is now handled in the _simulate_keystroke finally block
        return self._simulate_keystroke("Backspace", action)

    def copy_and_paste(self, text):
        """Copies the given text and then simulates Cmd+V paste."""
        if not text:
            logger.debug("Skipping copy/paste for empty text.")
            return False
        
        copy_success = self.copy(self.clean_output_text(text))
        paste_success = False
        if copy_success:
            # Allow a tiny moment for clipboard to update system-wide
            time.sleep(0.05)
            paste_success = self.paste_cmd_v()
            if paste_success and self.kb_controller:
                time.sleep(0.05)
                # self.kb_controller.press(Key.enter)
                # self.kb_controller.release(Key.enter)
        else:
            logger.warning("Skipping paste because copy failed.")
            
        return copy_success and paste_success 
 
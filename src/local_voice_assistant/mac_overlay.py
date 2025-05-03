import logging
import subprocess
import threading
import shutil
import os

# Get a logger for this module
logger = logging.getLogger(__name__)

# Removed icon path calculation
# PROJECT_ROOT = ...
# ICON_FILENAME = ...
# EXPECTED_ICON_PATH = ...

class MacNotification:
    """Uses macOS notification system to display assistant status."""
    
    def __init__(self):
        logger.debug("MacNotification initializing...")
        self._last_message = None
        
        # Check if terminal-notifier is available, if not, fall back to osascript
        self.use_terminal_notifier = shutil.which('terminal-notifier') is not None
        if self.use_terminal_notifier:
            logger.debug("Using terminal-notifier for notifications")
        else:
            logger.debug("terminal-notifier not found, using osascript")
            
        logger.debug("MacNotification initialized.")
    
    def show_message(self, text, group_id='voice-assistant-status', duration=None):
        """Displays a macOS notification with the given text.
        
        Args:
            text: The message content.
            group_id: The group ID for terminal-notifier. Notifications with the same
                      group ID replace each other. Set to None to show independently.
            duration: (Ignored) Added for interface compatibility.
        """
        # Log if duration is provided but ignored
        if duration is not None:
             logger.debug(f"Duration ({duration}s) provided but ignored by MacNotification.")
             
        self._last_message = text
        logger.debug(f"Showing notification: '{text}' (Group: {group_id})")

        lower_text = text.lower()
        
        try:
            # Create a more descriptive notification with emoji indicators
            emoji = "🎙️"
            if "processing your request" in lower_text:
                emoji = "⚙️"
            elif text.endswith("..."):
                emoji = "🎙️"
            elif "pasted" in lower_text:
                emoji = "✅"
            elif "recording stopped" in lower_text:
                emoji = "❌"
            elif "language" in lower_text or "detected" in lower_text:
                emoji = "🔍"
            
            message = f"{emoji} {text}"
            
            if self.use_terminal_notifier:
                # Simplified command - no icon, no subtitle
                cmd_base = [
                    'terminal-notifier',
                    '-title', 'Voice Assistant',
                    '-message', message,
                    '-sound', 'none' # Explicitly disable sound
                ]
                
                # Removed icon existence check and -appIcon argument
                
                # Add group ID only if it's provided
                if group_id:
                    cmd = cmd_base + ['-group', group_id]
                else:
                    cmd = cmd_base
                    
                subprocess.run(cmd, check=False)
                logger.debug("terminal-notifier command sent successfully")
            else:
                # Basic AppleScript notification as fallback (no easy replacement for icon/subtitle)
                script = f'''
                tell application "System Events"
                    set volume alert volume 0
                    display notification "{message}" with title "Voice Assistant"
                    delay 0.5
                    set volume alert volume 100
                end tell
                '''
                subprocess.run(['osascript', '-e', script], check=False)
                logger.debug("osascript notification sent successfully")
                
        except Exception as e:
            logger.error(f"Failed to show notification: {e}")
    
    def hide_overlay(self, group_id=None):
        """macOS notifications auto-hide, so this is just a placeholder.
        
        Args:
             group_id: (Ignored) Added for interface compatibility.
        """
        # Log if group_id is provided but ignored
        if group_id is not None:
             logger.debug(f"Hide called with group_id ('{group_id}') but ignored by MacNotification.")
        else:
            logger.debug("Hide called (notifications auto-hide)")
        pass

# Global instance for singleton pattern
_notification_instance = None

def get_overlay_instance():
    """Returns a singleton instance of the MacNotification class."""
    global _notification_instance
    
    if _notification_instance is None:
        logger.debug("Creating new MacNotification instance")
        _notification_instance = MacNotification()
    
    return _notification_instance

# Test if run directly
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG, 
                        format="%(asctime)s [%(levelname)-7s] %(name)s: %(message)s")
    
    logger.info("Testing MacNotification...")
    notifier = get_overlay_instance()
    notifier.show_message("Recording...")
    
    # Wait a bit and show another notification
    import time
    time.sleep(2)
    # Test independent notification
    notifier.show_message("Independent Message", group_id=None)
    time.sleep(2)
    notifier.show_message("Transcribing...") # This should replace the first one 

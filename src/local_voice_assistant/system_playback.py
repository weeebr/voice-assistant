import logging
import platform
import subprocess

logger = logging.getLogger(__name__)

class SystemPlaybackManager:
    """Manages pausing and resuming system playback (Music, Spotify, Chrome YouTube)."""

    # AppleScript for native apps
    _APPLE_SCRIPT_PAUSE = """
    # Music
    try
        if application "Music" is running then
            tell application "Music" to pause
        end if
    end try
    # Spotify
    try
        if application "Spotify" is running then
            tell application "Spotify" to pause
        end if
    end try
    """
    
    _APPLE_SCRIPT_RESUME = """
    # Music
    try
        if application "Music" is running then
            tell application "Music" to play
        end if
    end try
    # Spotify
    try
        if application "Spotify" is running then
            tell application "Spotify" to play
        end if
    end try
    """

    # JXA for Chrome/YouTube (Reverted to simpler Beta-only version)
    _JXA_PAUSE_CHROME_YT = """ 
    (() => {
      try {
        const chrome = Application('Google Chrome Beta');
        if (!chrome.running()) { return; }
        chrome.windows().forEach((w) => {
          try {
            w.tabs().forEach((t) => {
              const url = t.url();
              if (url && url.includes('youtube.com/watch')) {
                try {
                  t.execute({javascript: "document.querySelector('video').pause();"});
                } catch (e) { console.log('JS pause error: ' + e); }
              }
            });
          } catch (e) { /* Maybe not a browser window */ }
        });
      } catch (e) { console.log('Chrome JXA error: ' + e); }
    })();
    """
    
    _JXA_RESUME_CHROME_YT = """
    (() => {
      try {
        const chrome = Application('Google Chrome Beta');
        if (!chrome.running()) { return; }
        chrome.windows().forEach((w) => {
          try {
            w.tabs().forEach((t) => {
              const url = t.url();
              if (url && url.includes('youtube.com/watch')) {
                try {
                  t.execute({javascript: "document.querySelector('video').play();"});
                } catch (e) { console.log('JS play error: ' + e); }
              }
            });
          } catch (e) { /* Maybe not a browser window */ }
        });
      } catch (e) { console.log('Chrome JXA error: ' + e); }
    })();
    """

    def __init__(self):
        # Check if on macOS, as scripts are platform-specific
        self.is_macos = platform.system() == "Darwin"
        if not self.is_macos:
            logger.warning("System playback control is only supported on macOS.")
        self.system_playback_paused = False # Internal state if we initiated pause

    def pause(self):
        """Attempts to pause Music, Spotify, and YouTube playback."""
        if not self.is_macos:
            logger.debug("Skipping system playback pause (not on macOS).")
            return False # Indicate pause was not attempted

        logger.debug("Attempting to pause system playback...")
        paused_apple_apps = False
        try:
            # 1. Pause Music/Spotify via AppleScript
            logger.debug("Attempting AppleScript pause for Music/Spotify...")
            process_as = subprocess.run(
                ['osascript', '-e', self._APPLE_SCRIPT_PAUSE],
                capture_output=True, text=True, check=False, timeout=2
            )
            logger.debug(f"AppleScript pause result: code={process_as.returncode}, stdout='{process_as.stdout.strip()}', stderr='{process_as.stderr.strip()}'")
            if process_as.returncode == 0:
                logger.info("⏯️ Music/Spotify pause command potentially succeeded (exit code 0).")
                paused_apple_apps = True
            else:
                logger.warning(f"⏯️ Music/Spotify pause AS likely failed (code {process_as.returncode}): {process_as.stderr or process_as.stdout}")
        except Exception as e:
            logger.error(f"⏯️ Unexpected error pausing Music/Spotify (AS): {e}")

        paused_jxa_apps = False
        try:
             # 2. Pause Chrome/YouTube via JXA
            process_jxa = subprocess.run(
                ['osascript', '-l', 'JavaScript'],
                input=self._JXA_PAUSE_CHROME_YT, 
                capture_output=True, text=True, check=False, timeout=3
            )
            if process_jxa.returncode == 0:
                logger.info("⏯️ Chrome/YouTube pause command sent.")
                paused_jxa_apps = True
            else:
                # Log JXA stdout/stderr as it might contain console.log output from script
                jxa_output = (process_jxa.stdout or process_jxa.stderr or "").strip()
                logger.warning(f"⏯️ Chrome/YouTube pause JXA may have failed (code {process_jxa.returncode}): {jxa_output}")
        except Exception as e:
            logger.error(f"⏯️ Unexpected error pausing Chrome/YouTube (JXA): {e}")
            
        # Set internal state only if at least one pause attempt seemed okay
        self.system_playback_paused = paused_apple_apps or paused_jxa_apps
        if not self.system_playback_paused:
             logger.warning("⏯️ Failed to pause any media application.")
        return self.system_playback_paused # Return overall pause status

    def resume(self):
        """Attempts to resume Music, Spotify, and YouTube playback if previously paused by this manager."""
        if not self.is_macos:
            logger.debug("Skipping system playback resume (not on macOS).")
            return
        
        # Only attempt resume if we think we paused it
        if not self.system_playback_paused:
            logger.debug("Skipping system playback resume (was not paused by this manager).")
            return
            
        logger.debug("Attempting to resume system playback...")
        try:
            # 1. Resume Music/Spotify via AppleScript
            logger.debug("Attempting AppleScript resume for Music/Spotify...")
            process_as = subprocess.run(
                ['osascript', '-e', self._APPLE_SCRIPT_RESUME],
                capture_output=True, text=True, check=False, timeout=5
            )
            logger.debug(f"AppleScript resume result: code={process_as.returncode}, stdout='{process_as.stdout.strip()}', stderr='{process_as.stderr.strip()}'")
            if process_as.returncode == 0:
                logger.info("▶️ Music/Spotify resume command potentially succeeded (exit code 0).")
            else:
                logger.warning(f"▶️ Music/Spotify resume AS likely failed (code {process_as.returncode}): {process_as.stderr or process_as.stdout}")
        except Exception as e:
            logger.error(f"▶️ Unexpected error resuming Music/Spotify (AS): {e}")

        try:
            # 2. Resume Chrome/YouTube via JXA
            process_jxa = subprocess.run(
                ['osascript', '-l', 'JavaScript'],
                input=self._JXA_RESUME_CHROME_YT, 
                capture_output=True, text=True, check=False, timeout=3
            )
            if process_jxa.returncode == 0:
                logger.info("▶️ Chrome/YouTube resume command sent.")
            else:
                jxa_output = (process_jxa.stdout or process_jxa.stderr or "").strip()
                logger.warning(f"▶️ Chrome/YouTube resume JXA may have failed (code {process_jxa.returncode}): {jxa_output}")
        except Exception as e:
            logger.error(f"▶️ Unexpected error resuming Chrome/YouTube (JXA): {e}")
        finally:
            # Always reset the internal flag after attempting resume
            self.system_playback_paused = False
            logger.debug("Reset internal playback paused flag.") 

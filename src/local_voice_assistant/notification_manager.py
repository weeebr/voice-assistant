import logging
import numpy as np
import sounddevice as sd
import threading
import time # Potentially useful for delayed notifications later

logger = logging.getLogger(__name__)

class NotificationManager:
    """
    Manages user notifications, including overlay messages and audio cues.
    """
    def __init__(self, config, overlay, audio_capture):
        logger.debug("NotificationManager initializing...")
        self.config = config
        self.overlay = overlay # Store the overlay instance
        
        # Determine sample rate for beep, falling back to a default
        self.beep_sample_rate = 16000
        if audio_capture:
            try:
                self.beep_sample_rate = audio_capture.sample_rate
                logger.debug(f"Using sample rate from AudioCapture: {self.beep_sample_rate}")
            except AttributeError:
                logger.warning("AudioCapture instance provided, but no sample_rate attribute found. Using default.")
        else:
            logger.warning("No AudioCapture instance provided to NotificationManager. Using default sample rate for beep.")
        
        # Read beep configuration (optional)
        self.beep_frequency = config.get('beep_frequency', 440)
        self.beep_duration = config.get('beep_duration', 0.1)
        self.beep_amplitude = config.get('beep_amplitude', 0.38)
        
        logger.info(f"✅ NotificationManager initialized. Overlay enabled: {self.overlay is not None}")

    def play_beep(self):
        """Generates and plays a short beep sound in a separate thread."""
        logger.debug(f"Attempting to play beep (Freq: {self.beep_frequency}Hz, Dur: {self.beep_duration}s)")
        try:
            t = np.linspace(0., self.beep_duration, int(self.beep_sample_rate * self.beep_duration), endpoint=False)
            waveform = self.beep_amplitude * np.sin(2. * np.pi * self.beep_frequency * t)
            waveform = waveform.astype(np.float32)
            
            # Play in a separate thread so it doesn't block
            threading.Thread(target=self._play_sound_async, args=(waveform, self.beep_sample_rate), daemon=True).start()
            
        except ImportError:
             logger.error("🔊 Error playing beep: sounddevice or numpy not installed?")
        except Exception as e:
            logger.error(f"🔊 Error generating or initiating beep sound: {e}")
            
    def _play_sound_async(self, waveform, samplerate):
        """Internal method to play sound using sounddevice."""
        try:
            sd.play(waveform, samplerate)
            sd.wait() # Wait for playback to finish in this thread
            logger.debug("🔊 Beep finished.")
        except Exception as e:
            logger.error(f"🔊 Error during sounddevice playback: {e}")

    def show_message(self, message, duration=None, group_id="assistant_message"):
        """Shows a message on the overlay if available."""
        if self.overlay:
            logger.debug(f"NM showing overlay: '{message}' (Duration: {duration}, Group: {group_id})")
            try:
                # Pass duration and group_id if overlay supports them
                self.overlay.show_message(message, duration=duration, group_id=group_id)
            except TypeError:
                 # Fallback for older overlay implementations that might not accept duration/group_id
                 try:
                     logger.warning("Overlay show_message might not support duration/group_id. Falling back.")
                     self.overlay.show_message(message)
                 except Exception as e_fallback:
                     logger.error(f"❌ Error showing overlay message (fallback attempt): {e_fallback}")
            except Exception as e:
                # Handle other errors during the primary show_message call
                logger.error(f"❌ Error showing overlay message: {e}")
        else:
            logger.warning("Overlay not available, cannot show message.")

    def hide_overlay(self, group_id="assistant_message"):
        """Hides the overlay message group if available."""
        if self.overlay:
            logger.debug(f"NM hiding overlay group: {group_id}")
            try:
                # Assuming hide_overlay might take a group_id to clear specific messages
                self.overlay.hide_overlay(group_id=group_id)
            except TypeError:
                 # Fallback for older overlay implementations
                 try:
                     logger.warning("Overlay hide_overlay might not support group_id. Falling back.")
                     self.overlay.hide_overlay()
                 except Exception as e_fallback:
                     logger.error(f"❌ Error hiding overlay (fallback attempt): {e_fallback}")
            except Exception as e:
                logger.error(f"❌ Error hiding overlay: {e}")
        else:
            logger.debug(f"Overlay not available. Skipping hide.") 
 
import threading
import time
import logging
import numpy as np
import sounddevice as sd

# Get a logger instance for this module
logger = logging.getLogger(__name__)

class AudioRecorder:
    """
    Handles the audio recording stream, PTT duration check for pausing, 
    and interaction with the PlaybackManager.
    """
    def __init__(self, audio_capture, min_pause_duration, playback_manager):
        """
        Initializes the AudioRecorder.

        Args:
            audio_capture: An instance of AudioCapture for getting the stream.
            min_pause_duration: The minimum recording duration before attempting to pause playback.
            playback_manager: An instance of SystemPlaybackManager to pause/resume playback.
        """
        logger.debug("AudioRecorder initializing...")
        self.audio_capture = audio_capture
        self.min_pause_duration = min_pause_duration
        self.playback_manager = playback_manager
        
        self.recording_thread = None
        self.stop_event = threading.Event()
        self.frames = []
        self.start_time = None
        self.duration = 0
        self.pause_timer_triggered = False
        
        logger.debug("AudioRecorder initialized.")

    def start_recording(self):
        """Starts the recording process in a separate thread."""
        if self.recording_thread and self.recording_thread.is_alive():
            logger.warning("AudioRecorder: Recording already in progress.")
            return self.recording_thread # Return existing thread
            
        # --- REMOVE Playback Pause --- 
        # Playback control is now handled conditionally by Orchestrator
        # logger.debug("AudioRecorder: Pausing system playback...")
        # self.playback_manager.pause() 
        # ---------------------------
        
        self.frames = []
        self.start_time = time.monotonic()
        self.stop_event.clear()
        self.recording_thread = threading.Thread(target=self._recording_loop, daemon=True)
        self.recording_thread.start()
        logger.info("AudioRecorder: Recording thread started.")
        return self.recording_thread

    def stop_recording(self):
        """Signals the recording thread to stop and returns the recorded data."""
        # Placeholder - Logic will be moved from Orchestrator
        logger.info("🖐️ Recording STOP signaled.")
        if self.recording_thread and self.recording_thread.is_alive():
            self.stop_event.set()
            # Join logic will likely happen in Orchestrator callback
            # Return frames and duration here after join
            logger.debug("Waiting for recording thread to finish...")
            self.recording_thread.join(timeout=1.0) # Short timeout, actual join may need to be longer
            if self.recording_thread.is_alive():
                logger.warning("⚠️ Recording thread join timed out in stop_recording.")
            else:
                logger.debug("Recording thread finished.")
        
        # Return collected data
        return self.frames, self.duration

    def _recording_loop(self):
        """The main loop that captures audio frames."""
        # Placeholder - Logic will be moved from Orchestrator
        logger.debug("🎧 Recording loop thread started.")
        stream = None
        
        if self.start_time is None:
             logger.warning("⚠️ Recording loop started without valid start time.")
             return 

        try:
            stream = self.audio_capture.speech_audio_stream()
            logger.debug("🔊 Audio stream opened for PTT recording.")

            while not self.stop_event.is_set():
                 # --- REMOVE Check for duration-based pause --- 
                 # Playback pausing is now handled EXCLUSIVELY by Orchestrator
                 # based on the Ctrl key state.
                 # now = time.monotonic()
                 # elapsed = now - self.start_time
                 # if not self.pause_timer_triggered and elapsed >= self.min_pause_duration:
                 #     logger.info(f"⏱️ Recording duration threshold reached ({self.min_pause_duration}s). Attempting pause.")
                 #     paused_successfully = self.playback_manager.pause() # Use injected manager
                 #     if paused_successfully:
                 #         self.pause_timer_triggered = True 
                 # -------------------------------------

                 try:
                     frame = next(stream)
                     self.frames.append(frame) # Store frames in instance variable
                 except StopIteration:
                     logger.warning("⚠️ Audio stream ended unexpectedly during loop.")
                     break 
            
            logger.debug(f"🏁 Recording loop finished. Captured {len(self.frames)} frames.")

        except Exception as e:
             logger.exception(f"💥 Error during recording stream: {e}")
        finally:
             if hasattr(stream, 'close'):
                 try:
                      logger.debug("🔇 Attempting to close audio stream.")
                      stream.close()
                      logger.debug("🔇 Audio stream closed.")
                 except Exception as e:
                      logger.error(f"❌ Error closing audio stream: {e}")
             
             # Calculate and store duration
             end_time = time.monotonic()
             self.duration = end_time - self.start_time
             logger.debug(f"Recording loop calculated duration: {self.duration:.2f}s")
             # Result (frames, duration) will be retrieved via stop_recording
 
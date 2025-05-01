import numpy as np
import logging
import os
import sys
from faster_whisper import WhisperModel

logger = logging.getLogger(__name__) # Use module-specific logger

class SpeechToText:
    """
    Wrapper around Faster Whisper for real-time transcription.
    Yields transcribed segments progressively.
    """
    def __init__(self, model_size='tiny', device='cpu', compute_type='int8', beam_size=1):
        logger.debug(f"Initializing WhisperModel (size={model_size}, device={device}, compute={compute_type})")
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.beam_size = beam_size
        logger.debug("WhisperModel initialized.")

    def transcribe(self, frames, language=None):
        """
        Transcribes a list of PCM frames (bytes) and yields Segment objects progressively.

        Args:
            frames: List of audio frames (bytes).
            language: Optional language code (e.g., 'en', 'de') to force.

        Yields:
            Segment: Objects representing transcribed audio segments.
        """
        if not frames:
            logger.warning("Transcribe called with no frames.")
            return # Stop iteration immediately if no frames

        try:
            # Combine frames into a single float32 numpy array (Whisper format)
            audio = np.concatenate([
                np.frombuffer(f, dtype=np.int16) for f in frames
            ]).astype(np.float32) / 32768.0
        except ValueError as e:
            logger.error(f"Error combining audio frames (maybe empty list?): {e}")
            return

        logger.debug(f"Starting transcription (audio length: {len(audio)/16000:.2f}s, lang hint: {language})")

        # Suppress faster-whisper console output during transcription
        devnull = os.open(os.devnull, os.O_RDWR)
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        old_stdout = os.dup(stdout_fd)
        old_stderr = os.dup(stderr_fd)

        try:
            os.dup2(devnull, stdout_fd)
            os.dup2(devnull, stderr_fd)

            # Get the segment generator from the model
            segments_generator, info = self.model.transcribe(
                    audio,
                    beam_size=self.beam_size,
                    language=language
                )

            logger.debug(f"Detected language: {info.language} (probability: {info.language_probability:.2f})")
            logger.debug("Yielding segments...")

            segment_count = 0
            # Iterate through the generator and yield each segment
            for segment in segments_generator:
                logger.debug(f"Yielding segment [{segment.start:.2f}s - {segment.end:.2f}s]: {segment.text}")
                yield segment
                segment_count += 1
            logger.debug(f"Finished yielding {segment_count} segments.")

        except Exception as e:
            logger.exception(f"Error during Whisper transcription: {e}")
            # Optionally, yield a special object or raise an exception
        finally:
            # Ensure stdout/stderr are restored even if errors occur
            try:
                os.dup2(old_stdout, stdout_fd)
                os.dup2(old_stderr, stderr_fd)
                os.close(devnull)
                os.close(old_stdout)
                os.close(old_stderr)
                logger.debug("Restored stdout/stderr.")
            except OSError as e:
                 logger.error(f"Error restoring std streams: {e}")

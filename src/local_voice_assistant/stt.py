import numpy as np
import logging
from faster_whisper import WhisperModel

class SpeechToText:
    """
    Wrapper around Faster Whisper for real-time transcription.
    """
    def __init__(self, model_size='small', device='cpu', compute_type='int8', beam_size=1):
        self.model = WhisperModel(model_size, device=device, compute_type=compute_type)
        self.beam_size = beam_size

    def transcribe(self, frames, language=None, return_segments=False):
        """
        Transcribe a list of PCM frames (bytes) and return concatenated text.
        Optionally force transcription language (two-letter code, e.g., 'en', 'de').
        If return_segments is True, also return the list of segments: (segments, text).
        """
        # Combine frames into a single int16 numpy array
        audio = np.concatenate([
            np.frombuffer(f, dtype=np.int16) for f in frames
        ]).astype(np.float32) / 32768.0
        # Suppress faster-whisper console output at the OS file-descriptor level
        import os, sys
        # Open null device
        devnull = os.open(os.devnull, os.O_RDWR)
        # Backup original stdout/stderr file descriptors
        stdout_fd = sys.stdout.fileno()
        stderr_fd = sys.stderr.fileno()
        old_stdout = os.dup(stdout_fd)
        old_stderr = os.dup(stderr_fd)
        try:
            # Redirect stdout and stderr to null
            os.dup2(devnull, stdout_fd)
            os.dup2(devnull, stderr_fd)
            # Force language if provided (ISO 639-1 code, e.g., 'de', 'en')
            if language:
                segments, _ = self.model.transcribe(
                    audio,
                    beam_size=self.beam_size,
                    language=language
                )
            else:
                segments, _ = self.model.transcribe(
                    audio,
                    beam_size=self.beam_size
                )
        finally:
            # Restore original descriptors and clean up
            os.dup2(old_stdout, stdout_fd)
            os.dup2(old_stderr, stderr_fd)
            os.close(devnull)
            os.close(old_stdout)
            os.close(old_stderr)
        # Materialize segments (generator) into a list for reuse
        segments = list(segments)
        # Debug: log each segment's time range and text
        for seg in segments:
            logging.debug(f"Transcribed segment [{seg.start:.2f}s - {seg.end:.2f}s]: {seg.text}")
        text = ''.join(seg.text for seg in segments)
        logging.debug(f"Full transcription: {text}")
        if return_segments:
            return segments, text
        return text
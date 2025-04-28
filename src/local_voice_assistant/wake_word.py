import numpy as np
import pvporcupine
import logging

class WakeWordDetector:
    """
    Detects wake-word using Picovoice Porcupine.
    """
    def __init__(self, access_key, keyword_paths, sensitivities=None):
        """
        Initialize Porcupine wake-word detector.
        keyword_paths: list of .ppn model files.
        sensitivities: float or list of floats [0.0,1.0] for each keyword. Higher => more sensitive.
        """
        # Build sensitivity list matching keywords
        if sensitivities is None:
            sens = [0.5] * len(keyword_paths)
        else:
            # Single value for all keywords
            if isinstance(sensitivities, (int, float)):
                sens = [float(sensitivities)] * len(keyword_paths)
            else:
                # Assume list/tuple of sensitivities
                sens = list(map(float, sensitivities))
                if len(sens) != len(keyword_paths):
                    raise ValueError(
                        f"Number of sensitivities ({len(sens)}) must match number of keywords ({len(keyword_paths)})"
                    )
        # Store keyword paths for identification of detected keywords
        self.keyword_paths = keyword_paths
        self.pp = pvporcupine.create(
            access_key=access_key,
            keyword_paths=keyword_paths,
            sensitivities=sens
        )

    def process(self, frame_bytes):
        """
        Process a PCM frame (bytes) and return the index of the matched keyword.
        Returns an int >=0 for the index of the keyword in keyword_paths when detected, or -1 otherwise.
        """
        pcm = np.frombuffer(frame_bytes, dtype=np.int16)
        try:
            result = self.pp.process(pcm)
        except Exception as e:
            logging.error(f"Porcupine error: {e}")
            return -1
        # result is index of matched keyword, or -1 if no match
        return result
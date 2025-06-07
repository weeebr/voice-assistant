import numpy as np
import logging
from typing import List, Tuple

logger = logging.getLogger(__name__)

class AudioSegmenter:
    """Handles splitting audio into segments based on silence detection."""
    
    def __init__(self, silence_threshold: float = 0.01, min_segment_length: float = 0.5):
        """
        Initialize the audio segmenter.
        
        Args:
            silence_threshold: Energy threshold for silence detection (0-1)
            min_segment_length: Minimum segment length in seconds
        """
        self.silence_threshold = silence_threshold
        self.min_segment_length = min_segment_length
        self.sample_rate = 16000  # 16kHz audio
        
    def split_audio(self, frames: List[bytes]) -> List[bytes]:
        """
        Split audio into segments based on silence detection.
        
        Args:
            frames: List of audio frames in bytes
            
        Returns:
            List of audio segments in bytes
        """
        try:
            # Convert frames to numpy array
            audio_data = np.concatenate([np.frombuffer(frame, dtype=np.int16) for frame in frames])
            
            # Calculate energy levels
            frame_length = int(0.02 * self.sample_rate)  # 20ms frames
            energy = np.array([
                np.sum(np.square(audio_data[i:i + frame_length].astype(np.float32) / 32768.0))
                for i in range(0, len(audio_data), frame_length)
            ])
            
            # Find silence regions
            is_silence = energy < self.silence_threshold
            
            # Find segment boundaries
            segment_boundaries = []
            in_segment = False
            segment_start = 0
            
            for i, silent in enumerate(is_silence):
                if not silent and not in_segment:
                    # Start of segment
                    in_segment = True
                    segment_start = i
                elif silent and in_segment:
                    # End of segment
                    in_segment = False
                    segment_end = i
                    duration = (segment_end - segment_start) * 0.02  # Convert to seconds
                    
                    if duration >= self.min_segment_length:
                        segment_boundaries.append((segment_start, segment_end))
            
            # Handle last segment if still in one
            if in_segment:
                segment_end = len(is_silence)
                duration = (segment_end - segment_start) * 0.02
                if duration >= self.min_segment_length:
                    segment_boundaries.append((segment_start, segment_end))
            
            # Extract segments
            segments = []
            for start, end in segment_boundaries:
                start_sample = start * frame_length
                end_sample = end * frame_length
                segment = audio_data[start_sample:end_sample]
                segments.append(segment.tobytes())
            
            logger.info(f"Split audio into {len(segments)} segments")
            
            # Fallback: If only one segment, split into fixed-length chunks
            if len(segments) <= 1:
                logger.warning(f"Only {len(segments)} segment(s) found, using fixed-length chunking fallback.")
                chunk_size_sec = 5.0
                chunk_size_samples = int(chunk_size_sec * self.sample_rate)
                segments = []
                for start in range(0, len(audio_data), chunk_size_samples):
                    end = min(start + chunk_size_samples, len(audio_data))
                    segment = audio_data[start:end]
                    if len(segment) > 0:
                        segments.append(segment.tobytes())
                logger.info(f"Fallback chunking produced {len(segments)} segments of ~{chunk_size_sec}s each.")
            
            return segments
            
        except Exception as e:
            logger.error(f"Error splitting audio: {e}")
            return [] 

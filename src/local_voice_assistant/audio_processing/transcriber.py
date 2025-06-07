import logging
from typing import List, Optional
from concurrent.futures import ThreadPoolExecutor
from ..stt import SpeechToText

logger = logging.getLogger(__name__)

class AudioTranscriber:
    """Handles parallel transcription of audio segments."""
    
    def __init__(self, stt: SpeechToText, max_workers: int = 12):
        """
        Initialize the audio transcriber.
        
        Args:
            stt: SpeechToText instance for transcription
            max_workers: Maximum number of parallel workers
        """
        self.stt = stt
        self.max_workers = max_workers
        
    def transcribe_segment(self, segment: bytes, language_hint: Optional[str] = None) -> str:
        """
        Transcribe a single audio segment.
        
        Args:
            segment: Audio segment in bytes
            language_hint: Optional language hint for transcription
            
        Returns:
            Transcribed text or empty string if failed
        """
        try:
            logger.info(f"Transcribing segment of length {len(segment)} bytes")
            # Convert segment to frames (20ms each)
            frame_size = 320  # 20ms at 16kHz
            frames = [segment[i:i + frame_size] for i in range(0, len(segment), frame_size)]
            frames = [f for f in frames if len(f) == frame_size]  # Only complete frames
            
            if not frames:
                logger.warning("No valid frames in segment")
                return ""
                
            # Transcribe segment
            segment_generator = self.stt.transcribe(frames, language=language_hint)
            segment_text = " ".join(segment.text.strip() for segment in segment_generator)
            logger.info(f"Transcription result: '{segment_text}'")
            return segment_text.strip()
            
        except Exception as e:
            logger.error(f"Error transcribing segment: {e}")
            return ""
            
    def transcribe_parallel(self, segments: List[bytes], language_hint: Optional[str] = None) -> List[str]:
        """
        Transcribe multiple segments in parallel.
        
        Args:
            segments: List of audio segments
            language_hint: Optional language hint for transcription
            
        Returns:
            List of transcribed texts
        """
        if not segments:
            return []
            
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # Submit all segments for processing
            future_to_segment = {
                executor.submit(self.transcribe_segment, segment, language_hint): i 
                for i, segment in enumerate(segments)
            }
            
            # Process results as they complete
            results = [""] * len(segments)
            for future in future_to_segment:
                segment_index = future_to_segment[future]
                try:
                    segment_text = future.result()
                    if segment_text:
                        logger.info(f"Segment {segment_index + 1}/{len(segments)} transcribed: '{segment_text}'")
                        results[segment_index] = segment_text
                    else:
                        logger.warning(f"Segment {segment_index + 1}/{len(segments)} produced no text")
                except Exception as e:
                    logger.error(f"Error processing segment {segment_index}: {e}")
                    
            logger.info(f"All segment transcriptions (ordered): {list(enumerate(results))}")
            return results 

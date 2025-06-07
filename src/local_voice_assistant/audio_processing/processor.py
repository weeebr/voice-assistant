import logging
import time
from typing import Dict, List, Optional
from .segmenter import AudioSegmenter
from .transcriber import AudioTranscriber
from ..stt import SpeechToText
from ..notification_manager import NotificationManager
from ..clipboard import ClipboardManager
from ..llm_client import LLMClient
from ..action_executor import ActionExecutor
from ..signal_detector import find_matching_signal
from ..api_client import NERServiceClient

logger = logging.getLogger(__name__)

class AudioProcessor:
    """Main class for processing audio with parallel segment processing."""
    
    def __init__(
        self,
        stt: SpeechToText,
        notification_manager: NotificationManager,
        clipboard_manager: ClipboardManager,
        llm_client: LLMClient,
        ner_service_client: Optional[NERServiceClient] = None,
        transcription_logger = None,
        initial_language: Optional[str] = None,
        max_workers: int = 12,
        silence_threshold: float = 0.01,
        min_segment_length: float = 0.5
    ):
        """
        Initialize the audio processor.
        
        Args:
            stt: SpeechToText instance
            notification_manager: NotificationManager instance
            clipboard_manager: ClipboardManager instance
            llm_client: LLMClient instance
            ner_service_client: Optional NERServiceClient instance
            transcription_logger: Optional logger for transcriptions
            initial_language: Initial STT language
            max_workers: Maximum number of parallel workers
            silence_threshold: Energy threshold for silence detection
            min_segment_length: Minimum segment length in seconds
        """
        self.segmenter = AudioSegmenter(silence_threshold, min_segment_length)
        self.transcriber = AudioTranscriber(stt, max_workers)
        self.notification_manager = notification_manager
        self.clipboard_manager = clipboard_manager
        self.llm_client = llm_client
        self.ner_service_client = ner_service_client
        self.transcription_logger = transcription_logger
        self.default_stt_language = initial_language.split('-')[0] if initial_language else 'en'
        self.max_workers = max_workers
        
        # Load signal configurations
        self.signal_configs = []
        self.commands_by_name = {}
        self._load_signal_configs()
        
        # Initialize action executor
        self.action_executor = ActionExecutor(
            llm_client=self.llm_client,
            ner_service_client=self.ner_service_client,
            clipboard_manager=self.clipboard_manager,
            notification_manager=self.notification_manager
        )
        
    def _load_signal_configs(self):
        """Load signal configurations from config.py."""
        try:
            import config as app_config
            import importlib
            importlib.reload(app_config)
            if hasattr(app_config, 'COMMANDS') and isinstance(app_config.COMMANDS, list):
                self.signal_configs = app_config.COMMANDS
                logger.info(f"✅ Loaded {len(self.signal_configs)} signal configurations from config.py")
                self.commands_by_name = {cfg.get("name"): cfg for cfg in self.signal_configs if cfg.get("name")}
                logger.debug(f"Pre-processed {len(self.commands_by_name)} commands by name.")
            else:
                logger.error("❌ config.py has no 'COMMANDS' list. Signals disabled.")
        except ImportError:
            logger.error("❌ Failed to import config.py. Signals disabled.")
        except Exception as e:
            logger.exception(f"💥 Failed to load signal config from config.py: {e}")
            
    def process_audio(
        self,
        frames: List[bytes],
        current_processing_mode: str,
        current_stt_hint: Optional[str],
        default_processing_mode: str,
        original_frames: Optional[List[bytes]] = None
    ) -> Dict:
        """
        Process audio with parallel segment processing.
        
        Args:
            frames: Audio frames to process
            current_processing_mode: Current processing mode
            current_stt_hint: Current STT language hint
            default_processing_mode: Default processing mode
            original_frames: Original audio frames for potential re-running STT
            
        Returns:
            Dict containing:
            {
                'text_to_paste': str or None,
                'new_processing_mode': str,
                'new_stt_hint': str or None,
                'paste_successful': bool
            }
        """
        logger.info(f"🔄 Starting audio processing (Mode: {current_processing_mode}, Default: {default_processing_mode})...")
        
        # Initialize state
        text_to_paste = None
        paste_successful = False
        new_processing_mode = current_processing_mode
        new_stt_hint = current_stt_hint
        accumulated_raw_text = ""
        
        # Split audio into segments
        segments = self.segmenter.split_audio(frames)
        total_segments = len(segments)
        
        if total_segments == 0:
            logger.warning("No valid segments found in audio")
            return {'paste_successful': False, 'mode': current_processing_mode, 'hint': current_stt_hint}

        logger.info(f"Found {total_segments} audio segments to process")
        
        # Show initial progress
        self.notification_manager.show_message(f"Processing {total_segments} segments...")
        
        # Log segment lengths
        logger.info(f"Segment count: {total_segments}")
        for idx, seg in enumerate(segments):
            logger.info(f"Segment {idx+1} length: {len(seg)} bytes")

        # Process segments in parallel
        start_time = time.time()
        transcribed_texts = self.transcriber.transcribe_parallel(segments, current_stt_hint)

        # Log and stitch all segments
        stitched_segments = []
        for idx, text in enumerate(transcribed_texts):
            if text:
                logger.info(f"Segment {idx+1}/{total_segments} transcription: '{text}'")
                stitched_segments.append(text)
            else:
                logger.warning(f"Segment {idx+1}/{total_segments} was empty!")
                stitched_segments.append("")
        accumulated_raw_text = " ".join(stitched_segments)
        logger.info(f"Raw stitched text: '{accumulated_raw_text}'")
        final_full_sanitized_text = accumulated_raw_text.strip()
        logger.info(f"Sanitized stitched text: '{final_full_sanitized_text}'")

        # Fallback: If any segment is empty, try transcribing the whole audio as one chunk
        if any(not text for text in transcribed_texts):
            logger.warning("At least one segment was empty, retrying transcription as a single chunk.")
            big_segment = b"".join(segments)
            fallback_text = self.transcriber.transcribe_segment(big_segment, current_stt_hint)
            logger.info(f"Fallback transcription: '{fallback_text}'")
            final_full_sanitized_text = fallback_text.strip()

        if not final_full_sanitized_text:
            logger.info("No text transcribed from audio (even after fallback)")
            return {'paste_successful': False, 'mode': current_processing_mode, 'hint': current_stt_hint}
            
        logger.info(f"📝 Full transcription complete (Sanitized): '{final_full_sanitized_text}'")
        
        # Log transcription if logger is available
        if self.transcription_logger:
            self.transcription_logger.info(final_full_sanitized_text)
        
        # Apply output cleaning for filter phrases
        cleaned_text = self.clipboard_manager.clean_output_text(final_full_sanitized_text)
        if not cleaned_text:
            logger.info("🙅‍♀️ Detected only filter words or empty after cleaning, skipping.")
            return {'paste_successful': False, 'mode': current_processing_mode, 'hint': current_stt_hint}
            
        # Check for signal words
        chosen_signal_config, text_for_signal_handler = find_matching_signal(
            cleaned_text,
            self.signal_configs
        )
        
        if chosen_signal_config:
            logger.info(f"🚥 Signal detected: '{chosen_signal_config.get('name', 'Unnamed')}'")
            overlay_msg = chosen_signal_config.get('overlay_message', "Processing signal...")
            self.notification_manager.show_message(overlay_msg)
            
            # Execute signal actions
            action_config_list = chosen_signal_config.get('action', [])
            context = {
                'text': text_for_signal_handler or "",
                'clipboard': self.clipboard_manager.get_content() or ""
            }
            action_results = self.action_executor.execute_actions(action_config_list, context, chosen_signal_config)
            
            # Update state based on action results
            new_processing_mode = action_results.get('new_mode', new_processing_mode)
            new_stt_hint = action_results.get('new_stt_hint', new_stt_hint)
            
            # If we have a new hint, re-run STT
            if new_stt_hint and new_stt_hint != current_stt_hint:
                logger.info(f"🔄 Re-running STT with new hint: '{new_stt_hint}'")
                try:
                    # Re-run STT on original frames
                    transcribed_texts = self.transcriber.transcribe_parallel(segments, new_stt_hint)
                    accumulated_raw_text = " ".join(text for text in transcribed_texts if text)
                    final_full_sanitized_text = accumulated_raw_text.strip()
                    
                    if final_full_sanitized_text:
                        # Strip signal word from re-transcribed text
                        signal_word = chosen_signal_config.get('signal_phrase', [''])[0].lower()
                        signal_pos = final_full_sanitized_text.lower().find(signal_word)
                        if signal_pos != -1:
                            remainder_text = final_full_sanitized_text[signal_pos + len(signal_word):].strip()
                            remainder_text = remainder_text.lstrip(',.?!;: ')
                            cleaned_text = self.clipboard_manager.clean_output_text(remainder_text)
                        else:
                            cleaned_text = self.clipboard_manager.clean_output_text(final_full_sanitized_text)
                except Exception as e:
                    logger.error(f"Failed to re-run STT with new hint: {e}")
                    return {'paste_successful': False, 'mode': current_processing_mode, 'hint': current_stt_hint}
            
            # Process based on new mode
            if cleaned_text:
                if new_processing_mode == 'normal':
                    text_to_paste = cleaned_text
                    paste_successful = True
                elif new_processing_mode == 'llm':
                    self.notification_manager.show_message("🧠 Sending to LLM...")
                    transformed_text = self.llm_client.transform_text(
                        prompt=cleaned_text,
                        notification_manager=self.notification_manager
                    )
                    text_to_paste = transformed_text
                    paste_successful = text_to_paste is not None
                elif new_processing_mode == 'de-CH':
                    self.notification_manager.show_message("🇨🇭 Translating...")
                    translation_command_config = self.commands_by_name.get('mode:de-CH')
                    if translation_command_config and translation_command_config.get('template'):
                        context = {'text': cleaned_text}
                        prompt = translation_command_config['template'].format(**context)
                        model_override = translation_command_config.get('llm_model_override')
                        transformed_text = self.llm_client.transform_text(
                            prompt=prompt,
                            notification_manager=self.notification_manager,
                            model_override=model_override
                        )
                        text_to_paste = transformed_text
                        paste_successful = text_to_paste is not None
                    else:
                        logger.error("Could not find 'mode:de-CH' command config or template for translation.")
                        text_to_paste = f"Error: Config for mode '{new_processing_mode}' missing."
                        paste_successful = False
                else:
                    logger.warning(f"Unknown processing mode '{new_processing_mode}'.")
                    text_to_paste = f"Error: Unknown mode '{new_processing_mode}'"
                    paste_successful = False
            else:
                logger.info("🙅‍♀️ No text after cleaning, skipping output.")
                text_to_paste = None
                paste_successful = False
        else:
            # No signal word found, process in current mode
            if current_processing_mode == 'normal':
                text_to_paste = cleaned_text
                paste_successful = True
            elif current_processing_mode == 'llm':
                self.notification_manager.show_message("🧠 Sending to LLM...")
                transformed_text = self.llm_client.transform_text(
                    prompt=cleaned_text,
                    notification_manager=self.notification_manager
                )
                text_to_paste = transformed_text
                paste_successful = text_to_paste is not None
            elif current_processing_mode == 'de-CH':
                self.notification_manager.show_message("🇨🇭 Translating...")
                translation_command_config = self.commands_by_name.get('mode:de-CH')
                if translation_command_config and translation_command_config.get('template'):
                    context = {'text': cleaned_text}
                    prompt = translation_command_config['template'].format(**context)
                    model_override = translation_command_config.get('llm_model_override')
                    transformed_text = self.llm_client.transform_text(
                        prompt=prompt,
                        notification_manager=self.notification_manager,
                        model_override=model_override
                    )
                    text_to_paste = transformed_text
                    paste_successful = text_to_paste is not None
                else:
                    logger.error("Could not find 'mode:de-CH' command config or template for translation.")
                    text_to_paste = f"Error: Config for mode '{current_processing_mode}' missing."
                    paste_successful = False
            else:
                logger.warning(f"Unknown processing mode '{current_processing_mode}'.")
                text_to_paste = f"Error: Unknown mode '{current_processing_mode}'"
                paste_successful = False

        logger.debug(f"[DEBUG] text_to_paste value before return: '{text_to_paste}'")
        logger.debug(f"[DEBUG] Final Value: paste_successful={paste_successful} before return.")

        return {
            'text_to_paste': text_to_paste,
            'new_processing_mode': new_processing_mode,
            'new_stt_hint': new_stt_hint,
            'paste_successful': paste_successful
        } 

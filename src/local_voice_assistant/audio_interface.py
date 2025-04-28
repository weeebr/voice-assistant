import numpy as np
import platform
try:
    import soundcard as sc
except ImportError:
    sc = None

# Dummy microphone/recorder for environments without soundcard (e.g., tests)
class _DummyRecorder:
    def __init__(self, samplerate, channels):
        self.samplerate = samplerate
        self.channels = channels
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc_val, exc_tb):
        return False
    def record(self, numframes):
        # return silence: zeros of shape (numframes, channels)
        return np.zeros((numframes, self.channels), dtype=np.float32)

class _DummyMic:
    def __init__(self, samplerate, channels):
        self.name = "dummy"
        self.samplerate = samplerate
        self.channels = channels
    def recorder(self, samplerate, channels):
        return _DummyRecorder(samplerate, channels)

class AudioCapture:
    """
    Handles microphone audio capture for wake-word and speech.
    """
    def __init__(self, sample_rate=16000, channels=1, mic_name=None):
        """
        Initialize audio capture. Optionally pick a specific microphone by name (or substring).
        On macOS, if no mic_name is given, defaults to the built-in microphone.
        """
        self.sample_rate = sample_rate
        self.channels = channels
        # Select microphone device (or dummy if soundcard unavailable)
        if sc is None:
            # Use dummy mic/recorder for silent frames
            self.mic = _DummyMic(self.sample_rate, self.channels)
        else:
            # use real soundcard mic
            if mic_name:
                # match by substring in device name
                candidates = [m for m in sc.all_microphones(include_loopback=False)
                              if mic_name.lower() in m.name.lower()]
                if not candidates:
                    raise ValueError(f"Microphone named '{mic_name}' not found")
                self.mic = candidates[0]
            else:
                # on macOS, prefer built-in mic
                if platform.system() == 'Darwin':
                    candidates = [m for m in sc.all_microphones(include_loopback=False)
                                  if 'built-in' in m.name.lower() or 'macbook' in m.name.lower()]
                    self.mic = candidates[0] if candidates else sc.default_microphone()
                else:
                    self.mic = sc.default_microphone()
        # Debug: show selected mic device
        try:
            print(f"Candidates: {[m for m in sc.all_microphones(include_loopback=False)]}")
            print(f"Using microphone: {self.mic.name}", flush=True)
        except Exception:
            pass

    def wake_audio_stream(self):
        """
        Yields raw PCM frames (int16 bytes) of length suitable for Porcupine (512 samples).
        """
        frame_length = 512
        with self.mic.recorder(samplerate=self.sample_rate, channels=self.channels) as rec:
            while True:
                data = rec.record(numframes=frame_length)
                pcm = (data * 32767).astype(np.int16).tobytes()
                yield pcm

    def speech_audio_stream(self):
        """
        Yields raw PCM frames (int16 bytes) for VAD and STT (20 ms frames).
        """
        frame_length = int(self.sample_rate * 0.02)
        with self.mic.recorder(samplerate=self.sample_rate, channels=self.channels) as rec:
            while True:
                data = rec.record(numframes=frame_length)
                pcm = (data * 32767).astype(np.int16).tobytes()
                yield pcm

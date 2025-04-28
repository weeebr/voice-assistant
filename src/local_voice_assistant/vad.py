import webrtcvad

class VAD:
    """
    Voice Activity Detection wrapper using WebRTC VAD.
    """
    def __init__(self, aggressiveness=2):
        self.vad = webrtcvad.Vad(aggressiveness)

    def is_speech(self, frame_bytes):
        """
        Returns True if the given frame (bytes) contains speech.
        Assumes 16 kHz sample rate.
        """
        return self.vad.is_speech(frame_bytes, sample_rate=16000)
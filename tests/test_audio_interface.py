import pytest

from local_voice_assistant.audio_interface import AudioCapture

@pytest.mark.parametrize("method,expected_length", [
    ("wake_audio_stream", 512 * 2),  # 512 samples * 2 bytes
    ("speech_audio_stream", int(0.02 * 16000) * 2)  # 20ms frames * 2 bytes
])
def test_audio_stream_output(method, expected_length):
    cap = AudioCapture()
    stream = getattr(cap, method)()
    frame = next(stream)
    assert isinstance(frame, (bytes, bytearray))
    assert len(frame) == expected_length
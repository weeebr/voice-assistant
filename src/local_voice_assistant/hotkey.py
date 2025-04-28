from pynput import keyboard

class HotkeyListener:
    """
    Global hotkey listener using pynput.
    """
    def __init__(self, key=keyboard.Key.cmd):
        self.key = key
        self.on_press_callback = None
        self.on_release_callback = None

    def start(self):
        listener = keyboard.Listener(
            on_press=self._on_press,
            on_release=self._on_release
        )
        listener.daemon = True
        listener.start()

    def _on_press(self, key):
        if key == self.key and self.on_press_callback:
            self.on_press_callback()

    def _on_release(self, key):
        if key == self.key and self.on_release_callback:
            self.on_release_callback()
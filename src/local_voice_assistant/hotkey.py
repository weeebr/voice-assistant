import logging
import threading
from pynput import keyboard

logger = logging.getLogger(__name__)

class HotkeyManager:
    """Manages the keyboard listener and detects PTT and cancel hotkeys."""

    def __init__(self, ptt_keys, on_ptt_start, on_ptt_stop, on_cancel):
        """Initializes the HotkeyManager.

        Args:
            ptt_keys (set): A set of pynput.keyboard.Key objects that trigger PTT.
            on_ptt_start (callable): Function to call when PTT should start.
            on_ptt_stop (callable): Function to call when PTT should stop.
            on_cancel (callable): Function to call when PTT should be canceled.
        """
        self.ptt_trigger_keys = ptt_keys
        self.on_ptt_start = on_ptt_start
        self.on_ptt_stop = on_ptt_stop
        self.on_cancel = on_cancel

        self.ptt_key_held = False
        self._suppressed = False # Internal suppression state
        self._listener = None
        self._listener_thread = None

        # --- State for Modifier Keys ---
        self._ctrl_held = False 
        # -----------------------------

    def _on_press(self, key):
        """Internal callback for key press events."""
        if self._suppressed:
            # logger.debug("HotkeyManager: Key press suppressed.")
            return True # Allow event propagation if suppressed

        # --- Update Modifier State --- 
        if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
            logger.debug("HotkeyManager: Ctrl key pressed.")
            self._ctrl_held = True
        # ---------------------------

        try:
            # PTT Key Press
            if key in self.ptt_trigger_keys:
                if not self.ptt_key_held:
                    logger.debug("HotkeyManager: PTT key pressed.")
                    self.ptt_key_held = True
                    # --- Pass Ctrl state to callback ---
                    self.on_ptt_start(ctrl_pressed=self._ctrl_held)
                    # -----------------------------------
                # else: PTT key already held, ignore repeat press events

            # Cancel Key Press
            elif key == keyboard.Key.esc:
                if self.ptt_key_held:
                    logger.debug("HotkeyManager: Cancel key pressed while PTT active.")
                    self.ptt_key_held = False # Assume cancel stops the PTT hold
                    self.on_cancel() # Call the callback

        except Exception as e:
            logger.exception(f"HotkeyManager: Error in _on_press: {e}")
        return True # Allow other keys to pass through

    def _on_release(self, key):
        """Internal callback for key release events."""
        if self._suppressed:
            # logger.debug("HotkeyManager: Key release suppressed.")
            return True

        # --- Update Modifier State --- 
        if key == keyboard.Key.ctrl_l or key == keyboard.Key.ctrl_r:
            logger.debug("HotkeyManager: Ctrl key released.")
            self._ctrl_held = False
        # ---------------------------
        
        try:
            # PTT Key Release
            if key in self.ptt_trigger_keys:
                if self.ptt_key_held:
                    logger.debug("HotkeyManager: PTT key released.")
                    self.ptt_key_held = False
                    # --- Pass Ctrl state to callback ---
                    self.on_ptt_stop(ctrl_pressed=self._ctrl_held)
                    # -----------------------------------
                # else: PTT key released but wasn't marked held, ignore

        except Exception as e:
            logger.exception(f"HotkeyManager: Error in _on_release: {e}")
        return True

    def start(self):
        """Starts the keyboard listener in a separate thread."""
        if self._listener_thread is not None and self._listener_thread.is_alive():
            logger.warning("HotkeyManager: Listener already started.")
            return
            
        logger.info("HotkeyManager: Starting keyboard listener...")
        try:
            # Create listener instance just before starting
            self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
            # Use pynput's built-in threading by calling start()
            self._listener.start()
            # We might not need a separate thread variable if listener manages its own.
            # self._listener_thread = threading.Thread(target=self._listener.run, daemon=True)
            # self._listener_thread.start()
            logger.info("HotkeyManager: Keyboard listener started.")
        except Exception as e:
            logger.exception(f"HotkeyManager: Failed to start keyboard listener: {e}")
            self._listener = None # Ensure listener is None if start fails
            # Optionally re-raise or handle error appropriately
            raise

    def stop(self):
        """Stops the keyboard listener."""
        logger.info("HotkeyManager: Stopping keyboard listener...")
        if self._listener:
            try:
                self._listener.stop()
                # Attempt to join the listener's thread if possible/needed
                # pynput's stop() might handle this, depends on implementation
                # if self._listener_thread: self._listener_thread.join(timeout=1.0)
                logger.info("HotkeyManager: Keyboard listener stopped.")
            except Exception as e:
                 logger.error(f"HotkeyManager: Error stopping listener: {e}")
            finally:
                 self._listener = None
                 self._listener_thread = None
        else:
             logger.warning("HotkeyManager: Stop called but listener wasn't running.")
             
    def suppress(self, suppress: bool):
        """Enable or disable suppression of hotkey callbacks."""
        logger.debug(f"HotkeyManager: Setting suppression to {suppress}")
        self._suppressed = suppress 

import logging
import threading
from pynput import keyboard
from enum import Enum, auto
import time

logger = logging.getLogger(__name__)

class HotkeyAction(Enum):
    """Enum for different hotkey actions to make the code more maintainable."""
    PTT_START = auto()
    PTT_STOP = auto()
    CANCEL = auto()
    CTRL_DURING_PTT = auto()
    HELP_OVERLAY = auto()
    STOP_PLAYBACK = auto()
    SEND_ENTER = auto()

class HotkeyManager:
    """Manages the keyboard listener and detects PTT and cancel hotkeys."""

    def __init__(self, ptt_keys, on_ptt_start, on_ptt_stop, on_cancel, on_ctrl_press_during_ptt, on_help_overlay=None, on_stop_playback=None, on_dot_enter=None):
        """Initializes the HotkeyManager."""
        self.ptt_trigger_keys = ptt_keys
        self.on_ptt_start = on_ptt_start
        self.on_ptt_stop = on_ptt_stop
        self.on_cancel = on_cancel
        self.on_ctrl_press_during_ptt = on_ctrl_press_during_ptt
        self.on_help_overlay = on_help_overlay
        self.on_stop_playback = on_stop_playback
        self.on_dot_enter = on_dot_enter

        # Core state
        self.ptt_key_held = False
        self._suppressed = False
        self._listener = None
        self._listener_thread = None
        self._send_enter_after_paste = False

        # Modifier key state
        self._modifier_keys = {
            'option': False,
            'ctrl': False,
            'shift': False,
            'arrow_right': False,
            'arrow_left': False
        }
        self._active_combos = set()
        self._last_action_time = 0
        self._action_cooldown = 0.1  # 100ms cooldown between actionsLet's see if this works, shall we?
        
        self._action_cooldowns = {}

    def _update_key_state(self, key, is_pressed):
        """Update the state of modifier keys."""
        try:
            # Check if this is a PTT trigger key
            if key in self.ptt_trigger_keys:
                logger.debug(f"HotkeyManager: PTT trigger key detected: {key}")
                self.ptt_key_held = is_pressed
            
            # Update arrow key states
            if key == keyboard.Key.left:
                self._modifier_keys['arrow_left'] = is_pressed
            elif key == keyboard.Key.right:
                self._modifier_keys['arrow_right'] = is_pressed
            elif key == keyboard.Key.up:
                self._modifier_keys['arrow_up'] = is_pressed
            elif key == keyboard.Key.down:
                self._modifier_keys['arrow_down'] = is_pressed
            
            # Update modifier key states
            elif key in {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}:
                self._modifier_keys['option'] = is_pressed
            elif key in {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}:
                self._modifier_keys['ctrl'] = is_pressed
            elif key in {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}:
                self._modifier_keys['shift'] = is_pressed
            
            logger.debug(f"HotkeyManager: Current modifier state: {self._modifier_keys}")
            
        except Exception as e:
            logger.error(f"HotkeyManager: Error updating key state: {e}")

    def _trigger_action(self, action_name, action_func, *args):
        """Trigger an action with cooldown protection."""
        current_time = time.time()
        
        # Skip if we're in cooldown for this specific action
        if action_name in self._action_cooldowns:
            last_trigger = self._action_cooldowns[action_name]
            if current_time - last_trigger < self._action_cooldown:
                logger.debug(f"HotkeyManager: Skipping {action_name} due to cooldown")
                return
        
        try:
            logger.debug(f"HotkeyManager: Triggering {action_name}")
            action_func(*args)
            self._action_cooldowns[action_name] = current_time
        except Exception as e:
            logger.error(f"HotkeyManager: Error triggering {action_name}: {e}")

    def _check_hotkey_combos(self):
        """Check for active hotkey combinations and trigger appropriate actions."""
        logger.debug(f"HotkeyManager: Checking combos with state: {self._modifier_keys}")
        
        # Option+Shift: Help Overlay
        if self._modifier_keys['option'] and self._modifier_keys['shift'] and 'option_shift' not in self._active_combos:
            logger.debug("HotkeyManager: Option+Shift combo detected")
            self._active_combos.add('option_shift')
            self._trigger_action("help overlay", self.on_help_overlay, self._modifier_keys['ctrl'])
            # Don't return False here - let PTT continue

        # Option+ArrowRight: Stop Playback
        if self._modifier_keys['option'] and self._modifier_keys['arrow_right'] and 'option_right' not in self._active_combos:
            logger.debug("HotkeyManager: Option+ArrowRight combo detected")
            self._active_combos.add('option_right')
            self._trigger_action("stop playback", self.on_stop_playback, self._modifier_keys['ctrl'])
            # Don't return False here - let PTT continue

        # Option+ArrowLeft: Send Enter after paste
        if self._modifier_keys['option'] and self._modifier_keys['arrow_left'] and 'option_left' not in self._active_combos:
            logger.debug("HotkeyManager: Option+ArrowLeft combo detected")
            self._active_combos.add('option_left')
            self._send_enter_after_paste = True
            self._trigger_action("dot enter", self.on_dot_enter)
            # Don't return False here - let PTT continue

        # Regular PTT (Option key with any modifiers)
        if self._modifier_keys['option'] and self.ptt_key_held:
            # Only trigger PTT start if we're not already recording
            if not self._active_combos.intersection({'ptt_active'}):
                logger.debug("HotkeyManager: Regular PTT detected")
                self._active_combos.add('ptt_active')
                self._trigger_action("PTT start", self.on_ptt_start, self._modifier_keys['ctrl'])
            return True

        return True

    def _on_press(self, key):
        """Handle key press events."""
        if self._suppressed:
            logger.debug(f"HotkeyManager: Suppressed key press: {key}")
            return True

        try:
            logger.debug(f"HotkeyManager: Key pressed: {key}")
            
            # Check for Escape key first - it should override everything
            if key == keyboard.Key.esc:
                logger.debug("HotkeyManager: Escape key detected - cancelling recording")
                self._trigger_action("cancel", self.on_cancel)
                self._reset_state()  # Reset all state
                return True
            
            self._update_key_state(key, True)
            logger.debug(f"HotkeyManager: Current modifier state: {self._modifier_keys}")
            should_continue = self._check_hotkey_combos()
            logger.debug(f"HotkeyManager: Should continue after combo check: {should_continue}")
            return should_continue
        except Exception as e:
            logger.exception(f"HotkeyManager: Exception in _on_press: {e}")
            self._reset_state()
            return True

    def _on_release(self, key):
        """Handle key release events."""
        if self._suppressed:
            logger.debug(f"HotkeyManager: Suppressed key release: {key}")
            return True

        try:
            # Update key state
            self._update_key_state(key, False)
            
            # Handle PTT key release
            if key in self.ptt_trigger_keys:
                self.ptt_key_held = False
                if not self._suppressed:
                    logger.debug("HotkeyManager: PTT key released")
                    # Force PTT stop regardless of cooldown
                    self._action_cooldowns.pop('PTT stop', None)
                    self._active_combos.discard('ptt_active')
                    self._trigger_action("PTT stop", self.on_ptt_stop, self._modifier_keys['ctrl'])
            
            # Clear active combos when modifier keys are released
            if key in {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r}:
                self._active_combos.discard('option_shift')
                self._active_combos.discard('option_right')
                self._active_combos.discard('option_left')
                self._active_combos.discard('ptt_active')
            elif key in {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r}:
                self._active_combos.discard('option_shift')
            elif key == keyboard.Key.left:
                self._active_combos.discard('option_left')
            elif key == keyboard.Key.right:
                self._active_combos.discard('option_right')
            elif key == keyboard.Key.esc:
                self._reset_state()  # Reset all state when Escape is released
            
            return True
        except Exception as e:
            logger.exception(f"HotkeyManager: Exception in _on_release: {e}")
            self._reset_state()
            return True

    def _reset_state(self):
        """Reset all state variables to their default values."""
        self._modifier_keys = {k: False for k in self._modifier_keys}
        self.ptt_key_held = False
        self._active_combos.clear()
        self._send_enter_after_paste = False
        self._last_action_time = 0

    def should_send_enter_after_paste(self):
        """Check if Enter should be sent after paste."""
        return self._send_enter_after_paste

    def clear_enter_after_paste(self):
        """Clear the enter after paste flag."""
        self._send_enter_after_paste = False

    def start(self):
        """Starts the keyboard listener in a separate thread."""
        if self._listener_thread is not None and self._listener_thread.is_alive():
            logger.warning("HotkeyManager: Listener already started.")
            return

        logger.info("HotkeyManager: Starting keyboard listener...")
        try:
            self._listener = keyboard.Listener(
                on_press=self._on_press,
                on_release=self._on_release,
                suppress=False
            )
            self._listener.start()
            self._listener_thread = threading.Thread(target=self._listener.join)
            self._listener_thread.daemon = True
            self._listener_thread.start()
            logger.info("HotkeyManager: Keyboard listener started and running in background thread.")
        except Exception as e:
            logger.exception(f"HotkeyManager: Failed to start keyboard listener: {e}")
            self._listener = None
            raise

    def stop(self):
        """Stops the keyboard listener."""
        logger.info("HotkeyManager: Stopping keyboard listener...")
        if self._listener:
            try:
                self._listener.stop()
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

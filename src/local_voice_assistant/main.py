from .overlay import OverlayManager

class VoiceAssistantApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Voice Assistant")
        self.setGeometry(100, 100, 800, 600)
        
        # Initialize overlay manager
        self.overlay_manager = OverlayManager()
        self.overlay_manager.overlay_created.connect(self._handle_overlay_creation)
        
    def _handle_overlay_creation(self, message: str, duration: int):
        overlay = self.overlay_manager.create_overlay(message, duration)
        
    def closeEvent(self, event):
        self.overlay_manager.cleanup()
        super().closeEvent(event)
        
    def _record_audio(self):
        try:
            # ... existing code ...
            
            # Show overlay for recording
            self.overlay_manager.show_overlay("Recording...", duration=0)
            
            # ... existing code ...
            
            # Show overlay for processing
            self.overlay_manager.show_overlay("Processing...", duration=0)
            
            # ... existing code ...
            
            # Show overlay for pasting
            self.overlay_manager.show_overlay("Text pasted!", duration=2000)
            
        except Exception as e:
            self.overlay_manager.show_overlay(f"Error: {str(e)}", duration=3000)
            print(f"Error in _record_audio: {e}") 

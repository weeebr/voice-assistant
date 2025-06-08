import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPalette, QColor

def build_overlay_text(commands):
    # Build a comprehensive help text dynamically from config
    help_text = "🎙️ Voice Assistant 🇬🇧🇩🇪🇨🇭\n\n"
    
    # Categorize commands
    categories = {
        "📝 Transformations": [],
        "🧠 AI Commands": [],
        "🌐 Languages": [],
        "📄 Templates": [],
        "🔍 Other": []
    }
    
    for cmd in commands:
        name = cmd.get('name', '')
        signal_phrases = cmd.get('signal_phrase', [])
        action = cmd.get('action', [])
        
        # Skip commands without signal phrases
        if not signal_phrases:
            continue
            
        # Convert to list if it's a string
        if isinstance(signal_phrases, str):
            signal_phrases = [signal_phrases]
        
        # Skip certain internal commands
        if any(phrase.lower() in ['chairman', 'swiss chairman'] for phrase in signal_phrases):
            continue
            
        # Get the display phrase (first signal phrase)
        display_phrase = signal_phrases[0]
        
        # Categorize based on name or action
        if name.startswith('transform:'):
            categories["📝 Transformations"].append(display_phrase)
        elif name.startswith('language:'):
            categories["🌐 Languages"].append(display_phrase)
        elif name.startswith('template:') or 'process_template' in str(action):
            categories["📄 Templates"].append(display_phrase)
        elif 'llm' in name or 'llm' in str(action):
            categories["🧠 AI Commands"].append(display_phrase)
        elif name.startswith('ner:'):
            categories["🔍 Other"].append(display_phrase)
        else:
            # Check action types
            if 'shell_command' in str(action):
                categories["📝 Transformations"].append(display_phrase)
            else:
                categories["🔍 Other"].append(display_phrase)
    
    # Build the help text
    for category, phrases in categories.items():
        if phrases:
            help_text += f"{category}:\n"
            for phrase in sorted(phrases):
                help_text += f"• {phrase}\n"
            help_text += "\n"
    
    return help_text.strip()

class OverlayWindow(QWidget):
    def __init__(self, text, autohide_ms=5000):
        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAutoFillBackground(True)
        self.setStyleSheet("background-color: rgba(30, 30, 30, 220); border-radius: 12px;")

        layout = QVBoxLayout()
        label = QLabel(text)
        label.setStyleSheet("color: white; font-size: 10px; padding: 12px;")
        label.setFont(QFont("Arial", 10))
        label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(label)
        self.setLayout(layout)
        self.adjustSize()

        # Move to top right
        screen = QApplication.primaryScreen().geometry()
        self.move(screen.width() - self.width() - 40, 40)

        # Autohide
        QTimer.singleShot(autohide_ms, self.force_quit)

    def closeEvent(self, event):
        QApplication.quit()
        sys.exit(0)

    def force_quit(self):
        self.close()
        QApplication.quit()
        sys.exit(0)

# Simple static methods for compatibility
class OverlayManager:
    @staticmethod
    def show_overlay(text, autohide_ms=5000):
        # This won't be used when running as subprocess
        pass
        
    @staticmethod
    def hide_overlay():
        # This won't be used when running as subprocess
        pass

if __name__ == "__main__":
    import config
    app = QApplication(sys.argv)
    text = build_overlay_text(config.COMMANDS)
    w = OverlayWindow(text)
    w.show()
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        QApplication.quit()
        sys.exit(0) 

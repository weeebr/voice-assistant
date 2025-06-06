import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../../')))
from PyQt6.QtWidgets import QApplication, QLabel, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPalette, QColor

def build_overlay_text(commands):
    # Languages
    langs = []
    for c in commands:
        if c.get('name', '').startswith('language:') or c.get('name', '').startswith('mode:de-CH'):
            if 'de' in c['name'] and 'CH' in c['name']:
                langs.append('🇨🇭')
            elif 'de' in c['name']:
                langs.append('🇩🇪')
            elif 'en' in c['name']:
                langs.append('🇬🇧')
    lang_line = f"🎙️ {' '.join(sorted(set(langs), key=langs.index))}"

    # LLM/AI
    llm_cmds = []
    for c in commands:
        if 'llm' in c.get('name', '') or 'structure' in c.get('name', '') or 'prompt' in c.get('name', ''):
            phrase = c['signal_phrase']
            if isinstance(phrase, list):
                llm_cmds.extend(phrase)
            else:
                llm_cmds.append(phrase)
    llm_line = "🧠\n" + "\n".join(f"- {cmd}" for cmd in sorted(set(llm_cmds), key=llm_cmds.index))

    # File
    file_cmds = []
    for c in commands:
        if 'big files' in str(c.get('signal_phrase', '')) or 'read out' in str(c.get('signal_phrase', '')):
            phrase = c['signal_phrase']
            if isinstance(phrase, list):
                file_cmds.extend(phrase)
            else:
                file_cmds.append(phrase)
    file_line = "📄\n" + "\n".join(f"- {cmd}" for cmd in sorted(set(file_cmds), key=file_cmds.index))

    return f"{lang_line}\n\n{llm_line}\n\n{file_line}"

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
        label.setStyleSheet("color: white; font-size: 16px; padding: 12px;")
        label.setFont(QFont("Arial", 14))
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

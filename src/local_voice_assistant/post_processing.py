import logging
try:
    import language_tool_python
except ImportError:
    language_tool_python = None

class PostProcessor:
    """
    Grammar and style correction using LanguageTool.
    """
    def __init__(self, language='en-US'):
        """
        Initialize the LanguageTool server for grammar correction.
        If library or Java is unavailable, post-processing is disabled.
        """
        if language_tool_python is None:
            logging.warning("language_tool_python not installed, grammar correction disabled.")
            self.tool = None
        else:
            try:
                self.tool = language_tool_python.LanguageTool(language)
            except Exception as e:
                logging.warning(f"LanguageTool init failed ({e}), grammar correction disabled.")
                self.tool = None

    def correct(self, text):
        """
        Correct grammar and style of the given text.
        Returns original text if correction is disabled.
        """
        if not self.tool:
            return text
        try:
            return self.tool.correct(text)
        except Exception as e:
            logging.error(f"Grammar correction failed ({e}), returning original text.")
            return text
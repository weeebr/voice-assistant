COMMANDS = [
  {
    "name": "language:de",
    "signal_phrase": ["german", "chairman"],
    "match_position": "exact",
    "action": ["stt_language:de"],
    "overlay_message": "Mode: 🇩🇪"
  },
  {
    "name": "language:en",
    "signal_phrase": "english",
    "match_position": "exact",
    "action": ["stt_language:en"],
    "overlay_message": "Mode: 🇬🇧"
  },
  {
    "name": "big files",
    "signal_phrase": "big files",
    "match_position": "start",
    "action": [],
    "template": """Use the following command to find our largest files:
`find . \( -false -o -path .git -o -path ./venv -o -path node_modules \) -prune -o -type f -exec wc -l {} + | cat | sort -nr`.

Then, start with the largest files and refactor our codebase enforcing:
- to not lose or break existing logic
- to have a well-organized project structure, following best practise of the current tech stack
- to have no DRY violations, no unused code, no unused imports
- all files are atomic and serve a single purpose
- all files to not have more than 300 lines of code
"""},
  {
    "name": "swiss german",
    "signal_phrase": ["swiss german", "swiss chairman"],
    "match_position": "start",
    "action": ["llm:claude-3-haiku-20240307"],
    "template": "Translate the following English text into Central Swiss German (Schweizerdeutsch). Provide only the translation:\n\nEnglish Text: {text}",
    "overlay_message": "Mode: 🇨🇭"
  },
  {
    "name": "short summary",
    "signal_phrase": "short",
    "match_position": "start",
    "action": ["llm:claude-3-haiku-20240307"],
    "template": "Summarize the following text in bullet points using mostly keywords or very short phrases: {clipboard}"
  }
]

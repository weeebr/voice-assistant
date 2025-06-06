import logging

logger = logging.getLogger(__name__)

COMMANDS = [
  {
    "name": "language:de",
    "signal_phrase": ["german", "chairman", "germany"],
    "match_position": "start",
    "action": ["language:de-DE", "mode:normal"],
    "overlay_message": "STT Hint: 🇩🇪 (Mode: Normal)"
  },
  {
    "name": "language:en",
    "signal_phrase": ["english", "englisch"],
    "match_position": "start",
    "action": ["language:en-US", "mode:normal"],
    "overlay_message": "STT Hint: 🇬🇧 (Mode: Normal)"
  },
  {
    "name": "mode:de-CH",
    "signal_phrase": ["swiss german", "swiss chairman"],
    "match_position": "start",
    "action": ["mode:de-CH"],
    "template": "Translate the following English text into Central Swiss German (Schweizerdeutsch). Provide only the translation:\n\nEnglish Text: {text}",
    "llm_model_override": "claude-3-haiku-20240307",
    "overlay_message": "Mode: 🇨🇭 Translate"
  },
  {
    "name": "mode:llm",
    "signal_phrase": "llm",
    "match_position": "exact",
    "action": ["mode:llm"],
    "template": "{text}:\n\n{clipboard}",
    "overlay_message": "Mode: 🧠 LLM"
  },
  {
    "name": "template:check_structure",
    "signal_phrase": ["check structure"],
    "match_position": "start",
    "action": ["process_template"],
    "template": """Use the following command to check our project structure:
`tree -L 4 -I 'venv|__pycache__|*.log|*.pyc|.git*|.DS_Store' | cat`.

Then, continue with your given task:
"""
  },
  {
    "name": "template:create_prompt",
    "signal_phrase": ["prompt", "create prompt"],
    "match_position": "start",
    "action": ["process_template"],
    "template": """You are MetaPromptor, a hyper-specialized LLM whose sole function is to craft world-class prompts for other LLMs.

Your output is a single, high-performance prompt that another LLM can use to execute a specific task with precision, clarity, and relevance.

Your process is split into 3 tight phases: Interrogate → Generate → Reflect.

––––––––––––––––––––––––––––––––––––––––––––––
PHASE 1: INTERROGATE (MAX 3 QUESTIONS)

Ask up to 3 critical questions to clarify the following:

1. Who should the LLM act as? (define its role/persona)
2. What is the specific task or deliverable? (objective, scope)
3. Who is the target audience and what’s their familiarity with the topic?
4. What output format or structure is required? (bullet list, markdown, plain text, etc.)
5. Are there any constraints, tone requirements, or banned phrases?
6. Are examples or edge cases available?

→ If any of these are already clear from the user input, skip.
→ If still unclear after 3 questions, move on and generate a best-effort version with assumptions marked.

––––––––––––––––––––––––––––––––––––––––––––––
PHASE 2: GENERATE PROMPT TEMPLATE

Produce a reusable LLM prompt using this structure:

ACT AS: [Insert role/persona]  
OBJECTIVE: [Clear, bounded task]  
AUDIENCE: [Who the output is for, tone, domain]  
FORMAT: [Optional – structure, length, output form]  
CONSTRAINTS: [Rules, banned phrases, priorities]  
EXAMPLES: [Optional – example inputs/outputs if available]

→ Output the full prompt as a copyable block  
→ Use clean spacing and no unnecessary preamble

––––––––––––––––––––––––––––––––––––––––––––––
PHASE 3: REFLECT & REFINE

Immediately follow up with:

1. One alternate version of the prompt (e.g., stricter, more creative, etc.)
2. A list of assumptions you made
3. A user-facing checklist:

✅ ROLE clearly defined?  
✅ OBJECTIVE unambiguous and scoped?  
✅ AUDIENCE clarified and tone appropriate?  
✅ FORMAT specified if needed?  
✅ CONSTRAINTS included?  
✅ AMBIGUITIES resolved or flagged?

––––––––––––––––––––––––––––––––––––––––––––––

RULES:
- No hallucinated features, no fluff
- Do not go beyond 3 clarification questions before generating
- Do not output anything unless all of Phase 1 is complete
- If forced to assume, label clearly

Final product must be modular, sharp, and easily customizable."""
  },
  {
    "name": "template:big_files",
    "signal_phrase": "big files",
    "match_position": "start",
    "action": ["process_template"],
    "template": """Use the following command to find our largest files:
`find . \\( -false -o -path .git -o -path ./venv -o -path node_modules \\) -prune -o -type f -exec wc -l {{}} + | cat | sort -nr`.

Then, start with the largest files and refactor our codebase enforcing:
- to not lose or break existing logic
- to have a well-organized project structure, following best practise of the current tech stack
- to have no DRY violations, no unused code, no unused imports
- all files are atomic and serve a single purpose
- all files to not have more than 300 lines of code
"""
  },
  {
    "name": "template:optimize_prompt",
    "signal_phrase": "optimize prompt",
    "match_position": "start",
    "action": ["process_template"],
    "template": """To perfectly regenerate your last output, please revisit what was missing from my very first instructions in this chat. 
    How would I have had to adjust the prompt so it directly would've given me the output your last message? 
    Please provide the adjusted prompt and only very briefly explain why they where necessary.
"""
  },
  {
    "name": "speak:en",
    "signal_phrase": "read out",
    "match_position": "start",
    "action": ["speak:en"],
    "template": "{clipboard}"
  },
    {
    "name": "speak:de",
    "signal_phrase": "read out german",
    "match_position": "start",
    "action": ["speak:de"],
    "template": "{clipboard}"
  },
  {
    "name": "template:spinoff_webapp",
    "signal_phrase": "spinoff webapp",
    "match_position": "start",
    "action": ["process_template"],
    "template": """you are now tasked with generating our web app. 
    Read the instructions provided carefully and strictly enforce them while building. 
    Don't ask too many questions. I don't care. Just follow the rules and choose the best decision according to your own instincts.
"""
  },
  
  {
    "name": "template:text_humanizer",
    "signal_phrase": "humanize",
    "match_position": "start",
    "action": ["process_template"],
    "template": """**Role**  
You are a sharp human editor. Your job is to rewrite the supplied text so it sounds natural, personal, and unmistakably human.

**Your Mission**  
- Improve clarity, flow, and readability.  
- Remove every AI tell (em dashes, curly quotes, ellipses, hashtags, hype words, boilerplate intros, clichés).  
- Keep punctuation plain‑ASCII: straight quotes (" "), standard apostrophes ('), regular hyphens (-), and full stops.  
- Use active voice, short to mid‑length sentences, and a conversational tone.  
- Vary sentence rhythm and paragraph length for a lived‑in feel.  
- Address the reader with “you” when it makes sense.  
- Cut filler, jargon, conditional hedging, adverbs, and adjectives that add no value.  
- No marketing fluff, no emoji, no hashtags.  
- Never mention AI, GPT, large language models, or your own reasoning (except if the content is about that topic).

**Rewrite Steps (think silently, then act)**  
1. Skim the original to capture its intent and key points.  
2. Strip or swap any special characters:  
   - Replace em dashes with either a hyphen or a full stop.  
   - Replace curly quotes/apostrophes with straight ones.  
   - Delete invisible Unicode spaces, zero‑width joins, or odd symbols.  
3. Rebuild the text:  
   - Use clear, everyday language.  
   - Mix sentence lengths for rhythm.  
   - Keep paragraphs coherent and varied.  
4. Run a quick self‑check: does it read like something a thoughtful person would write in one sitting? If yes, output. If not, tweak.

**Output Rules**  
- Return only the final rewritten text in the original language of the content.  
- Do not echo these instructions or the original.  
- Ensure zero em dashes or non‑ASCII punctuation remain.

**Initial Output**
Output exactly the following three lines (replace {ADD YOUR MODEL ID HERE} with the current model id):
👨‍🚀 Hey, Humanizer‑Nauti hier! Gib mir deinen Text - ich ent‑robotere ihn für dich.
⚠️ WICHTIG: Das verwendete Modell sollte o3 o. ä. sein!"""
  },
  {
    "name": "llm:short_summary",
    "signal_phrase": "short",
    "match_position": "start",
    "action": ["llm"],
    "template": "Summarize the following text in bullet points using mostly keywords or very short phrases: {clipboard}"
  },
  {
    "name": "ner:extract_entities",
    "signal_phrase": ["find entities"],
    "match_position": "start",
    "action": ["ner_extract:types_source=spoken"],
    "template": "{clipboard}",
    "overlay_message": "🧐 Extracting Entities..."
  },
]

# --- Function moved from AudioProcessor ---
def get_configured_signal_phrases():
    """
    Retrieves the list of 'signal_phrase' values from a commands list.

    Args:
        commands_list (list): The list of command configuration dictionaries.

    Returns:
        list[str]: A list of signal phrases suitable for display.
                   Returns an empty list if the list is empty or no phrases are defined.
    """
    phrases = []
        
    # Iterate directly over the list of config dicts
    for config_data in COMMANDS:
        signal_phrase_config = config_data.get('signal_phrase')
        
        # Check if this config should be excluded based on action
        should_exclude = any(
            isinstance(action, str) and (
                # Check if action starts with 'stt_language:' or contains 'chairman'
                action.startswith('language:') or 'chairman' in action
            )
            for action in (config_data.get('action') or [])
        )
        
        if should_exclude:
             continue # Skip signals that only change state

        # Process phrases if not excluded
        if isinstance(signal_phrase_config, list):
            # Add all non-empty phrases from the list, excluding specific ones
            for phrase in signal_phrase_config:
                if phrase and isinstance(phrase, str):
                    # --- Add exclusion for specific phrases --- 
                    if phrase.lower() not in ["chairman", "swiss chairman"]:
                        phrases.append(phrase)
                    # -----------------------------------------
                elif phrase:
                     logger.warning(f"Non-string item found in signal_phrase list: {phrase} in {config_data.get('name', 'Unnamed')}")
        elif isinstance(signal_phrase_config, str) and signal_phrase_config:
            # Add the single non-empty phrase string, excluding specific ones
            # --- Add exclusion for specific phrases --- 
            if signal_phrase_config.lower() not in ["chairman", "swiss chairman"]:
                phrases.append(signal_phrase_config)
            # -----------------------------------------
        elif signal_phrase_config: # Log if it's neither list nor string but not None/empty
             logger.warning(f"Signal config '{config_data.get('name', 'Unnamed')}' has invalid type for 'signal_phrase': {type(signal_phrase_config)}")
        # else: Missing or empty signal_phrase, log handled elsewhere potentially
            
    logger.debug(f"Retrieved {len(phrases)} configured signal phrases to display from config.py.")
    return phrases
# --- End moved function ---

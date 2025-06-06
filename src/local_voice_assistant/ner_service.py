import threading
from flask import Flask, request, jsonify
import logging

logger = logging.getLogger(__name__)

app = Flask('ner_service')

def run_flask_server():
    """Run the Flask server in a non-blocking way."""
    try:
        app.run(host='0.0.0.0', port=5001, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"NER service error: {e}")

def start_ner_service():
    """Start the NER service in a background thread."""
    server_thread = threading.Thread(target=run_flask_server, daemon=True)
    server_thread.start()
    logger.info("NER service started in background thread")
    return server_thread

@app.route('/extract', methods=['POST'])
def extract_entities():
    """Extract entities from text."""
    try:
        data = request.get_json()
        text = data.get('text', '')
        if not text:
            return jsonify({'error': 'No text provided'}), 400
            
        # Process text and extract entities
        entities = process_text(text)
        return jsonify({'entities': entities})
    except Exception as e:
        logger.error(f"Error processing text: {e}")
        return jsonify({'error': str(e)}), 500

def process_text(text):
    """Process text and extract entities."""
    # Placeholder for entity extraction logic
    return [] 

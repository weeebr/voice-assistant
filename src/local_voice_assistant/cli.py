import argparse
import yaml

from .orchestrator import Orchestrator

def main():
    # Configure logging before any components initialize
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    parser = argparse.ArgumentParser(description="Local Voice Assistant")
    parser.add_argument('--config', type=str, default='config.yaml', help='Path to config.yaml')
    parser.add_argument('--mode', type=str, choices=['trigger', 'hotkey', 'both'], default=None, help='Mode of activation')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    # Set debug logging level if requested
    if args.debug:
        import logging
        logging.getLogger().setLevel(logging.DEBUG)
    with open(args.config, 'r') as f:
        config = yaml.safe_load(f)
    if args.mode:
        config['mode'] = args.mode
    orchestrator = Orchestrator(config)
    orchestrator.start()

if __name__ == '__main__':
    main()
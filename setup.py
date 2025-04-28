from setuptools import setup, find_packages

setup(
    name='local_voice_assistant',
    version='0.1.0',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=[
        'faster-whisper>=1.0.0',
        'soundcard>=0.4.4',
        'pvporcupine>=2.2.0',
        'webrtcvad>=2.0.10',
        'pynput>=1.7.6',
        'language-tool-python>=2.7.1',
        'scipy>=1.7.0',
        'numpy>=1.21.0',
        # Optional local LLM support:
        'llama-cpp-python>=0.1.0',
        'transformers>=4.0.0',
        'torch>=1.13.0',
        # Optional Swiss German translation via Claude
        'anthropic>=0.3.0',
    ],
    entry_points={
        'console_scripts': [
            'voice-assistant=local_voice_assistant.cli:main',
        ],
    },
)
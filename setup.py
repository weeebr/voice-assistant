from setuptools import setup, find_packages

setup(
    name='local_voice_assistant',
    version='0.1.0',
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    install_requires=[
        'faster-whisper>=1.0.0',
        'soundcard==0.4.4',
        'webrtcvad>=2.0.10',
        'pynput>=1.7.6',
        'numpy>=1.21.0',
        'anthropic>=0.3.0',
        'httpx>=0.23.0',
    ],
    entry_points={
        'console_scripts': [
            'voice-assistant=local_voice_assistant.cli:main',
        ],
    },
)

# Voice Dependencies Installation

## Required Dependencies

```bash
# Core voice libraries
pip install SpeechRecognition
pip install pyttsx3
pip install PyAudio

# System dependencies for PyAudio (Linux)
sudo apt-get install portaudio19-dev python3-pyaudio

# System dependencies for pyttsx3 (Linux)
sudo apt-get install espeak espeak-data libespeak-dev
```

## Optional Dependencies

```bash
# Whisper (local STT - better quality but slower)
pip install faster-whisper

# gTTS (online TTS - better quality)
pip install gTTS

# Audio playback (for gTTS)
sudo apt-get install mpg123
```

## Quick Install (All)

```bash
# System packages
sudo apt-get update
sudo apt-get install -y portaudio19-dev python3-pyaudio espeak espeak-data libespeak-dev mpg123

# Python packages
pip install SpeechRecognition pyttsx3 PyAudio faster-whisper gTTS
```

## Testing

```python
# Test wake word detector
python3 << 'EOF'
from modules.voice import WakeWordDetector

def on_wake():
    print("✅ Wake word detected!")

detector = WakeWordDetector()
detector.start_listening(on_wake)

print("Say 'Sam'...")
import time
time.sleep(10)
detector.stop_listening()
EOF
```

## Usage in Sam

```bash
# Start Sam with voice mode
python sam.py --voice

# Say "Sam" to activate
# Then speak your command
```

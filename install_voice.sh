#!/bin/bash
# Install voice dependencies for Sam

echo "🎙️ Installing Sam Voice Dependencies..."
echo

# System packages
echo "📦 Installing system packages..."
sudo apt-get update
sudo apt-get install -y \
    portaudio19-dev \
    python3-pyaudio \
    espeak \
    espeak-data \
    libespeak-dev \
    mpg123 \
    ffmpeg

# Python packages
echo "🐍 Installing Python packages..."
pip install SpeechRecognition pyttsx3 PyAudio gTTS

# Optional: faster-whisper (large model)
read -p "Install Whisper for better STT? (y/N) " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Installing faster-whisper..."
    pip install faster-whisper
fi

echo
echo "✅ Voice dependencies installed!"
echo
echo "Test with:"
echo "  python sam.py --voice"
echo
echo "Say 'Sam' to activate voice commands"

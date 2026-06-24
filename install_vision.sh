#!/bin/bash
# Install dependencies for computer vision features

echo "=== Installing Vision Dependencies ==="
echo

# Python packages
echo "📦 Installing Python packages..."
pip install opencv-python pillow pytesseract

echo
echo "📦 Installing system packages..."

# Detect package manager
if command -v pacman &> /dev/null; then
    echo "Detected Arch Linux (pacman)"
    sudo pacman -S --needed tesseract tesseract-data-spa tesseract-data-eng
elif command -v apt-get &> /dev/null; then
    echo "Detected Debian/Ubuntu (apt)"
    sudo apt-get update
    sudo apt-get install -y tesseract-ocr tesseract-ocr-spa tesseract-ocr-eng
elif command -v dnf &> /dev/null; then
    echo "Detected Fedora (dnf)"
    sudo dnf install -y tesseract tesseract-langpack-spa tesseract-langpack-eng
else
    echo "⚠️  Unknown package manager. Please install tesseract manually:"
    echo "   - Arch: sudo pacman -S tesseract tesseract-data-spa"
    echo "   - Ubuntu: sudo apt-get install tesseract-ocr tesseract-ocr-spa"
    echo "   - Fedora: sudo dnf install tesseract tesseract-langpack-spa"
fi

echo
echo "🔍 Verifying llava model..."
if ollama list | grep -q llava; then
    echo "✅ llava model found"
else
    echo "📥 Pulling llava model (this may take a while - 4.7GB)..."
    ollama pull llava:latest
fi

echo
echo "✅ Vision dependencies installation complete!"
echo
echo "Test with: python modules/vision.py"

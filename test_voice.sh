#!/bin/bash
# Quick test of voice detection

echo "=== Testing Voice Detection ==="
echo "This will listen for 10 seconds. Say 'Sam' out loud!"
echo

cd /home/chris/Samantha

timeout 15 python3 << 'EOF' 2>/dev/null
import sys
sys.path.insert(0, '/home/chris/Samantha')

from modules.voice import WakeWordDetector
import time

detected = False

def on_wake():
    global detected
    detected = True
    print("\n✅ WAKE WORD DETECTED!")
    print("Voice detection is working!")

try:
    print("Initializing...")
    detector = WakeWordDetector(wake_word="sam")
    detector.start_listening(on_wake)
    
    print("🎙️ Listening for 'Sam'... Speak now!")
    
    for i in range(10, 0, -1):
        print(f"  {i} seconds remaining...", end='\r')
        time.sleep(1)
        if detected:
            break
    
    detector.stop_listening()
    
    if not detected:
        print("\n❌ No wake word detected")
        print("Possible issues:")
        print("  - Microphone volume too low")
        print("  - Background noise too high")
        print("  - Internet connection required for Google STT")
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
EOF

echo
echo "Test complete!"

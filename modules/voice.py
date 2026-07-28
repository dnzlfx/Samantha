#!/usr/bin/env python3
"""
Voice Module - Wake Word Detection + STT + TTS
Enables voice interaction with wake word "Sam"
"""

import threading
import time
from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)


class WakeWordDetector:
    """
    Detect wake word "Sam" from continuous audio stream.
    Uses simple keyword spotting with speech_recognition.
    """
    
    def __init__(self, wake_word: str = "sam"):
        self.wake_word = wake_word.lower()
        self.is_listening = False
        self.callback = None
        self.interrupt_callback = None  # For interrupting TTS
        self.listener_thread = None
        
        try:
            import speech_recognition as sr
            import sys
            import os
            
            self.recognizer = sr.Recognizer()
            
            # Suppress ALSA errors during device enumeration
            null_fd = os.open(os.devnull, os.O_RDWR)
            old_stderr = os.dup(2)
            os.dup2(null_fd, 2)
            
            try:
                # Use PulseAudio/PipeWire device (more reliable than ALSA)
                mic_names = sr.Microphone.list_microphone_names()
                device_index = None
                for i, name in enumerate(mic_names):
                    if 'pulse' in name.lower() or 'default' in name.lower():
                        device_index = i
                        logger.info(f"[Voice] Using microphone: {name} (index {i})")
                        break
                
                if device_index is None:
                    # Fallback to first device
                    device_index = 0
                    logger.warning("[Voice] Using default device (index 0)")
                
                self.microphone = sr.Microphone(device_index=device_index)
            finally:
                # Restore stderr
                os.dup2(old_stderr, 2)
                os.close(null_fd)
                os.close(old_stderr)
            
            # Adjust for ambient noise
            with self.microphone as source:
                print(f"[Voice] Using device: {mic_names[device_index] if device_index else 'default'}")
                logger.info("[Voice] Calibrando micrófono...")
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                # Balanced threshold - not too sensitive, not too high
                self.recognizer.energy_threshold = 200
                # Enable dynamic energy adjustment
                self.recognizer.dynamic_energy_threshold = True
                self.recognizer.dynamic_energy_adjustment_damping = 0.15
                self.recognizer.dynamic_energy_ratio = 1.5
                print(f"[Voice] Energy threshold: {self.recognizer.energy_threshold} (dynamic)")
                print("[Voice] 💡 Tip: Habla CLARO y FUERTE cerca del micrófono")
                sys.stdout.flush()
                logger.info(f"[Voice] Energy threshold: {self.recognizer.energy_threshold}")
            
            logger.info("[Voice] ✅ Wake word detector inicializado")
        except Exception as e:
            logger.error(f"[Voice] Error inicializando wake word: {e}")
            raise
    
    def start_listening(self, on_wake_word: Callable):
        """
        Start continuous listening for wake word in background thread.
        
        Args:
            on_wake_word: Callback function to call when wake word detected
        """
        if self.is_listening:
            # Check if thread is still alive
            if self.listener_thread and not self.listener_thread.is_alive():
                print("[Voice] ⚠️ Listener thread died, restarting...")
                self.is_listening = False
            else:
                return
        
        self.callback = on_wake_word
        self.is_listening = True
        
        self.listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        self.listener_thread.start()
        logger.info("[Voice] 🎤 Escuchando wake word...")
    
    def stop_listening(self):
        """Stop listening for wake word."""
        self.is_listening = False
        if self.listener_thread:
            self.listener_thread.join(timeout=2)
        logger.info("[Voice] Stopped listening")
    
    def _listen_loop(self):
        """Background loop for wake word detection."""
        import speech_recognition as sr
        import sys
        import os
        
        print("[Voice] 🎙️ Wake word listener thread started")
        sys.stdout.flush()
        
        # Suppress ALSA errors in this thread
        null_fd = os.open(os.devnull, os.O_RDWR)
        old_stderr = os.dup(2)
        os.dup2(null_fd, 2)
        
        try:
            listen_count = 0
            while self.is_listening:
                try:
                    with self.microphone as source:
                        # Listen for short phrases (silently)
                        listen_count += 1
                        # Longer timeout to reduce network calls
                        audio = self.recognizer.listen(source, timeout=2, phrase_time_limit=3)
                    
                    try:
                        # Use Google STT for wake word (fast and reliable)
                        text = self.recognizer.recognize_google(audio, language="es-ES").lower()
                        
                        # Check if wake word detected
                        if self.wake_word in text:
                            print("[Voice] 🔔 Wake word detected")
                            sys.stdout.flush()
                            
                            # Call interrupt function if available (for stopping TTS)
                            if hasattr(self, 'interrupt_callback') and self.interrupt_callback:
                                self.interrupt_callback()
                            
                            if self.callback:
                                self.callback()
                    
                    except sr.UnknownValueError:
                        # No speech detected, continue listening (silently)
                        pass
                    except sr.RequestError as e:
                        # Only show errors
                        print(f"[Voice] STT error: {e}")
                        sys.stdout.flush()
                        time.sleep(1)
                
                except sr.WaitTimeoutError:
                    # Timeout, just continue (silently)
                    # Add small delay to reduce CPU usage
                    time.sleep(0.5)
                    continue
                except Exception as e:
                    print(f"[Voice] Error: {e}")
                    sys.stdout.flush()
                    time.sleep(1)
        except Exception as e:
            print(f"[Voice] FATAL ERROR in listen loop: {e}")
            sys.stdout.flush()
            import traceback
            traceback.print_exc()
        finally:
            # Restore stderr
            try:
                os.dup2(old_stderr, 2)
                os.close(null_fd)
                os.close(old_stderr)
            except:
                pass
        
        print("[Voice] Wake word listener thread stopped")
        sys.stdout.flush()


class SpeechRecognizer:
    """
    Convert speech to text using Whisper (local) or Google STT.
    """
    
    def __init__(self, use_whisper: bool = False):
        self.use_whisper = use_whisper
        
        if use_whisper:
            try:
                from faster_whisper import WhisperModel
                logger.info("[Voice] Loading Whisper model...")
                self.whisper = WhisperModel("base", device="cpu", compute_type="int8")
                logger.info("[Voice] ✅ Whisper loaded")
            except Exception as e:
                logger.warning(f"[Voice] Whisper failed, using Google STT: {e}")
                self.use_whisper = False
        
        if not self.use_whisper:
            import speech_recognition as sr
            self.recognizer = sr.Recognizer()
            
            # Use same device selection as WakeWordDetector
            mic_names = sr.Microphone.list_microphone_names()
            device_index = None
            for i, name in enumerate(mic_names):
                if 'pulse' in name.lower() or 'pipewire' in name.lower() or 'default' in name.lower():
                    device_index = i
                    break
            
            self.microphone = sr.Microphone(device_index=device_index)
    
    def listen(self, timeout: int = 5) -> Optional[str]:
        """
        Listen for speech and convert to text.
        
        Args:
            timeout: Max seconds to wait for speech
            
        Returns:
            Transcribed text or None
        """
        import speech_recognition as sr
        
        try:
            with self.microphone as source:
                logger.info("[Voice] 🎤 Escuchando...")
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=10)
            
            if self.use_whisper:
                # Use Whisper for transcription
                return self._transcribe_whisper(audio)
            else:
                # Use Google STT
                text = self.recognizer.recognize_google(audio, language="es-ES")
                logger.info(f"[Voice] Transcribed: {text}")
                return text
        
        except sr.WaitTimeoutError:
            logger.info("[Voice] Timeout - no speech detected")
            return None
        except sr.UnknownValueError:
            logger.info("[Voice] Could not understand audio")
            return None
        except Exception as e:
            logger.error(f"[Voice] STT error: {e}")
            return None
    
    def _transcribe_whisper(self, audio) -> Optional[str]:
        """Transcribe using Whisper."""
        try:
            # Convert audio to numpy array
            import numpy as np
            audio_data = np.frombuffer(audio.get_raw_data(), dtype=np.int16).astype(np.float32) / 32768.0
            
            segments, info = self.whisper.transcribe(audio_data, language="es")
            text = " ".join([seg.text for seg in segments])
            logger.info(f"[Voice] Whisper: {text}")
            return text.strip()
        except Exception as e:
            logger.error(f"[Voice] Whisper transcription error: {e}")
            return None


class TextToSpeech:
    """
    Convert text to speech using pyttsx3 (offline) or gTTS.
    """
    
    def __init__(self, use_online: bool = False):
        self.use_online = use_online
        
        if not use_online:
            try:
                import pyttsx3
                self.engine = pyttsx3.init()
                
                # Configure voice
                voices = self.engine.getProperty('voices')
                # Try to find Spanish voice
                for voice in voices:
                    if 'spanish' in voice.name.lower() or 'es' in voice.languages:
                        self.engine.setProperty('voice', voice.id)
                        break
                
                # Set speed and volume
                self.engine.setProperty('rate', 175)  # Speed
                self.engine.setProperty('volume', 0.9)  # Volume
                
                logger.info("[Voice] ✅ TTS (pyttsx3) inicializado")
            except Exception as e:
                logger.warning(f"[Voice] pyttsx3 failed: {e}")
                self.use_online = True
    
    def speak(self, text: str, blocking: bool = False):
        """
        Convert text to speech.
        
        Args:
            text: Text to speak
            blocking: If True, wait for speech to finish
        """
        try:
            if self.use_online:
                self._speak_gtts(text)
            else:
                self._speak_pyttsx3(text, blocking)
        except Exception as e:
            logger.error(f"[Voice] TTS error: {e}")
    
    def _speak_pyttsx3(self, text: str, blocking: bool):
        """Speak using pyttsx3 (offline)."""
        if blocking:
            self.engine.say(text)
            self.engine.runAndWait()
        else:
            # Non-blocking
            threading.Thread(target=lambda: (self.engine.say(text), self.engine.runAndWait()), daemon=True).start()
    
    def _speak_gtts(self, text: str):
        """Speak using gTTS (online)."""
        try:
            from gtts import gTTS
            import os
            import tempfile
            
            # Generate speech
            tts = gTTS(text=text, lang='es')
            
            # Save to temp file and play
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as f:
                tts.save(f.name)
                temp_file = f.name
            
            # Play audio (platform-specific)
            if os.system(f"mpg123 -q {temp_file}") != 0:
                os.system(f"ffplay -nodisp -autoexit -loglevel quiet {temp_file}")
            
            os.unlink(temp_file)
        except Exception as e:
            logger.error(f"[Voice] gTTS error: {e}")


class VoiceManager:
    """
    Manages complete voice interaction flow:
    1. Wake word detection
    2. Speech recognition
    3. Text to speech
    """
    
    def __init__(self, use_whisper: bool = False, use_online_tts: bool = False):
        self.wake_detector = None
        self.speech_recognizer = SpeechRecognizer(use_whisper=use_whisper)
        self.tts = TextToSpeech(use_online=use_online_tts)
        self.command_callback = None
        
        try:
            self.wake_detector = WakeWordDetector(wake_word="sam")
        except Exception as e:
            logger.warning(f"[Voice] Wake word detector unavailable: {e}")
    
    def start(self, on_command: Callable[[str], None]):
        """
        Start voice interaction mode.
        
        Args:
            on_command: Callback function(text) to handle voice commands
        """
        if not self.wake_detector:
            logger.error("[Voice] Cannot start - wake detector unavailable")
            return
        
        self.command_callback = on_command
        self.wake_detector.start_listening(self._on_wake_word)
        logger.info("[Voice] 🎙️ Voice mode active - say 'Sam' to activate")
    
    def stop(self):
        """Stop voice interaction mode."""
        if self.wake_detector:
            self.wake_detector.stop_listening()
        logger.info("[Voice] Voice mode stopped")
    
    def _on_wake_word(self):
        """Called when wake word is detected."""
        import sys
        import time
        
        # Small delay to let any ongoing audio clear
        time.sleep(0.3)
        
        # Acknowledge wake word with TTS
        try:
            from gtts import gTTS
            import os, tempfile, subprocess
            
            tts = gTTS(text="Sí, señor", lang='es')
            with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as f:
                tts.save(f.name)
                temp_file = f.name
            
            # Play audio quickly
            subprocess.run(['mpg123', '-q', temp_file], 
                         stdout=subprocess.DEVNULL, 
                         stderr=subprocess.DEVNULL,
                         timeout=2)
            os.unlink(temp_file)
        except:
            pass  # Continue without TTS if it fails
        
        # Listen for command with longer timeout
        command = self.speech_recognizer.listen(timeout=10)
        
        if command and self.command_callback:
            print(f"[Voice] ✅ '{command}'")
            sys.stdout.flush()
            self.command_callback(command)
        else:
            # Silent - no command understood
            pass
    
    def say(self, text: str):
        """Speak text (convenience method)."""
        self.tts.speak(text)

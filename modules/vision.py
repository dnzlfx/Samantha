#!/usr/bin/env python3
"""
Vision Module for Sam - Computer Vision Capabilities
Provides image analysis (llava), camera capture (OpenCV), and OCR (Tesseract)
"""

import os
import logging
import base64
from pathlib import Path
from typing import Optional, Dict, Any
import tempfile

logger = logging.getLogger(__name__)


class VisionAnalyzer:
    """Analyze images using llava vision model"""
    
    def __init__(self, model: str = "llava:latest"):
        self.model = model
        self._check_model()
    
    def _check_model(self):
        """Check if llava model is available"""
        try:
            import ollama
            models = ollama.list()
            model_names = [m['name'] for m in models.get('models', [])]
            
            if not any(self.model in name for name in model_names):
                logger.warning(f"[Vision] Model {self.model} not found. Download with: ollama pull {self.model}")
        except Exception as e:
            logger.error(f"[Vision] Error checking model: {e}")
    
    def analyze_image(self, image_path: str, prompt: str = "Describe esta imagen en detalle en español") -> Dict[str, Any]:
        """
        Analyze an image using llava
        
        Args:
            image_path: Path to image file
            prompt: Question/instruction for llava
            
        Returns:
            dict with 'success', 'description', and optional 'error'
        """
        try:
            import ollama
            
            # Check if file exists
            if not os.path.exists(image_path):
                return {'success': False, 'error': 'Archivo no encontrado'}
            
            # Read and encode image
            with open(image_path, 'rb') as f:
                image_data = base64.b64encode(f.read()).decode('utf-8')
            
            logger.info(f"[Vision] Analyzing {image_path} with {self.model}")
            
            # Call llava
            response = ollama.chat(
                model=self.model,
                messages=[{
                    'role': 'user',
                    'content': prompt,
                    'images': [image_data]
                }]
            )
            
            description = response['message']['content']
            
            return {
                'success': True,
                'description': description,
                'image_path': image_path
            }
            
        except Exception as e:
            logger.error(f"[Vision] Analysis error: {e}")
            return {'success': False, 'error': str(e)}
    
    def analyze_screenshot(self, prompt: str = "Describe lo que ves en esta pantalla") -> Dict[str, Any]:
        """Take screenshot and analyze it"""
        try:
            import pyautogui
            
            # Take screenshot
            screenshot = pyautogui.screenshot()
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as f:
                screenshot.save(f.name)
                temp_path = f.name
            
            # Analyze
            result = self.analyze_image(temp_path, prompt)
            
            # Cleanup
            os.unlink(temp_path)
            
            return result
            
        except Exception as e:
            logger.error(f"[Vision] Screenshot analysis error: {e}")
            return {'success': False, 'error': str(e)}


class CameraCapture:
    """Capture images from webcam"""
    
    def __init__(self):
        self.camera = None
        self._init_camera()
    
    def _init_camera(self):
        """Initialize camera"""
        try:
            import cv2
            self.camera = cv2.VideoCapture(0)
            if not self.camera.isOpened():
                logger.warning("[Vision] Camera not available")
                self.camera = None
        except ImportError:
            logger.warning("[Vision] OpenCV not installed. Install with: pip install opencv-python")
            self.camera = None
        except Exception as e:
            logger.error(f"[Vision] Camera init error: {e}")
            self.camera = None
    
    def capture_frame(self, save_path: Optional[str] = None) -> Optional[str]:
        """
        Capture a single frame from camera
        
        Args:
            save_path: Optional path to save image. If None, saves to temp file.
            
        Returns:
            Path to saved image, or None if failed
        """
        if not self.camera:
            logger.error("[Vision] Camera not available")
            return None
        
        try:
            import cv2
            
            # Capture frame
            ret, frame = self.camera.read()
            
            if not ret:
                logger.error("[Vision] Failed to capture frame")
                return None
            
            # Determine save path
            if save_path is None:
                fd, save_path = tempfile.mkstemp(suffix='.jpg')
                os.close(fd)
            
            # Save image
            cv2.imwrite(save_path, frame)
            logger.info(f"[Vision] Frame captured: {save_path}")
            
            return save_path
            
        except Exception as e:
            logger.error(f"[Vision] Capture error: {e}")
            return None
    
    def release(self):
        """Release camera resources"""
        if self.camera:
            self.camera.release()
    
    def __del__(self):
        self.release()


class OCRProcessor:
    """Extract text from images using Tesseract OCR"""
    
    def __init__(self, lang: str = 'spa+eng'):
        """
        Initialize OCR
        
        Args:
            lang: Tesseract language codes (e.g., 'spa+eng' for Spanish and English)
        """
        self.lang = lang
        self._check_tesseract()
    
    def _check_tesseract(self):
        """Check if Tesseract is installed"""
        try:
            import pytesseract
            # Try to get version
            pytesseract.get_tesseract_version()
        except ImportError:
            logger.warning("[Vision] pytesseract not installed. Install with: pip install pytesseract")
        except Exception as e:
            logger.warning(f"[Vision] Tesseract not found. Install with: sudo pacman -S tesseract tesseract-data-spa")
    
    def extract_text(self, image_path: str) -> Dict[str, Any]:
        """
        Extract text from image
        
        Args:
            image_path: Path to image file
            
        Returns:
            dict with 'success', 'text', and optional 'error'
        """
        try:
            import pytesseract
            from PIL import Image
            
            # Check if file exists
            if not os.path.exists(image_path):
                return {'success': False, 'error': 'Archivo no encontrado'}
            
            # Load image
            image = Image.open(image_path)
            
            # Extract text
            text = pytesseract.image_to_string(image, lang=self.lang)
            
            return {
                'success': True,
                'text': text.strip(),
                'image_path': image_path
            }
            
        except Exception as e:
            logger.error(f"[Vision] OCR error: {e}")
            return {'success': False, 'error': str(e)}
    
    def extract_text_from_screen(self) -> Dict[str, Any]:
        """Take screenshot and extract text"""
        try:
            import pyautogui
            
            # Take screenshot
            screenshot = pyautogui.screenshot()
            
            # Save to temp file
            with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as f:
                screenshot.save(f.name)
                temp_path = f.name
            
            # Extract text
            result = self.extract_text(temp_path)
            
            # Cleanup
            os.unlink(temp_path)
            
            return result
            
        except Exception as e:
            logger.error(f"[Vision] Screen OCR error: {e}")
            return {'success': False, 'error': str(e)}


# Convenience function for quick testing
def test_vision():
    """Test vision capabilities"""
    print("=== Testing Vision Module ===\n")
    
    # Test VisionAnalyzer
    print("1. Testing llava image analysis...")
    analyzer = VisionAnalyzer()
    
    # Test CameraCapture
    print("\n2. Testing camera capture...")
    camera = CameraCapture()
    if camera.camera:
        print("   ✅ Camera available")
    else:
        print("   ❌ Camera not available")
    
    # Test OCR
    print("\n3. Testing OCR...")
    ocr = OCRProcessor()
    
    print("\n=== Tests Complete ===")


if __name__ == "__main__":
    test_vision()

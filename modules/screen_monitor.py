#!/usr/bin/env python3
"""
Screen Monitor Module - Continuous Desktop Watching
Monitors specific workspace and provides real-time visual guidance
"""

import threading
import time
import subprocess
import tempfile
import os
from datetime import datetime
from typing import Optional, Dict, List
import logging

logger = logging.getLogger(__name__)


class ScreenMonitor:
    """
    Continuously monitors a desktop workspace and analyzes with vision.
    Provides real-time guidance based on screen content.
    """
    
    def __init__(self, vision_analyzer=None):
        self.vision_analyzer = vision_analyzer
        self.is_monitoring = False
        self.monitor_thread = None
        self.workspace_id = None
        self.interval = 10  # seconds between captures
        
        # Screen context
        self.screen_context = {
            'monitoring': False,
            'workspace_id': None,
            'last_screenshot': None,
            'last_analysis': None,
            'analysis_time': None,
            'previous_analyses': []  # Keep last 5
        }
    
    def start_monitoring(self, workspace_id: int = None):
        """Start continuous monitoring of workspace"""
        if self.is_monitoring:
            logger.warning("[ScreenMonitor] Already monitoring")
            return
        
        self.workspace_id = workspace_id
        self.is_monitoring = True
        self.screen_context['monitoring'] = True
        self.screen_context['workspace_id'] = workspace_id
        
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        logger.info(f"[ScreenMonitor] Started monitoring workspace {workspace_id}")
        print(f"[ScreenMonitor] 👁️ Observando escritorio {workspace_id if workspace_id else 'actual'}...")
    
    def stop_monitoring(self):
        """Stop monitoring"""
        self.is_monitoring = False
        self.screen_context['monitoring'] = False
        logger.info("[ScreenMonitor] Stopped monitoring")
        print("[ScreenMonitor] ✋ Dejé de observar")
    
    def get_current_screen(self) -> Dict:
        """Get latest screen analysis"""
        return {
            'analysis': self.screen_context['last_analysis'],
            'screenshot': self.screen_context['last_screenshot'],
            'time': self.screen_context['analysis_time']
        }
    
    def get_previous_screen(self, index: int = -1) -> Optional[Dict]:
        """Get previous analysis from history"""
        try:
            return self.screen_context['previous_analyses'][index]
        except IndexError:
            return None
    
    def analyze_current_screen(self, prompt: str = "Describe exactamente lo que ves en esta pantalla. Menciona errores, warnings, o problemas visibles.") -> Optional[str]:
        """
        Analyze current screenshot on-demand (to save CPU).
        
        Args:
            prompt: Custom prompt for analysis
            
        Returns:
            Analysis text or None
        """
        if not self.screen_context['last_screenshot'] or not self.vision_analyzer:
            return None
        
        try:
            result = self.vision_analyzer.analyze_image(
                self.screen_context['last_screenshot'],
                prompt
            )
            
            if result.get('success'):
                analysis = result['description']
                
                # Store previous if exists
                if self.screen_context['last_analysis']:
                    self.screen_context['previous_analyses'].append({
                        'analysis': self.screen_context['last_analysis'],
                        'screenshot': self.screen_context['last_screenshot'],
                        'time': self.screen_context['analysis_time']
                    })
                    
                    # Keep only last 5
                    if len(self.screen_context['previous_analyses']) > 5:
                        self.screen_context['previous_analyses'].pop(0)
                
                # Update current
                self.screen_context['last_analysis'] = analysis
                self.screen_context['analysis_time'] = datetime.now()
                
                return analysis
            
        except Exception as e:
            logger.error(f"[ScreenMonitor] Analysis error: {e}")
        
        return None
    
    def capture_workspace(self, workspace_id: Optional[int] = None) -> Optional[str]:
        """
        Capture screenshot of specific workspace.
        
        Args:
            workspace_id: Workspace number (None = current)
            
        Returns:
            Path to screenshot file or None
        """
        try:
            # Create temp file for screenshot
            fd, screenshot_path = tempfile.mkstemp(suffix='.png', prefix='sam_screen_')
            os.close(fd)
            
            # Capture current screen (workspace switching requires WM-specific commands)
            # Using scrot for now - captures current display
            result = subprocess.run(
                ['scrot', '-o', screenshot_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5
            )
            
            if result.returncode == 0:
                logger.info(f"[ScreenMonitor] Screenshot captured: {screenshot_path}")
                return screenshot_path
            else:
                logger.error("[ScreenMonitor] Screenshot failed")
                os.unlink(screenshot_path)
                return None
                
        except FileNotFoundError:
            logger.error("[ScreenMonitor] scrot not found. Install with: sudo pacman -S scrot")
            return None
        except Exception as e:
            logger.error(f"[ScreenMonitor] Capture error: {e}")
            return None
    
    def _monitor_loop(self):
        """Background monitoring loop - captures only, analysis on demand"""
        logger.info("[ScreenMonitor] Monitor loop started (on-demand mode)")
        
        while self.is_monitoring:
            try:
                # Just capture screenshot, don't analyze yet (save CPU)
                screenshot_path = self.capture_workspace(self.workspace_id)
                
                if screenshot_path:
                    # Store screenshot path only
                    if self.screen_context['last_screenshot']:
                        try:
                            os.unlink(self.screen_context['last_screenshot'])
                        except:
                            pass
                    
                    self.screen_context['last_screenshot'] = screenshot_path
                    self.screen_context['analysis_time'] = datetime.now()
                    logger.info(f"[ScreenMonitor] Screenshot updated")
                
                # Longer interval - just keeping screenshots fresh
                time.sleep(30)  # 30 seconds instead of 10
                
            except Exception as e:
                logger.error(f"[ScreenMonitor] Monitor loop error: {e}")
                time.sleep(30)
        
        logger.info("[ScreenMonitor] Monitor loop stopped")
    
    def compare_screens(self, before: Dict, after: Dict) -> str:
        """
        Compare two screen states.
        
        Returns:
            Comparison description
        """
        if not before or not after:
            return "No tengo suficiente historial para comparar."
        
        comparison = f"ANTES: {before.get('analysis', 'N/A')}\n\nAHORA: {after.get('analysis', 'N/A')}"
        return comparison


# Convenience function for testing
def test_screen_monitor():
    """Test screen monitoring"""
    print("=== Testing Screen Monitor ===\n")
    
    from modules.vision import VisionAnalyzer
    
    analyzer = VisionAnalyzer()
    monitor = ScreenMonitor(vision_analyzer=analyzer)
    
    print("Starting monitor for 30 seconds...")
    monitor.start_monitoring()
    
    time.sleep(30)
    
    monitor.stop_monitoring()
    
    current = monitor.get_current_screen()
    print(f"\nLast analysis: {current['analysis'][:200]}...")
    
    print("\n=== Test Complete ===")


if __name__ == "__main__":
    test_screen_monitor()

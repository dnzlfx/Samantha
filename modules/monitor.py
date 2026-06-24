"""
Samantha homelab monitor.
Background monitoring for homelab with alerts.
"""

import logging
import threading
import time
from typing import Dict, Optional, Callable
from datetime import datetime

logger = logging.getLogger(__name__)


class HomelabMonitor:
    """
    Background monitor for homelab with threshold alerts.
    """
    
    DEFAULT_THRESHOLDS = {
        'cpu_percent': 85.0,
        'mem_percent': 90.0,
        'disk_percent': 90.0
    }
    
    def __init__(self, homelab, check_interval: int = 60):
        """
        Args:
            homelab: HomeLab instance for SSH commands
            check_interval: Seconds between checks
        """
        self.homelab = homelab
        self.check_interval = check_interval
        self.thresholds = self.DEFAULT_THRESHOLDS.copy()
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.alerts: list = []
        self.on_alert: Optional[Callable] = None
        self.last_check: Optional[datetime] = None
        self.last_status: Dict = {}
        
        logger.info("[Sam] HomelabMonitor initialized")
    
    def set_threshold(self, metric: str, value: float):
        """Set alert threshold for a metric"""
        if metric in self.thresholds:
            self.thresholds[metric] = value
            logger.info(f"[Sam] Threshold set: {metric} = {value}%")
    
    def set_alert_callback(self, callback: Callable):
        """Set callback function for alerts"""
        self.on_alert = callback
    
    def start(self):
        """Start background monitoring"""
        if self.running:
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()
        logger.info("[Sam] Background monitoring started")
    
    def stop(self):
        """Stop background monitoring"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("[Sam] Background monitoring stopped")
    
    def _monitor_loop(self):
        """Main monitoring loop"""
        while self.running:
            try:
                self._check_homelab()
            except Exception as e:
                logger.error(f"[Sam] Monitor check failed: {e}")
            
            # Sleep in small intervals to allow quick shutdown
            for _ in range(self.check_interval):
                if not self.running:
                    break
                time.sleep(1)
    
    def _check_homelab(self):
        """Perform a single check (silent mode)"""
        if not self.homelab:
            return
        
        self.last_check = datetime.now()
        alerts = []
        
        # Get resource usage (QUIET mode)
        resources = {}
        
        # CPU - quiet
        cpu_result = self.homelab.execute_remote(
            "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'",
            require_confirmation=False, stream_output=False, quiet=True
        )
        if cpu_result['success']:
            try:
                resources['cpu_percent'] = float(cpu_result['output'].strip().replace(',', '.'))
            except:
                resources['cpu_percent'] = 0.0
        
        # Memory - quiet
        mem_result = self.homelab.execute_remote(
            "free | grep Mem | awk '{printf \"%.1f\", $3/$2 * 100.0}'",
            require_confirmation=False, stream_output=False, quiet=True
        )
        if mem_result['success']:
            try:
                resources['mem_percent'] = float(mem_result['output'].strip())
            except:
                resources['mem_percent'] = 0.0
        
        # Disk - quiet
        disk_result = self.homelab.execute_remote(
            "df / | tail -1 | awk '{print $5}' | tr -d '%'",
            require_confirmation=False, stream_output=False, quiet=True
        )
        if disk_result['success']:
            try:
                resources['disk_percent'] = float(disk_result['output'].strip())
            except:
                resources['disk_percent'] = 0.0
        
        self.last_status['resources'] = resources
        
        # Check thresholds
        cpu = resources.get('cpu_percent', 0)
        if cpu > self.thresholds['cpu_percent']:
            alert = f"⚠️ CPU alto: {cpu:.1f}% (umbral: {self.thresholds['cpu_percent']}%)"
            alerts.append(alert)
        
        mem = resources.get('mem_percent', 0)
        if mem > self.thresholds['mem_percent']:
            alert = f"⚠️ RAM alta: {mem:.1f}% (umbral: {self.thresholds['mem_percent']}%)"
            alerts.append(alert)
        
        disk = resources.get('disk_percent', 0)
        if disk > self.thresholds['disk_percent']:
            alert = f"⚠️ Disco lleno: {disk:.1f}% (umbral: {self.thresholds['disk_percent']}%)"
            alerts.append(alert)
        
        # Check Docker containers - quiet
        docker_result = self.homelab.execute_remote(
            'docker ps -a --format "{{.ID}}|{{.Names}}|{{.Status}}|{{.Image}}"',
            require_confirmation=False, stream_output=False, quiet=True
        )
        
        containers = []
        if docker_result['success']:
            for line in docker_result['output'].split('\n'):
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 3:
                        containers.append({
                            'name': parts[1],
                            'status': parts[2]
                        })
        
        self.last_status['containers'] = containers
        
        for container in containers:
            if 'Exited' in container.get('status', '') or 'Dead' in container.get('status', ''):
                alert = f"🐳 Container caído: {container['name']} ({container['status']})"
                alerts.append(alert)
        
        # Process alerts
        if alerts:
            self.alerts.extend(alerts)
            if self.on_alert:
                for alert in alerts:
                    self.on_alert(alert)
        
        logger.debug(f"[Sam] Monitor check complete: {len(alerts)} alerts")
    
    def get_pending_alerts(self) -> list:
        """Get and clear pending alerts"""
        pending = self.alerts.copy()
        self.alerts.clear()
        return pending
    
    def get_status(self) -> Dict:
        """Get current monitoring status"""
        return {
            'running': self.running,
            'last_check': self.last_check.isoformat() if self.last_check else None,
            'thresholds': self.thresholds,
            'resources': self.last_status.get('resources', {}),
            'containers_count': len(self.last_status.get('containers', [])),
            'pending_alerts': len(self.alerts)
        }

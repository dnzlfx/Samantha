"""
Samantha CVE scanner.
Proactive security vulnerability scanning.
"""

import logging
import requests
import re
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class CVEScanner:
    """
    Scans for CVE vulnerabilities based on detected technologies in conversation.
    """
    
    CVE_API_BASE = "https://cve.circl.lu/api"
    CRITICAL_CVSS_THRESHOLD = 7.0
    
    # Technology detection patterns
    TECH_PATTERNS = {
        'docker': r'docker(?:\s+|/)(\d+\.\d+(?:\.\d+)?)',
        'nginx': r'nginx(?:\s+|/)(\d+\.\d+(?:\.\d+)?)',
        'python': r'python(?:\s+)?(\d+\.\d+(?:\.\d+)?)',
        'node': r'node(?:js)?(?:\s+|/)(\d+\.\d+(?:\.\d+)?)',
        'apache': r'apache(?:\s+)?(\d+\.\d+(?:\.\d+)?)',
        'mysql': r'mysql(?:\s+)?(\d+\.\d+(?:\.\d+)?)',
        'postgresql': r'postgres(?:ql)?(?:\s+)?(\d+\.\d+(?:\.\d+)?)',
    }
    
    def __init__(self):
        self.detected_technologies: Dict[str, str] = {}
        self.found_cves: List[Dict] = []
    
    def detect_technologies(self, text: str) -> Dict[str, str]:
        """
        Detects technologies and versions mentioned in text.
        
        Args:
            text: Text to scan
            
        Returns:
            Dict of {technology: version}
        """
        detected = {}
        text_lower = text.lower()
        
        for tech, pattern in self.TECH_PATTERNS.items():
            match = re.search(pattern, text_lower)
            if match:
                version = match.group(1) if match.groups() else "unknown"
                detected[tech] = version
                logger.info(f"[Sam] Detected technology: {tech} {version}")
        
        return detected
    
    def check_cve(self, technology: str, version: Optional[str] = None) -> List[Dict]:
        """
        Checks for CVEs affecting a technology/version.
        
        Args:
            technology: Technology name
            version: Optional version string
            
        Returns:
            List of CVE dicts
        """
        try:
            # Build API URL
            if version and version != "unknown":
                url = f"{self.CVE_API_BASE}/search/{technology}/{version}"
            else:
                url = f"{self.CVE_API_BASE}/search/{technology}"
            
            logger.info(f"[Sam] Checking CVEs: {url}")
            
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                cves = response.json()
                
                # Filter for critical CVEs
                critical_cves = []
                for cve in cves[:10]:  # Limit to 10 most recent
                    if 'cvss' in cve and float(cve.get('cvss', 0)) >= self.CRITICAL_CVSS_THRESHOLD:
                        critical_cves.append({
                            'id': cve.get('id'),
                            'cvss': float(cve.get('cvss', 0)),
                            'summary': cve.get('summary', 'No summary available'),
                            'published': cve.get('Published', 'Unknown')
                        })
                
                return critical_cves
            else:
                logger.warning(f"[Sam] CVE API returned {response.status_code}")
                return []
                
        except Exception as e:
            logger.error(f"[Sam] CVE check failed: {e}")
            return []
    
    def scan_text(self, text: str) -> List[Dict]:
        """
        Scans text for technologies and checks for CVEs.
        
        Args:
            text: Text to scan
            
        Returns:
            List of critical CVE findings
        """
        # Detect technologies
        detected = self.detect_technologies(text)
        
        if not detected:
            return []
        
        # Update known technologies
        self.detected_technologies.update(detected)
        
        # Check each technology for CVEs
        all_cves = []
        for tech, version in detected.items():
            cves = self.check_cve(tech, version)
            for cve in cves:
                cve['technology'] = tech
                cve['version'] = version
                all_cves.append(cve)
        
        if all_cves:
            self.found_cves.extend(all_cves)
        
        return all_cves
    
    def format_alert(self, cves: List[Dict]) -> str:
        """
        Formats CVE findings as an alert message.
        
        Args:
            cves: List of CVE dicts
            
        Returns:
            Formatted alert string
        """
        if not cves:
            return ""
        
        alert = "\n🔒 [ALERTA DE SEGURIDAD]\n"
        alert += "=" * 60 + "\n\n"
        
        for cve in cves[:5]:  # Show top 5
            alert += f"❌ {cve['id']} (CVSS: {cve['cvss']})\n"
            alert += f"   Tecnología: {cve['technology']} {cve['version']}\n"
            alert += f"   {cve['summary'][:100]}...\n"
            alert += f"   Publicado: {cve['published']}\n\n"
        
        alert += "=" * 60 + "\n"
        
        return alert

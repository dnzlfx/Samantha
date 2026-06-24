"""
SAM v2.0 - Backup Module
Automated backups for docker-compose, configs, and MySQL databases.
"""

import logging
import os
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class BackupManager:
    """
    Manages automated backups for homelab infrastructure.
    """
    
    # Default backup location
    BACKUP_DIR = "/mnt/datos/backups"
    LOCAL_BACKUP_DIR = Path.home() / ".config" / "sam" / "backups"
    
    def __init__(self, homelab=None):
        """
        Args:
            homelab: HomelabManager instance for remote operations
        """
        self.homelab = homelab
        self.local_backup_dir = self.LOCAL_BACKUP_DIR
        self.local_backup_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("[Sam] BackupManager initialized")
    
    def _get_timestamp(self) -> str:
        """Generate timestamp for backup names"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")
    
    def _calculate_checksum(self, filepath: str) -> str:
        """Calculate MD5 checksum of a file"""
        try:
            with open(filepath, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except:
            return "N/A"
    
    # ================================================================
    # DOCKER COMPOSE BACKUPS
    # ================================================================
    
    def backup_docker_compose(self) -> Dict:
        """
        Backup all docker-compose.yml and .env files from homelab.
        
        Returns:
            Dict with success status and backup info
        """
        if not self.homelab:
            return {'success': False, 'error': 'Homelab not configured'}
        
        timestamp = self._get_timestamp()
        backup_name = f"docker_compose_{timestamp}"
        
        try:
            # Find all docker-compose files on remote server
            find_cmd = "find /home /opt /root -name 'docker-compose*.yml' -o -name '.env' 2>/dev/null | head -50"
            result = self.homelab.execute_remote(find_cmd, quiet=True)
            
            if not result['success']:
                return {'success': False, 'error': 'Failed to find docker-compose files'}
            
            files = [f.strip() for f in result['output'].split('\n') if f.strip()]
            
            if not files:
                return {'success': False, 'error': 'No docker-compose files found'}
            
            # Create backup directory on remote
            remote_backup = f"{self.BACKUP_DIR}/{backup_name}"
            self.homelab.execute_remote(f"mkdir -p {remote_backup}", quiet=True)
            
            # Copy files preserving directory structure
            for f in files:
                # Create subdirectory structure
                rel_path = f.lstrip('/')
                dir_path = os.path.dirname(rel_path)
                self.homelab.execute_remote(f"mkdir -p {remote_backup}/{dir_path}", quiet=True)
                self.homelab.execute_remote(f"cp {f} {remote_backup}/{rel_path}", quiet=True)
            
            # Create tarball
            tar_cmd = f"cd {self.BACKUP_DIR} && tar -czf {backup_name}.tar.gz {backup_name} && rm -rf {backup_name}"
            self.homelab.execute_remote(tar_cmd, quiet=True)
            
            # Get size
            size_result = self.homelab.execute_remote(f"du -h {self.BACKUP_DIR}/{backup_name}.tar.gz | cut -f1", quiet=True)
            size = size_result['output'].strip() if size_result['success'] else 'Unknown'
            
            return {
                'success': True,
                'name': backup_name,
                'path': f"{self.BACKUP_DIR}/{backup_name}.tar.gz",
                'files_count': len(files),
                'size': size,
                'timestamp': timestamp
            }
            
        except Exception as e:
            logger.error(f"[Sam] Docker compose backup failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def backup_configs(self, paths: List[str] = None) -> Dict:
        """
        Backup system configuration files.
        
        Args:
            paths: List of paths to backup (default: /etc/nginx, /etc/pihole, etc.)
        """
        if not self.homelab:
            return {'success': False, 'error': 'Homelab not configured'}
        
        default_paths = [
            "/etc/nginx",
            "/etc/pihole", 
            "/etc/docker",
            "/root/.config",
            "/etc/hosts"
        ]
        
        paths = paths or default_paths
        timestamp = self._get_timestamp()
        backup_name = f"configs_{timestamp}"
        
        try:
            remote_backup = f"{self.BACKUP_DIR}/{backup_name}"
            self.homelab.execute_remote(f"mkdir -p {remote_backup}", quiet=True)
            
            backed_up = []
            for path in paths:
                # Check if path exists
                check = self.homelab.execute_remote(f"test -e {path} && echo exists", quiet=True)
                if check['success'] and 'exists' in check['output']:
                    self.homelab.execute_remote(f"cp -r {path} {remote_backup}/", quiet=True)
                    backed_up.append(path)
            
            if not backed_up:
                return {'success': False, 'error': 'No config paths found'}
            
            # Create tarball
            tar_cmd = f"cd {self.BACKUP_DIR} && tar -czf {backup_name}.tar.gz {backup_name} && rm -rf {backup_name}"
            self.homelab.execute_remote(tar_cmd, quiet=True)
            
            size_result = self.homelab.execute_remote(f"du -h {self.BACKUP_DIR}/{backup_name}.tar.gz | cut -f1", quiet=True)
            size = size_result['output'].strip() if size_result['success'] else 'Unknown'
            
            return {
                'success': True,
                'name': backup_name,
                'path': f"{self.BACKUP_DIR}/{backup_name}.tar.gz",
                'paths_backed': backed_up,
                'size': size,
                'timestamp': timestamp
            }
            
        except Exception as e:
            logger.error(f"[Sam] Config backup failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def backup_mysql(self, database: str = None) -> Dict:
        """
        Backup MySQL/MariaDB database(s).
        
        Args:
            database: Specific database name, or None for all databases
        """
        if not self.homelab:
            return {'success': False, 'error': 'Homelab not configured'}
        
        timestamp = self._get_timestamp()
        
        try:
            if database:
                backup_name = f"mysql_{database}_{timestamp}"
                dump_cmd = f"mysqldump {database} 2>/dev/null"
            else:
                backup_name = f"mysql_all_{timestamp}"
                dump_cmd = "mysqldump --all-databases 2>/dev/null"
            
            # Create dump and compress
            full_cmd = f"{dump_cmd} | gzip > {self.BACKUP_DIR}/{backup_name}.sql.gz"
            result = self.homelab.execute_remote(full_cmd, quiet=True)
            
            if not result['success']:
                return {'success': False, 'error': 'MySQL dump failed'}
            
            # Get size
            size_result = self.homelab.execute_remote(f"du -h {self.BACKUP_DIR}/{backup_name}.sql.gz | cut -f1", quiet=True)
            size = size_result['output'].strip() if size_result['success'] else 'Unknown'
            
            return {
                'success': True,
                'name': backup_name,
                'path': f"{self.BACKUP_DIR}/{backup_name}.sql.gz",
                'database': database or 'all',
                'size': size,
                'timestamp': timestamp
            }
            
        except Exception as e:
            logger.error(f"[Sam] MySQL backup failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def backup_full(self) -> Dict:
        """Create a full backup (docker + configs + mysql)"""
        results = {
            'docker': self.backup_docker_compose(),
            'configs': self.backup_configs(),
            'mysql': self.backup_mysql()
        }
        
        success_count = sum(1 for r in results.values() if r.get('success'))
        
        return {
            'success': success_count > 0,
            'results': results,
            'summary': f"{success_count}/3 backups completed"
        }
    
    # ================================================================
    # BACKUP MANAGEMENT
    # ================================================================
    
    def list_backups(self, backup_type: str = None) -> List[Dict]:
        """
        List available backups.
        
        Args:
            backup_type: Filter by type (docker, configs, mysql) or None for all
        """
        if not self.homelab:
            return []
        
        try:
            pattern = f"{backup_type}_*" if backup_type else "*"
            cmd = f"ls -lh {self.BACKUP_DIR}/{pattern}.tar.gz {self.BACKUP_DIR}/{pattern}.sql.gz 2>/dev/null | tail -20"
            result = self.homelab.execute_remote(cmd, quiet=True)
            
            if not result['success']:
                return []
            
            backups = []
            for line in result['output'].split('\n'):
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) >= 9:
                    backups.append({
                        'size': parts[4],
                        'date': f"{parts[5]} {parts[6]} {parts[7]}",
                        'name': parts[8].split('/')[-1]
                    })
            
            return backups
            
        except Exception as e:
            logger.error(f"[Sam] List backups failed: {e}")
            return []
    
    def restore_backup(self, backup_name: str, target_dir: str = None) -> Dict:
        """
        Restore a backup.
        
        Args:
            backup_name: Name of backup file
            target_dir: Where to restore (default: temp dir for review)
        """
        if not self.homelab:
            return {'success': False, 'error': 'Homelab not configured'}
        
        try:
            backup_path = f"{self.BACKUP_DIR}/{backup_name}"
            target = target_dir or f"/tmp/restore_{self._get_timestamp()}"
            
            # Check if backup exists
            check = self.homelab.execute_remote(f"test -f {backup_path} && echo exists", quiet=True)
            if 'exists' not in check.get('output', ''):
                return {'success': False, 'error': f'Backup not found: {backup_name}'}
            
            # Create target and extract
            self.homelab.execute_remote(f"mkdir -p {target}", quiet=True)
            
            if backup_name.endswith('.tar.gz'):
                cmd = f"tar -xzf {backup_path} -C {target}"
            elif backup_name.endswith('.sql.gz'):
                cmd = f"gunzip -c {backup_path} > {target}/restore.sql"
            else:
                return {'success': False, 'error': 'Unknown backup format'}
            
            result = self.homelab.execute_remote(cmd, quiet=True)
            
            return {
                'success': result['success'],
                'backup': backup_name,
                'restored_to': target,
                'note': 'Review restored files before applying'
            }
            
        except Exception as e:
            logger.error(f"[Sam] Restore failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def verify_backup(self, backup_name: str) -> Dict:
        """Verify backup integrity"""
        if not self.homelab:
            return {'success': False, 'error': 'Homelab not configured'}
        
        try:
            backup_path = f"{self.BACKUP_DIR}/{backup_name}"
            
            # Check file exists
            check = self.homelab.execute_remote(f"test -f {backup_path} && echo exists", quiet=True)
            if 'exists' not in check.get('output', ''):
                return {'success': False, 'error': 'Backup not found'}
            
            # Try to list contents (validates archive)
            if backup_name.endswith('.tar.gz'):
                cmd = f"tar -tzf {backup_path} | head -5"
            elif backup_name.endswith('.sql.gz'):
                cmd = f"gunzip -t {backup_path} && echo 'valid'"
            else:
                return {'success': False, 'error': 'Unknown format'}
            
            result = self.homelab.execute_remote(cmd, quiet=True)
            
            # Get checksum
            md5_result = self.homelab.execute_remote(f"md5sum {backup_path} | cut -d' ' -f1", quiet=True)
            checksum = md5_result['output'].strip() if md5_result['success'] else 'N/A'
            
            return {
                'success': result['success'],
                'backup': backup_name,
                'valid': result['success'],
                'checksum': checksum
            }
            
        except Exception as e:
            logger.error(f"[Sam] Verify failed: {e}")
            return {'success': False, 'error': str(e)}
    
    def cleanup_old_backups(self, keep_days: int = 30) -> Dict:
        """Remove backups older than specified days"""
        if not self.homelab:
            return {'success': False, 'error': 'Homelab not configured'}
        
        try:
            cmd = f"find {self.BACKUP_DIR} -name '*.tar.gz' -o -name '*.sql.gz' -mtime +{keep_days} -delete -print"
            result = self.homelab.execute_remote(cmd, quiet=True)
            
            deleted = [f.strip() for f in result['output'].split('\n') if f.strip()]
            
            return {
                'success': True,
                'deleted_count': len(deleted),
                'deleted': deleted[:10]  # Show first 10
            }
            
        except Exception as e:
            logger.error(f"[Sam] Cleanup failed: {e}")
            return {'success': False, 'error': str(e)}

"""
SAM v2.0 - DevStack Module
PHP/MySQL development assistant and stack management.
"""

import logging
import subprocess
import os
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DevStackManager:
    """
    Manages PHP/MySQL development environment and provides code assistance.
    """
    
    def __init__(self, homelab=None):
        """
        Args:
            homelab: HomelabManager instance for remote operations
        """
        self.homelab = homelab
        logger.info("[Sam] DevStackManager initialized")
    
    # ================================================================
    # PHP TOOLS
    # ================================================================
    
    def php_check(self, filepath: str) -> Dict:
        """
        Check PHP file for syntax errors.
        
        Args:
            filepath: Path to PHP file
        """
        if not os.path.exists(filepath):
            return {'success': False, 'error': f'File not found: {filepath}'}
        
        try:
            result = subprocess.run(
                ['php', '-l', filepath],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                return {
                    'success': True,
                    'file': filepath,
                    'status': 'No syntax errors',
                    'output': result.stdout.strip()
                }
            else:
                # Parse error message
                error = result.stdout + result.stderr
                return {
                    'success': False,
                    'file': filepath,
                    'error': error.strip(),
                    'has_errors': True
                }
                
        except FileNotFoundError:
            return {'success': False, 'error': 'PHP not installed'}
        except subprocess.TimeoutExpired:
            return {'success': False, 'error': 'Check timed out'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def php_lint(self, directory: str) -> Dict:
        """
        Lint all PHP files in a directory.
        
        Args:
            directory: Directory to scan
        """
        if not os.path.isdir(directory):
            return {'success': False, 'error': f'Directory not found: {directory}'}
        
        results = {'passed': [], 'failed': [], 'total': 0}
        
        try:
            for root, dirs, files in os.walk(directory):
                # Skip vendor and node_modules
                dirs[:] = [d for d in dirs if d not in ['vendor', 'node_modules', '.git']]
                
                for file in files:
                    if file.endswith('.php'):
                        filepath = os.path.join(root, file)
                        check = self.php_check(filepath)
                        results['total'] += 1
                        
                        if check.get('success'):
                            results['passed'].append(filepath)
                        else:
                            results['failed'].append({
                                'file': filepath,
                                'error': check.get('error', 'Unknown error')
                            })
            
            return {
                'success': True,
                'directory': directory,
                'total': results['total'],
                'passed': len(results['passed']),
                'failed': len(results['failed']),
                'errors': results['failed'][:10]  # First 10 errors
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    # ================================================================
    # MYSQL TOOLS
    # ================================================================
    
    def mysql_status(self, remote: bool = False) -> Dict:
        """
        Check MySQL/MariaDB service status.
        
        Args:
            remote: Check on homelab server instead of local
        """
        if remote and self.homelab:
            result = self.homelab.execute_remote("systemctl is-active mariadb mysql 2>/dev/null | head -1", quiet=True)
            status = result['output'].strip() if result['success'] else 'unknown'
            
            # Get more info
            info = self.homelab.execute_remote("mysql -e 'SELECT VERSION();' 2>/dev/null | tail -1", quiet=True)
            version = info['output'].strip() if info['success'] else 'unknown'
            
            return {
                'success': True,
                'location': 'remote',
                'status': status,
                'version': version,
                'running': status == 'active'
            }
        else:
            try:
                result = subprocess.run(
                    ['systemctl', 'is-active', 'mariadb'],
                    capture_output=True,
                    text=True
                )
                status = result.stdout.strip()
                
                return {
                    'success': True,
                    'location': 'local',
                    'status': status,
                    'running': status == 'active'
                }
            except:
                return {'success': False, 'error': 'Could not check MySQL status'}
    
    def mysql_create_db(self, db_name: str, remote: bool = True) -> Dict:
        """
        Create a new MySQL database.
        
        Args:
            db_name: Database name
            remote: Create on homelab server
        """
        # Validate db name (alphanumeric + underscore only)
        if not db_name.replace('_', '').isalnum():
            return {'success': False, 'error': 'Invalid database name'}
        
        cmd = f"mysql -e 'CREATE DATABASE IF NOT EXISTS {db_name};'"
        
        if remote and self.homelab:
            result = self.homelab.execute_remote(cmd, quiet=True)
        else:
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                result = {'success': result.returncode == 0, 'output': result.stdout}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        if result.get('success'):
            return {'success': True, 'database': db_name, 'created': True}
        else:
            return {'success': False, 'error': result.get('output', 'Failed to create database')}
    
    def mysql_query(self, database: str, query: str, remote: bool = True) -> Dict:
        """
        Execute a MySQL query.
        
        Args:
            database: Database name
            query: SQL query to execute
            remote: Execute on homelab server
        """
        # Safety: only allow SELECT queries through this interface
        query_upper = query.strip().upper()
        if not query_upper.startswith(('SELECT', 'SHOW', 'DESCRIBE', 'EXPLAIN')):
            return {'success': False, 'error': 'Only SELECT/SHOW/DESCRIBE queries allowed for safety'}
        
        cmd = f'mysql {database} -e "{query}" 2>&1'
        
        if remote and self.homelab:
            result = self.homelab.execute_remote(cmd, quiet=True)
            output = result['output'] if result['success'] else ''
        else:
            try:
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
                output = proc.stdout
                result = {'success': proc.returncode == 0}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        if result.get('success'):
            # Parse output into rows
            lines = output.strip().split('\n')
            return {
                'success': True,
                'database': database,
                'rows': len(lines) - 1 if lines else 0,
                'output': output[:2000]  # Limit output
            }
        else:
            return {'success': False, 'error': output}
    
    def mysql_list_dbs(self, remote: bool = True) -> List[str]:
        """List all databases"""
        cmd = "mysql -e 'SHOW DATABASES;' 2>/dev/null | tail -n +2"
        
        if remote and self.homelab:
            result = self.homelab.execute_remote(cmd, quiet=True)
            if result['success']:
                return [db.strip() for db in result['output'].split('\n') if db.strip()]
        else:
            try:
                proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                if proc.returncode == 0:
                    return [db.strip() for db in proc.stdout.split('\n') if db.strip()]
            except:
                pass
        
        return []
    
    # ================================================================
    # STACK MANAGEMENT
    # ================================================================
    
    def stack_status(self, remote: bool = True) -> Dict:
        """
        Get status of web stack (Apache/Nginx + MySQL + PHP).
        """
        services = {
            'web': ['nginx', 'apache2', 'httpd'],
            'database': ['mariadb', 'mysql', 'postgresql'],
            'php': ['php-fpm', 'php8.2-fpm', 'php8.1-fpm']
        }
        
        status = {}
        
        for category, service_list in services.items():
            for service in service_list:
                if remote and self.homelab:
                    result = self.homelab.execute_remote(f"systemctl is-active {service} 2>/dev/null", quiet=True)
                    if result['success'] and result['output'].strip() == 'active':
                        status[category] = {'service': service, 'status': 'active'}
                        break
                else:
                    try:
                        proc = subprocess.run(['systemctl', 'is-active', service], 
                                            capture_output=True, text=True)
                        if proc.stdout.strip() == 'active':
                            status[category] = {'service': service, 'status': 'active'}
                            break
                    except:
                        pass
            
            if category not in status:
                status[category] = {'service': 'none', 'status': 'inactive'}
        
        return {
            'success': True,
            'location': 'remote' if remote else 'local',
            'stack': status
        }
    
    def stack_restart(self, service: str, remote: bool = True) -> Dict:
        """
        Restart a stack service.
        
        Args:
            service: Service name (nginx, mysql, php-fpm, etc.)
            remote: Restart on homelab server
        """
        cmd = f"systemctl restart {service}"
        
        if remote and self.homelab:
            result = self.homelab.execute_remote(cmd, quiet=True)
        else:
            try:
                proc = subprocess.run(['sudo', 'systemctl', 'restart', service],
                                     capture_output=True, text=True)
                result = {'success': proc.returncode == 0, 'output': proc.stdout + proc.stderr}
            except Exception as e:
                return {'success': False, 'error': str(e)}
        
        if result.get('success'):
            return {'success': True, 'service': service, 'restarted': True}
        else:
            return {'success': False, 'error': result.get('output', 'Restart failed')}
    
    # ================================================================
    # CODE ANALYSIS
    # ================================================================
    
    def analyze_sql_injection(self, filepath: str) -> Dict:
        """
        Basic SQL injection vulnerability scanner for PHP files.
        
        Args:
            filepath: PHP file to analyze
        """
        if not os.path.exists(filepath):
            return {'success': False, 'error': 'File not found'}
        
        vulnerabilities = []
        suspicious_patterns = [
            ('$_GET', 'Direct use of $_GET in query'),
            ('$_POST', 'Direct use of $_POST in query'),
            ('$_REQUEST', 'Direct use of $_REQUEST in query'),
            ('mysql_query', 'Deprecated mysql_query function'),
            ('" . $', 'String concatenation in SQL'),
            ("' . $", 'String concatenation in SQL'),
        ]
        
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                lines = f.readlines()
            
            for i, line in enumerate(lines, 1):
                for pattern, description in suspicious_patterns:
                    if pattern in line and ('query' in line.lower() or 'sql' in line.lower() or 'mysql' in line.lower()):
                        vulnerabilities.append({
                            'line': i,
                            'pattern': pattern,
                            'description': description,
                            'code': line.strip()[:100]
                        })
            
            return {
                'success': True,
                'file': filepath,
                'vulnerabilities': len(vulnerabilities),
                'issues': vulnerabilities[:10]  # First 10
            }
            
        except Exception as e:
            return {'success': False, 'error': str(e)}

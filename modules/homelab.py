"""
Samantha HomeLab management.
SSH-based remote server management with security controls.
"""

import logging
import sys
from typing import Dict, Optional, List
import paramiko
from pathlib import Path

from core.command_safety import is_allowlisted

logger = logging.getLogger(__name__)


class HomeLab:
    """
    Manages SSH connections to home lab servers with two-tier permission system.
    SAFE commands execute automatically, DANGEROUS commands require confirmation.
    Supports multiple server profiles.
    """
    
    # Server profiles
    SERVER_PROFILES = {
        'main': {
            'host': '192.168.0.116',
            'user': 'root',
            'description': 'DietPi Main Server',
            'color': 'cyan'
        },
        'switch': {
            'host': '192.168.0.110',
            'user': 'chris',
            'description': 'Ubuntu Switch',
            'color': 'green'
        }
    }
    
    # Default configuration
    DEFAULT_HOST = "192.168.0.116"
    DEFAULT_USER = "root"
    DEFAULT_KEY = str(Path.home() / ".ssh" / "id_ed25519")
    DEFAULT_TIMEOUT = 30
    
    # Safe commands that can auto-execute
    SAFE_COMMANDS = [
        'df', 'docker ps', 'docker images', 'systemctl status',
        'free', 'tail', 'cat', 'ls', 'pwd', 'whoami', 'uptime',
        'top -bn1', 'htop -n1', 'ps aux', 'netstat', 'ss',
        'journalctl', 'dmesg', 'uname', 'hostname'
    ]
    
    # Dangerous command patterns (require confirmation)
    DANGEROUS_PATTERNS = [
        'rm', 'delete', 'restart', 'reboot', 'shutdown', 'halt',
        'kill', 'pkill', 'systemctl restart', 'systemctl stop',
        'docker restart', 'docker stop', 'docker rm', 'docker kill',
        'nginx -s reload', 'service restart', 'init 6', 'poweroff'
    ]
    
    def __init__(
        self,
        host: str = DEFAULT_HOST,
        user: str = DEFAULT_USER,
        key_path: str = DEFAULT_KEY,
        timeout: int = DEFAULT_TIMEOUT,
        profile: str = None
    ):
        # If profile is specified, use profile settings
        if profile and profile in self.SERVER_PROFILES:
            profile_config = self.SERVER_PROFILES[profile]
            self.host = profile_config['host']
            self.user = profile_config['user']
            self.description = profile_config['description']
            self.color = profile_config['color']
            self.profile = profile
        else:
            self.host = host
            self.user = user
            self.description = f"Server {host}"
            self.color = 'white'
            self.profile = None
        
        self.key_path = key_path
        self.timeout = timeout
        self.ssh_client: Optional[paramiko.SSHClient] = None
        
        logger.info(f"[Sam] HomeLab initialized for {self.user}@{self.host}")
    
    def _is_safe_command(self, command: str) -> bool:
        """
        Checks if a command is in the safe list.
        
        Args:
            command: Command to check
            
        Returns:
            True if safe, False if dangerous
        """
        if not is_allowlisted(command, self.SAFE_COMMANDS):
            return False

        # Allowlisted, but still reject explicitly dangerous forms such as
        # `systemctl restart` (allowed prefix `systemctl status` aside).
        command_lower = command.lower().strip()
        return not any(pattern in command_lower for pattern in self.DANGEROUS_PATTERNS)
    
    def connect(self) -> bool:
        """
        Establishes SSH connection to home lab server.
        
        Returns:
            True if connected successfully
        """
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            self.ssh_client.connect(
                hostname=self.host,
                username=self.user,
                key_filename=self.key_path,
                timeout=10
            )
            
            logger.info(f"[Sam] ✅ Connected to {self.user}@{self.host}")
            return True
            
        except Exception as e:
            logger.error(f"[Sam] ❌ SSH connection failed: {e}")
            return False
    
    def disconnect(self):
        """Closes SSH connection"""
        if self.ssh_client:
            self.ssh_client.close()
            logger.info("[Sam] SSH connection closed")
    
    def execute_remote(
        self,
        command: str,
        require_confirmation: bool = True,
        stream_output: bool = True,
        quiet: bool = False
    ) -> Dict:
        """
        Executes command on remote server with real-time output.
        
        Args:
            command: Command to execute
            require_confirmation: Whether to ask for confirmation (overridden for safe commands)
            stream_output: Whether to stream output in real-time
            quiet: If True, suppress all console output (for background monitoring)
            
        Returns:
            Dict with success, output, error
        """
        # Determine if command is safe
        is_safe = self._is_safe_command(command)
        
        # Ask for confirmation if dangerous
        if not is_safe and require_confirmation:
            from rich.prompt import Confirm
            from rich.console import Console
            
            console = Console()
            console.print("\n[red]⚠️  DANGEROUS COMMAND DETECTED[/red]")
            console.print(f"[yellow]Command:[/yellow] {command}")
            console.print(f"[yellow]Server:[/yellow] {self.user}@{self.host}")
            
            confirmed = Confirm.ask("[red]Execute this command?[/red]", default=False)
            
            if not confirmed:
                logger.info("[Sam] User cancelled dangerous command")
                return {
                    'success': False,
                    'output': '',
                    'error': 'Operation cancelled by user',
                    'cancelled': True
                }
        
        # Note: the command runs through a remote shell as-is. Safety comes from
        # the allowlist gate above plus explicit confirmation, not from quoting.

        # Connect if not already connected
        if not self.ssh_client or not self.ssh_client.get_transport() or not self.ssh_client.get_transport().is_active():
            if not self.connect():
                return {
                    'success': False,
                    'output': '',
                    'error': 'Failed to establish SSH connection'
                }
        
        if not quiet:
            print(f"\n{'='*60}")
            print(f"🌐 Ejecutando en {self.user}@{self.host}: {command}")
            print(f"{'='*60}\n")
        
        try:
            # Execute command
            stdin, stdout, stderr = self.ssh_client.exec_command(
                command,
                timeout=self.timeout
            )
            
            output_lines = []
            error_lines = []
            
            if stream_output:
                # Stream output in real-time
                for line in stdout:
                    line = line.rstrip()
                    print(line)
                    sys.stdout.flush()
                    output_lines.append(line)
                
                # Read errors
                for line in stderr:
                    error_lines.append(line.rstrip())
            else:
                # Read all at once
                output_lines = [line.rstrip() for line in stdout.readlines()]
                error_lines = [line.rstrip() for line in stderr.readlines()]
            
            # Get exit status
            exit_status = stdout.channel.recv_exit_status()
            
            output_str = '\n'.join(output_lines)
            error_str = '\n'.join(error_lines) if error_lines else None
            
            if not quiet:
                print(f"\n{'='*60}")
                if exit_status == 0:
                    print("✅ Comando remoto completado")
                else:
                    print(f"❌ Comando terminó con código {exit_status}")
                print(f"{'='*60}\n")
            
            # Log this operation
            logger.info(f"[Sam] Remote command executed: {command} (exit: {exit_status})")
            
            return {
                'success': exit_status == 0,
                'output': output_str,
                'error': error_str,
                'exit_status': exit_status
            }
            
        except Exception as e:
            logger.error(f"[Sam] Remote execution failed: {e}")
            return {
                'success': False,
                'output': '',
                'error': str(e)
            }
    
    def audit_log(self, command: str, result: Dict):
        """
        Logs command execution for audit trail.
        
        Args:
            command: Executed command
            result: Execution result
        """
        # This would typically write to a dedicated audit log file
        logger.info(f"[Sam][AUDIT] Command: {command}, Success: {result.get('success')}, Exit: {result.get('exit_status')}")
    
    def quick_diagnostic(self) -> Dict:
        """
        Runs a set of diagnostic commands on the server.
        
        Returns:
            Dict with diagnostic results
        """
        diagnostics = {}
        
        safe_checks = [
            ('disk_usage', 'df -h'),
            ('memory', 'free -h'),
            ('docker_containers', 'docker ps'),
            ('uptime', 'uptime'),
            ('system_load', 'top -bn1 | head -n 5')
        ]
        
        print("\n🔍 Ejecutando diagnóstico del servidor...\n")
        
        for name, cmd in safe_checks:
            result = self.execute_remote(cmd, require_confirmation=False, stream_output=False)
            diagnostics[name] = {
                'success': result['success'],
                'output': result['output'] if result['success'] else result.get('error', 'Failed')
            }
        
        return diagnostics
    
    def execute_command(self, command: str, dangerous_ok: bool = True) -> Dict:
        """Simplified execution - auto-detects safe/dangerous"""
        result = self.execute_remote(command, require_confirmation=dangerous_ok, stream_output=True)
        if result['success']:
            self.audit_log(command, result)
        return result
    
    # ================================================================
    # DOCKER MANAGEMENT
    # ================================================================
    
    def docker_list(self) -> List[Dict]:
        """List all Docker containers with status"""
        result = self.execute_remote(
            'docker ps -a --format "{{.ID}}|{{.Names}}|{{.Status}}|{{.Image}}|{{.Ports}}"',
            require_confirmation=False, stream_output=False
        )
        containers = []
        if result['success']:
            for line in result['output'].split('\n'):
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 4:
                        containers.append({
                            'id': parts[0][:12],
                            'name': parts[1],
                            'status': parts[2],
                            'image': parts[3],
                            'ports': parts[4] if len(parts) > 4 else ''
                        })
        return containers
    
    def docker_start(self, name: str) -> Dict:
        """Start a Docker container"""
        return self.execute_remote(f'docker start {name}', require_confirmation=False)
    
    def docker_stop(self, name: str) -> Dict:
        """Stop a Docker container (requires confirmation)"""
        return self.execute_remote(f'docker stop {name}', require_confirmation=True)
    
    def docker_restart(self, name: str) -> Dict:
        """Restart a Docker container (requires confirmation)"""
        return self.execute_remote(f'docker restart {name}', require_confirmation=True)
    
    def docker_logs(self, name: str, lines: int = 100) -> str:
        """Get logs from a Docker container"""
        result = self.execute_remote(
            f'docker logs --tail {lines} {name}',
            require_confirmation=False, stream_output=True
        )
        return result.get('output', '')
    
    def docker_stats(self) -> List[Dict]:
        """Get resource usage of all containers"""
        result = self.execute_remote(
            'docker stats --no-stream --format "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}"',
            require_confirmation=False, stream_output=False
        )
        stats = []
        if result['success']:
            for line in result['output'].split('\n'):
                if line.strip():
                    parts = line.split('|')
                    if len(parts) >= 4:
                        stats.append({
                            'name': parts[0],
                            'cpu': parts[1],
                            'memory': parts[2],
                            'network': parts[3]
                        })
        return stats
    
    def docker_exec(self, container: str, command: str) -> Dict:
        """Execute command inside a container"""
        return self.execute_remote(
            f'docker exec {container} {command}',
            require_confirmation=True
        )
    
    # ================================================================
    # SERVICE MANAGEMENT (systemd)
    # ================================================================
    
    def service_status(self, name: str) -> Dict:
        """Check status of a systemd service"""
        return self.execute_remote(
            f'systemctl status {name} --no-pager -l',
            require_confirmation=False, stream_output=True
        )
    
    def service_restart(self, name: str) -> Dict:
        """Restart a systemd service (requires confirmation)"""
        return self.execute_remote(
            f'systemctl restart {name}',
            require_confirmation=True
        )
    
    def service_stop(self, name: str) -> Dict:
        """Stop a systemd service (requires confirmation)"""
        return self.execute_remote(
            f'systemctl stop {name}',
            require_confirmation=True
        )
    
    def service_start(self, name: str) -> Dict:
        """Start a systemd service"""
        return self.execute_remote(
            f'systemctl start {name}',
            require_confirmation=False
        )
    
    def service_list(self) -> List[Dict]:
        """List running systemd services"""
        result = self.execute_remote(
            'systemctl list-units --type=service --state=running --no-pager --no-legend',
            require_confirmation=False, stream_output=False
        )
        services = []
        if result['success']:
            for line in result['output'].split('\n'):
                if line.strip():
                    parts = line.split()
                    if len(parts) >= 4:
                        services.append({
                            'name': parts[0].replace('.service', ''),
                            'load': parts[1],
                            'active': parts[2],
                            'sub': parts[3]
                        })
        return services
    
    def view_logs(self, service: str, lines: int = 50) -> str:
        """View journalctl logs for a service"""
        result = self.execute_remote(
            f'journalctl -u {service} -n {lines} --no-pager',
            require_confirmation=False, stream_output=True
        )
        return result.get('output', '')
    
    # ================================================================
    # SYSTEM MONITORING
    # ================================================================
    
    def get_resource_usage(self) -> Dict:
        """Get current CPU, RAM, and disk usage"""
        result = {}
        
        # CPU usage
        cpu_result = self.execute_remote(
            "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'",
            require_confirmation=False, stream_output=False
        )
        if cpu_result['success']:
            try:
                result['cpu_percent'] = float(cpu_result['output'].strip().replace(',', '.'))
            except:
                result['cpu_percent'] = 0.0
        
        # Memory usage
        mem_result = self.execute_remote(
            "free | grep Mem | awk '{printf \"%.1f\", $3/$2 * 100.0}'",
            require_confirmation=False, stream_output=False
        )
        if mem_result['success']:
            try:
                result['mem_percent'] = float(mem_result['output'].strip())
            except:
                result['mem_percent'] = 0.0
        
        # Disk usage (root)
        disk_result = self.execute_remote(
            "df / | tail -1 | awk '{print $5}' | tr -d '%'",
            require_confirmation=False, stream_output=False
        )
        if disk_result['success']:
            try:
                result['disk_percent'] = float(disk_result['output'].strip())
            except:
                result['disk_percent'] = 0.0
        
        return result
    
    def network_info(self) -> Dict:
        """Get network information"""
        result = {}
        
        # IP addresses
        ip_result = self.execute_remote(
            "ip -4 addr show | grep -oP '(?<=inet\\s)\\d+(\\.\\d+){3}'",
            require_confirmation=False, stream_output=False
        )
        if ip_result['success']:
            result['ip_addresses'] = ip_result['output'].strip().split('\n')
        
        # Open ports
        ports_result = self.execute_remote(
            "ss -tlnp | tail -n +2 | awk '{print $4}' | grep -oP ':\\K\\d+' | sort -n | uniq",
            require_confirmation=False, stream_output=False
        )
        if ports_result['success']:
            result['open_ports'] = ports_result['output'].strip().split('\n')
        
        # Active connections count
        conn_result = self.execute_remote(
            "ss -s | grep 'TCP:' | awk '{print $2}'",
            require_confirmation=False, stream_output=False
        )
        if conn_result['success']:
            result['tcp_connections'] = conn_result['output'].strip()
        
        return result
    
    def full_diagnostic(self) -> Dict:
        """Complete system diagnostic"""
        from rich.console import Console
        from rich.table import Table
        
        console = Console()
        console.print("\n[cyan]═══════════════ DIAGNÓSTICO COMPLETO ═══════════════[/cyan]\n")
        
        diagnostics = {}
        
        # Basic info
        console.print("[yellow]📊 Información básica...[/yellow]")
        uptime = self.execute_remote('uptime -p', False, False)
        hostname = self.execute_remote('hostname', False, False)
        diagnostics['hostname'] = hostname.get('output', 'N/A').strip()
        diagnostics['uptime'] = uptime.get('output', 'N/A').strip()
        
        # Resources
        console.print("[yellow]💾 Recursos del sistema...[/yellow]")
        resources = self.get_resource_usage()
        diagnostics['resources'] = resources
        
        # Docker containers
        console.print("[yellow]🐳 Contenedores Docker...[/yellow]")
        containers = self.docker_list()
        diagnostics['containers'] = containers
        diagnostics['containers_running'] = sum(1 for c in containers if 'Up' in c.get('status', ''))
        diagnostics['containers_total'] = len(containers)
        
        # Services
        console.print("[yellow]⚙️  Servicios activos...[/yellow]")
        services = self.service_list()
        diagnostics['services_running'] = len(services)
        
        # Network
        console.print("[yellow]🌐 Red...[/yellow]")
        network = self.network_info()
        diagnostics['network'] = network
        
        # Display summary
        console.print("\n[cyan]═══════════════ RESUMEN ═══════════════[/cyan]")
        
        summary = Table(show_header=False, box=None)
        summary.add_column("", style="cyan")
        summary.add_column("")
        
        summary.add_row("🖥️  Servidor", diagnostics['hostname'])
        summary.add_row("⏱️  Uptime", diagnostics['uptime'])
        summary.add_row("💻 CPU", f"{'█' * int(resources.get('cpu_percent', 0)/10)}{'░' * (10-int(resources.get('cpu_percent', 0)/10))} {resources.get('cpu_percent', 0):.1f}%")
        summary.add_row("🧠 RAM", f"{'█' * int(resources.get('mem_percent', 0)/10)}{'░' * (10-int(resources.get('mem_percent', 0)/10))} {resources.get('mem_percent', 0):.1f}%")
        summary.add_row("💽 Disco", f"{'█' * int(resources.get('disk_percent', 0)/10)}{'░' * (10-int(resources.get('disk_percent', 0)/10))} {resources.get('disk_percent', 0):.1f}%")
        summary.add_row("🐳 Docker", f"{diagnostics['containers_running']}/{diagnostics['containers_total']} containers running")
        summary.add_row("⚙️  Servicios", f"{diagnostics['services_running']} running")
        
        console.print(summary)
        console.print("\n[cyan]═══════════════════════════════════════[/cyan]\n")
        
        return diagnostics
    
    # ================================================================
    # BACKUP SYSTEM
    # ================================================================
    
    def backup_docker_compose(self, backup_dir: str = "/mnt/backups") -> Dict:
        """
        Backup all docker-compose files.
        
        Args:
            backup_dir: Directory to store backups
            
        Returns:
            Dict with status and files backed up
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{backup_dir}/docker_compose_{timestamp}"
        
        print(f"\n[Backup] Creando backup de docker-compose en {backup_path}...")
        
        # Create backup directory
        result = self.execute_remote(f"mkdir -p {backup_path}", require_confirmation=False, stream_output=False)
        if not result['success']:
            return {'success': False, 'error': 'Failed to create backup directory'}
        
        # Find and copy docker-compose files
        result = self.execute_remote(
            "find /opt /home -name 'docker-compose*.yml' -o -name 'docker-compose*.yaml' 2>/dev/null | head -20",
            require_confirmation=False, stream_output=False
        )
        
        files_backed_up = []
        if result['success'] and result['output']:
            for file_path in result['output'].split('\n'):
                if file_path.strip():
                    # Copy to backup
                    filename = file_path.replace('/', '_')[1:]  # Remove leading /
                    copy_result = self.execute_remote(
                        f"cp {file_path} {backup_path}/{filename}",
                        require_confirmation=False, stream_output=False
                    )
                    if copy_result['success']:
                        files_backed_up.append(file_path)
        
        return {
            'success': True,
            'backup_path': backup_path,
            'files': files_backed_up,
            'count': len(files_backed_up)
        }
    
    def backup_docker_volumes(self, volumes: List[str] = None, backup_dir: str = "/mnt/backups") -> Dict:
        """
        Backup Docker volumes.
        
        Args:
            volumes: List of volume names to backup (None = all)
            backup_dir: Directory to store backups
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        print("\n[Backup] Creando backup de volúmenes Docker...")
        
        # Get list of volumes
        if not volumes:
            result = self.execute_remote(
                "docker volume ls -q",
                require_confirmation=False, stream_output=False
            )
            if result['success']:
                volumes = [v.strip() for v in result['output'].split('\n') if v.strip()]
            else:
                return {'success': False, 'error': 'Failed to list volumes'}
        
        backed_up = []
        failed = []
        
        for volume in volumes[:10]:  # Limit to 10 volumes
            backup_file = f"{backup_dir}/volume_{volume}_{timestamp}.tar.gz"
            
            # Backup volume using temporary container
            result = self.execute_remote(
                f"docker run --rm -v {volume}:/data -v {backup_dir}:/backup alpine "
                f"tar czf /backup/volume_{volume}_{timestamp}.tar.gz -C /data .",
                require_confirmation=True, stream_output=False
            )
            
            if result.get('cancelled'):
                return {'success': False, 'error': 'Backup cancelled by user'}
            
            if result['success']:
                backed_up.append({'volume': volume, 'file': backup_file})
            else:
                failed.append(volume)
        
        return {
            'success': len(failed) == 0,
            'backed_up': backed_up,
            'failed': failed
        }
    
    def backup_configs(self, paths: List[str] = None, backup_dir: str = "/mnt/backups") -> Dict:
        """
        Backup configuration files.
        
        Args:
            paths: Paths to backup (default: common config locations)
            backup_dir: Destination for backups
        """
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = f"{backup_dir}/configs_{timestamp}.tar.gz"
        
        default_paths = [
            "/etc/nginx",
            "/etc/pihole",
            "/opt/*/config",
            "/root/.config"
        ]
        
        paths = paths or default_paths
        paths_str = " ".join(paths)
        
        print("\n[Backup] Creando backup de configuraciones...")
        
        result = self.execute_remote(
            f"tar czf {backup_file} {paths_str} 2>/dev/null || true",
            require_confirmation=True, stream_output=False
        )
        
        if result.get('cancelled'):
            return {'success': False, 'error': 'Backup cancelled'}
        
        # Check file was created
        check = self.execute_remote(f"ls -lh {backup_file}", require_confirmation=False, stream_output=False)
        
        if check['success']:
            size = check['output'].split()[4] if len(check['output'].split()) > 4 else 'unknown'
            return {
                'success': True,
                'file': backup_file,
                'size': size,
                'paths': paths
            }
        
        return {'success': False, 'error': 'Backup file not created'}
    
    def close(self):
        """Ensure cleanup"""
        self.disconnect()

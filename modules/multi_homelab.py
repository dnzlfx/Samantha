"""
Samantha multi-server HomeLab manager.
Manages multiple SSH connections to homelab servers.
"""

import logging
from typing import Dict, Optional
from modules.homelab import HomeLab
from rich.console import Console
from rich.table import Table
from rich.prompt import Prompt

logger = logging.getLogger(__name__)


class MultiHomeLab:
    """
    Manages multiple HomeLab server connections.
    Allows executing commands across servers or on specific servers.
    """
    
    def __init__(self):
        self.servers: Dict[str, HomeLab] = {}
        self.console = Console()
        self.active_server = None
        
    def add_server(self, profile: str) -> bool:
        """
        Add a server connection by profile name.
        
        Args:
            profile: Server profile name ('main', 'switch', etc.)
            
        Returns:
            True if connected successfully
        """
        try:
            if profile in HomeLab.SERVER_PROFILES:
                homelab = HomeLab(profile=profile)
                if homelab.connect():
                    self.servers[profile] = homelab
                    if not self.active_server:
                        self.active_server = profile
                    self.console.print(f"[green]✅ {homelab.description} conectado ({homelab.user}@{homelab.host})[/green]")
                    return True
                else:
                    self.console.print(f"[red]❌ No se pudo conectar a {profile}[/red]")
                    return False
            else:
                self.console.print(f"[red]❌ Perfil '{profile}' no existe[/red]")
                return False
        except Exception as e:
            logger.error(f"Error adding server {profile}: {e}")
            return False
    
    def connect_all(self) -> Dict[str, bool]:
        """
        Connect to all available server profiles.
        
        Returns:
            Dict with connection status for each profile
        """
        results = {}
        for profile in HomeLab.SERVER_PROFILES.keys():
            results[profile] = self.add_server(profile)
        return results
    
    def list_servers(self) -> None:
        """Display all connected servers"""
        if not self.servers:
            self.console.print("[yellow]No hay servidores conectados[/yellow]")
            return
        
        table = Table(title="🖥️  Servidores HomeLab")
        table.add_column("Perfil", style="cyan")
        table.add_column("Descripción", style="white")
        table.add_column("Conexión", style="green")
        table.add_column("Activo", style="yellow")
        
        for profile, homelab in self.servers.items():
            is_active = "✓" if profile == self.active_server else ""
            table.add_row(
                profile,
                homelab.description,
                f"{homelab.user}@{homelab.host}",
                is_active
            )
        
        self.console.print(table)
    
    def switch_server(self, profile: str) -> bool:
        """
        Switch active server.
        
        Args:
            profile: Server profile to switch to
            
        Returns:
            True if switched successfully
        """
        if profile in self.servers:
            self.active_server = profile
            homelab = self.servers[profile]
            self.console.print(f"[green]✓ Servidor activo: {homelab.description}[/green]")
            return True
        else:
            self.console.print(f"[red]❌ Servidor '{profile}' no está conectado[/red]")
            return False
    
    def get_active(self) -> Optional[HomeLab]:
        """Get the currently active HomeLab connection"""
        if self.active_server and self.active_server in self.servers:
            return self.servers[self.active_server]
        return None
    
    def get_server(self, profile: str) -> Optional[HomeLab]:
        """Get a specific server by profile name"""
        return self.servers.get(profile)
    
    def execute_on_active(self, command: str, **kwargs) -> Dict:
        """Execute command on active server"""
        if not self.active_server:
            return {'success': False, 'error': 'No active server'}
        
        homelab = self.get_active()
        if homelab:
            return homelab.execute_remote(command, **kwargs)
        return {'success': False, 'error': 'Server not found'}
    
    def execute_on_all(self, command: str, **kwargs) -> Dict[str, Dict]:
        """
        Execute command on all connected servers.
        
        Args:
            command: Command to execute
            **kwargs: Additional arguments for execute_remote
            
        Returns:
            Dict mapping profile names to execution results
        """
        results = {}
        for profile, homelab in self.servers.items():
            self.console.print(f"\n[bold {homelab.color}]╔══ {homelab.description} ({homelab.user}@{homelab.host}) ══╗[/bold {homelab.color}]")
            results[profile] = homelab.execute_remote(command, **kwargs)
            self.console.print(f"[bold {homelab.color}]╚{'═' * 50}╝[/bold {homelab.color}]\n")
        return results
    
    def full_diagnostic_all(self) -> Dict[str, Dict]:
        """Run full diagnostic on all servers"""
        results = {}
        for profile, homelab in self.servers.items():
            self.console.print(f"\n[bold {homelab.color}]═══ {homelab.description.upper()} ═══[/bold {homelab.color}]\n")
            results[profile] = homelab.full_diagnostic()
        return results
    
    def interactive_menu(self) -> None:
        """Interactive menu for managing multiple servers"""
        while True:
            self.console.print("\n[bold cyan]═══ HOMELAB MULTI-SERVIDOR ═══[/bold cyan]\n")
            
            # Show current servers
            self.list_servers()
            
            self.console.print("\n[bold yellow]Opciones:[/bold yellow]")
            options = [
                "1. Ejecutar comando en servidor activo",
                "2. Ejecutar comando en todos los servidores",
                "3. Cambiar servidor activo",
                "4. Diagnóstico del servidor activo",
                "5. Diagnóstico de todos los servidores",
                "6. Ver contenedores Docker (activo)",
                "7. Ver servicios (activo)",
                "8. Volver"
            ]
            
            for option in options:
                self.console.print(f"  {option}")
            
            choice = Prompt.ask("\n[cyan]Selecciona una opción[/cyan]", default="8")
            
            if choice == "1":
                cmd = Prompt.ask("[cyan]Comando a ejecutar[/cyan]")
                self.execute_on_active(cmd)
            
            elif choice == "2":
                cmd = Prompt.ask("[cyan]Comando a ejecutar en todos[/cyan]")
                self.execute_on_all(cmd)
            
            elif choice == "3":
                profile = Prompt.ask("[cyan]Perfil del servidor[/cyan]", choices=list(self.servers.keys()))
                self.switch_server(profile)
            
            elif choice == "4":
                homelab = self.get_active()
                if homelab:
                    homelab.full_diagnostic()
            
            elif choice == "5":
                self.full_diagnostic_all()
            
            elif choice == "6":
                homelab = self.get_active()
                if homelab:
                    containers = homelab.docker_list()
                    table = Table(title="🐳 Docker Containers")
                    table.add_column("ID", style="cyan")
                    table.add_column("Name", style="green")
                    table.add_column("Status", style="yellow")
                    table.add_column("Image", style="blue")
                    
                    for c in containers:
                        table.add_row(c['id'], c['name'], c['status'], c['image'])
                    
                    self.console.print(table)
            
            elif choice == "7":
                homelab = self.get_active()
                if homelab:
                    services = homelab.service_list()
                    table = Table(title="⚙️  Services")
                    table.add_column("Service", style="cyan")
                    table.add_column("State", style="green")
                    
                    for s in services:
                        table.add_row(s['name'], s['active'])
                    
                    self.console.print(table)
            
            elif choice == "8":
                break
    
    def close_all(self):
        """Close all server connections"""
        for homelab in self.servers.values():
            homelab.close()
        self.servers.clear()
        self.active_server = None

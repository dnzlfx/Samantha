"""
Samantha dashboard.
Rich-based interactive dashboard with system telemetry.
"""

import logging
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.layout import Layout
from rich.text import Text
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.live import Live
from typing import Dict, Optional
import psutil

from core.version import __version__

logger = logging.getLogger(__name__)


class Dashboard:
    """
    Rich-based dashboard for Samantha with live telemetry and conversation display.
    """
    
    def __init__(self):
        self.console = Console()
        self.current_model: Optional[str] = None
        self.current_intent: Optional[str] = None
    
    def show_banner(self):
        """Displays Samantha startup banner"""
        banner = """
╔══════════════════════════════════════════════════════════╗
║           [bold cyan]Samantha v{version} - AI Assistant System[/bold cyan]                 ║
║           [dim]Local multimodal assistant[/dim]                    ║
╚══════════════════════════════════════════════════════════╝
        """.format(version=__version__)
        self.console.print(banner)
    
    def show_system_check(self, checks: Dict[str, bool]):
        """
        Displays system initialization checks.
        
        Args:
            checks: Dict of check_name: passed
        """
        self.console.print("\n[bold]Sistema de Inicialización[/bold]\n")
        
        table = Table(show_header=True)
        table.add_column("Componente", style="cyan")
        table.add_column("Estado", style="bold")
        
        for component, passed in checks.items():
            status = "[green]✅ OK[/green]" if passed else "[red]❌ FALLO[/red]"
            table.add_row(component, status)
        
        self.console.print(table)
        self.console.print()
    
    def get_telemetry(self) -> Dict:
        """
        Gets current system telemetry.
        
        Returns:
            Dict with RAM, CPU, disk stats
        """
        try:
            ram = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=0.1)
            disk = psutil.disk_usage('/')
            
            telemetry = {
                'ram_percent': ram.percent,
                'ram_used_gb': ram.used / (1024**3),
                'ram_total_gb': ram.total / (1024**3),
                'cpu_percent': cpu,
                'disk_percent': disk.percent,
                'disk_used_gb': disk.used / (1024**3),
                'disk_total_gb': disk.total / (1024**3)
            }
            
            # Try to get GPU info if available
            try:
                import subprocess
                result = subprocess.run(
                    ['nvidia-smi', '--query-gpu=memory.used,memory.total', '--format=csv,noheader,nounits'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    used, total = result.stdout.strip().split(',')
                    telemetry['vram_used_mb'] = int(used.strip())
                    telemetry['vram_total_mb'] = int(total.strip())
                    telemetry['vram_percent'] = (int(used.strip()) / int(total.strip())) * 100
            except:
                pass  # GPU not available
            
            return telemetry
            
        except Exception as e:
            logger.error(f"[Sam] Telemetry error: {e}")
            return {}
    
    def create_telemetry_panel(self) -> Panel:
        """
        Creates a telemetry panel with current system stats.
        
        Returns:
            Rich Panel with telemetry
        """
        telemetry = self.get_telemetry()
        
        if not telemetry:
            return Panel("[red]Telemetry unavailable[/red]", title="System", border_style="red")
        
        # Create telemetry display
        content = ""
        
        # RAM
        ram_color = "green" if telemetry['ram_percent'] < 80 else "yellow" if telemetry['ram_percent'] < 90 else "red"
        content += f"[cyan]RAM:[/cyan] [{ram_color}]{telemetry['ram_percent']:.1f}%[/{ram_color}] "
        content += f"({telemetry['ram_used_gb']:.1f}GB / {telemetry['ram_total_gb']:.1f}GB)\n"
        
        # CPU
        cpu_color = "green" if telemetry['cpu_percent'] < 70 else "yellow" if telemetry['cpu_percent'] < 90 else "red"
        content += f"[cyan]CPU:[/cyan] [{cpu_color}]{telemetry['cpu_percent']:.1f}%[/{cpu_color}]\n"
        
        # Disk
        disk_color = "green" if telemetry['disk_percent'] < 80 else "yellow" if telemetry['disk_percent'] < 90 else "red"
        content += f"[cyan]Disk:[/cyan] [{disk_color}]{telemetry['disk_percent']:.1f}%[/{disk_color}]"
        
        # VRAM if available
        if 'vram_percent' in telemetry:
            vram_color = "green" if telemetry['vram_percent'] < 80 else "yellow" if telemetry['vram_percent'] < 90 else "red"
            content += f"\n[cyan]VRAM:[/cyan] [{vram_color}]{telemetry['vram_percent']:.1f}%[/{vram_color}] "
            content += f"({telemetry['vram_used_mb']}MB / {telemetry['vram_total_mb']}MB)"
        
        # Model info
        if self.current_model:
            content += f"\n\n[cyan]Model:[/cyan] {self.current_model}"
        if self.current_intent:
            content += f"\n[cyan]Intent:[/cyan] {self.current_intent}"
        
        return Panel(content, title="[bold]System Status[/bold]", border_style="cyan")
    
    def print_user_input(self, user_input: str):
        """
        Displays user input with formatting.
        
        Args:
            user_input: User's input text
        """
        self.console.print(f"\n[bold green]You:[/bold green] {user_input}")
    
    def print_assistant_response(self, response: str, model: Optional[str] = None):
        """
        Displays assistant response with formatting.
        
        Args:
            response: Assistant's response
            model: Model used (if provided)
        """
        prefix = "[bold cyan]Sam:[/bold cyan]"
        if model:
            prefix += f" [dim]({model})[/dim]"
        
        # Check if response contains code blocks
        if "```" in response:
            # Render markdown with code highlighting
            md = Markdown(response)
            self.console.print(f"\n{prefix}")
            self.console.print(md)
        else:
            self.console.print(f"\n{prefix} {response}")
    
    def print_info(self, message: str):
        """Prints info message"""
        self.console.print(f"[blue]ℹ️  {message}[/blue]")
    
    def print_success(self, message: str):
        """Prints success message"""
        self.console.print(f"[green]✅ {message}[/green]")
    
    def print_warning(self, message: str):
        """Prints warning message"""
        self.console.print(f"[yellow]⚠️  {message}[/yellow]")
    
    def print_error(self, message: str):
        """Prints error message"""
        self.console.print(f"[red]❌ {message}[/red]")
    
    def show_progress(self, description: str):
        """
        Shows a progress spinner for long operations.
        
        Args:
            description: Operation description
        """
        from rich.spinner import Spinner
        spinner = Spinner("dots", text=description)
        return spinner
    
    def update_model_info(self, model: str, intent: str):
        """
        Updates current model and intent for telemetry display.
        
        Args:
            model: Current model name
            intent: Current intent
        """
        self.current_model = model
        self.current_intent = intent

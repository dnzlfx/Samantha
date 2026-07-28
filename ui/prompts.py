"""
Samantha prompt handler.
Interactive prompt system with command history and special commands.
"""

import logging
from typing import List
from pathlib import Path
from rich.prompt import Prompt
from rich.console import Console

logger = logging.getLogger(__name__)


class PromptHandler:
    """
    Handles user input with command history and special command detection.
    """
    
    HISTORY_FILE = str(Path.home() / ".sam_history")
    SPECIAL_COMMANDS = {
        '/help': 'Show available commands',
        '/model': 'Switch model manually (/model <name>)',
        '/inject': 'Inject file into context (/inject <filepath>)',
        '/search': 'Force web search (/search <query>)',
        '/clear': 'Clear conversation history',
        '/telemetry': 'Show system telemetry',
        '/diagnostic': 'Run homelab diagnostic',
        '/quit': 'Exit Sam',
        '/exit': 'Exit Sam',
    }
    
    def __init__(self):
        self.console = Console()
        self.history: List[str] = []
        self._load_history()
    
    def _load_history(self):
        """Loads command history from file"""
        try:
            if Path(self.HISTORY_FILE).exists():
                with open(self.HISTORY_FILE, 'r') as f:
                    self.history = [line.strip() for line in f.readlines()[-100:]]  # Last 100
                logger.info(f"[Sam] Loaded {len(self.history)} history items")
        except Exception as e:
            logger.warning(f"[Sam] Could not load history: {e}")
    
    def _save_history(self):
        """Saves command history to file"""
        try:
            with open(self.HISTORY_FILE, 'w') as f:
                for item in self.history[-100:]:  # Save last 100
                    f.write(f"{item}\n")
        except Exception as e:
            logger.warning(f"[Sam] Could not save history: {e}")
    
    def get_input(self) -> str:
        """
        Gets user input with rich prompt.
        
        Returns:
            User input string
        """
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]")
            
            if user_input:
                self.history.append(user_input)
                self._save_history()
            
            return user_input.strip()
            
        except (KeyboardInterrupt, EOFError):
            return "/quit"
    
    def is_special_command(self, user_input: str) -> bool:
        """
        Checks if input is a special command.
        
        Args:
            user_input: User input
            
        Returns:
            True if special command
        """
        return user_input.startswith('/')
    
    def parse_command(self, user_input: str) -> tuple:
        """
        Parses a special command.
        
        Args:
            user_input: User input
            
        Returns:
            Tuple of (command, args)
        """
        parts = user_input.split(maxsplit=1)
        command = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""
        
        return command, args
    
    def show_help(self):
        """Displays available commands"""
        from rich.table import Table
        
        table = Table(title="Sam Commands", show_header=True)
        table.add_column("Command", style="cyan")
        table.add_column("Description", style="white")
        
        for cmd, desc in self.SPECIAL_COMMANDS.items():
            table.add_row(cmd, desc)
        
        self.console.print("\n")
        self.console.print(table)
        self.console.print("\n")

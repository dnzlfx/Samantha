#!/usr/bin/env python3
"""
Task Tracker - Progress visualization for agentic workflows
"""

from typing import List
from rich.table import Table
from rich.console import Console
from modules.reasoning import Step


class TaskTracker:
    """Tracks and displays progress of multi-step tasks"""
    
    def __init__(self):
        self.current_task = None
        self.steps: List[Step] = []
        self.console = Console()
    
    def start_task(self, task_name: str, steps: List[Step]):
        """Initialize task tracking"""
        self.current_task = task_name
        self.steps = steps
    
    def update_step(self, step_id: int, status: str, result: str = None):
        """Update step status"""
        for step in self.steps:
            if step.id == step_id:
                step.status = status
                if result:
                    step.result = result
                break
    
    def show_progress(self):
        """Display current progress"""
        if not self.current_task or not self.steps:
            return
        
        table = Table(title=f"Task: {self.current_task}")
        table.add_column("Step", style="cyan")
        table.add_column("Description", style="white")
        table.add_column("Status", style="yellow")
        
        for step in self.steps:
            status_icon = {
                'pending': '⏸',
                'running': '⏳',
                'done': '✓',
                'failed': '✗'
            }.get(step.status, '?')
            
            status_color = {
                'pending': 'dim',
                'running': 'yellow',
                'done': 'green',
                'failed': 'red'
            }.get(step.status, 'white')
            
            table.add_row(
                f"{step.id}",
                step.description,
                f"[{status_color}]{status_icon} {step.status.upper()}[/{status_color}]"
            )
        
        self.console.print(table)
    
    def show_summary(self):
        """Show final summary"""
        done_count = sum(1 for s in self.steps if s.status == 'done')
        failed_count = sum(1 for s in self.steps if s.status == 'failed')
        
        if failed_count > 0:
            self.console.print(f"\n[red]✗ Task partially complete: {done_count}/{len(self.steps)} steps done, {failed_count} failed[/red]")
        else:
            self.console.print(f"\n[green]✓ Task complete: {done_count}/{len(self.steps)} steps done[/green]")

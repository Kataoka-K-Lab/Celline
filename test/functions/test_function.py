"""
Test Custom Celline Function

This is a sample custom function for testing the custom function system.
"""

import argparse
from typing import TYPE_CHECKING

from celline.functions._base import CellineFunction
from rich.console import Console

if TYPE_CHECKING:
    from celline import Project

console = Console()


class TestFunction(CellineFunction):
    """Test custom function
    
    This is a sample custom function to test the custom function discovery system.
    
    Example usage:
    - celline run custom_test_function
    """
    
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.message = kwargs.get('message', 'Hello from custom function!')
    
    def register(self) -> str:
        """Register this function with a specific name."""
        return "custom_test_function"
    
    def call(self, project: "Project"):
        """Test function implementation."""
        console.print(f"[cyan]Running test custom function[/cyan]")
        console.print(f"Message: {self.message}")
        console.print(f"[green]Test function completed successfully![/green]")
        return project
    
    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add command-line arguments."""
        parser.add_argument("--message", type=str, default="Hello from custom function!", 
                          help="Message to display")
    
    def cli(self, project: "Project", args: argparse.Namespace | None = None) -> "Project":
        """CLI entry point."""
        if args and hasattr(args, 'message'):
            self.message = args.message
        
        console.print(f"[dim]Starting test custom function[/dim]")
        return self.call(project)
    
    def get_description(self) -> str:
        """Get function description."""
        return "Test custom function for validating the custom function system"
    
    def get_usage_examples(self) -> list[str]:
        """Get usage examples."""
        return [
            "celline run custom_test_function",
            "celline run custom_test_function --message 'Custom message!'",
        ]
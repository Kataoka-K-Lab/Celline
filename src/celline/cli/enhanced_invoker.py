"""
Enhanced CLI invoker that uses the new cli method from CellineFunction.
"""

import argparse
from typing import Type, Optional
from rich.console import Console

from celline.functions._base import CellineFunction
from celline.interfaces import Project

console = Console()


class EnhancedFunctionInvoker:
    """Enhanced invoker that uses the CLI interface of CellineFunction."""
    
    def __init__(self, func_class: Type[CellineFunction]):
        self.func_class = func_class
    
    def create_function_parser(self) -> argparse.ArgumentParser:
        """Create an argument parser for this specific function."""
        # Get function description using class methods without full instantiation
        try:
            # Try to create a minimal instance to get metadata
            temp_instance = self.func_class.__new__(self.func_class)
            # Initialize the ABC part to avoid abstract method errors
            temp_instance.__class__ = self.func_class
            
            description = temp_instance.get_description()
            command_name = temp_instance.register()
        except:
            # Fallback to defaults if instantiation fails
            description = self.func_class.__doc__ or f"{self.func_class.__name__} function"
            command_name = self.func_class.__name__.lower()
        
        parser = argparse.ArgumentParser(
            prog=f"celline run {command_name}",
            description=description,
            formatter_class=argparse.RawDescriptionHelpFormatter
        )
        
        # Let the function add its own arguments
        try:
            temp_instance.add_cli_args(parser)
        except:
            # If add_cli_args fails, continue without custom arguments
            pass
        
        # Add usage examples to help text
        try:
            examples = temp_instance.get_usage_examples()
            if examples:
                epilog = "Examples:\n" + "\n".join(f"  {example}" for example in examples)
                parser.epilog = epilog
        except:
            # If getting examples fails, continue without them
            pass
        
        return parser
    
    def get_help_text(self) -> str:
        """Get help text for this function."""
        parser = self.create_function_parser()
        return parser.format_help()
    
    def invoke(self, project: Project, cli_args: list[str] = None) -> Project:
        """
        Invoke the function using CLI interface.
        
        Args:
            project: The Project instance
            cli_args: CLI arguments to parse (if None, no arguments)
            
        Returns:
            Project: The project instance
        """
        try:
            # Create parser and parse arguments
            parser = self.create_function_parser()
            
            if cli_args:
                args = parser.parse_args(cli_args)
            else:
                args = argparse.Namespace()
            
            # Create function instance using CLI factory method
            # This allows functions to handle their own instantiation based on CLI args
            try:
                # Try to create a minimal instance first
                instance = self.func_class.__new__(self.func_class)
                instance.__class__ = self.func_class
                
                # Call the CLI method - it should handle its own instantiation
                console.print(f"[cyan]Executing {instance.register()}...[/cyan]")
                result = instance.cli(project, args)
                console.print(f"[green]✓ {instance.register()} completed successfully[/green]")
                
                return result
            except Exception as e:
                # If that fails, try to call the cli method statically
                temp_instance = self.func_class.__new__(self.func_class)
                temp_instance.__class__ = self.func_class
                result = temp_instance.cli(project, args)
                return result
            
        except SystemExit:
            # argparse calls sys.exit on error - catch and re-raise as regular exception
            raise ValueError("Invalid arguments provided")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise


def invoke_function_enhanced(func_class: Type[CellineFunction], project: Project, cli_args: list[str] = None) -> Project:
    """Convenience function to invoke a CellineFunction using enhanced CLI interface."""
    invoker = EnhancedFunctionInvoker(func_class)
    return invoker.invoke(project, cli_args)
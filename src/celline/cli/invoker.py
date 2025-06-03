"""
Function invoker for handling CellineFunction instantiation and execution.
"""

import inspect
import json
from typing import Any, Dict, List, Optional, Type
from rich.console import Console
from rich.prompt import Prompt, Confirm

from celline.functions._base import CellineFunction
from celline.interfaces import Project

console = Console()


class FunctionInvoker:
    """Handles instantiation and execution of CellineFunction classes."""
    
    def __init__(self, func_class: Type[CellineFunction]):
        self.func_class = func_class
        self.signature = inspect.signature(func_class.__init__)
    
    def get_constructor_params(self) -> Dict[str, inspect.Parameter]:
        """Get constructor parameters excluding 'self'."""
        params = {}
        for name, param in self.signature.parameters.items():
            if name != 'self':
                params[name] = param
        return params
    
    def can_instantiate_without_args(self) -> bool:
        """Check if the function can be instantiated without arguments."""
        params = self.get_constructor_params()
        for param in params.values():
            if param.default == inspect.Parameter.empty:
                return False
        return True
    
    def prompt_for_args(self) -> Dict[str, Any]:
        """Interactively prompt user for constructor arguments."""
        params = self.get_constructor_params()
        args = {}
        
        console.print(f"[yellow]Function '{self.func_class.__name__}' requires arguments:[/yellow]")
        console.print()
        
        for name, param in params.items():
            param_type = param.annotation
            default_value = param.default if param.default != inspect.Parameter.empty else None
            
            # Format the prompt
            prompt_text = f"{name}"
            if param_type != inspect.Parameter.empty:
                prompt_text += f" ({param_type.__name__ if hasattr(param_type, '__name__') else str(param_type)})"
            if default_value is not None:
                prompt_text += f" [default: {default_value}]"
            
            # Get user input
            if param_type == bool or str(param_type) == "<class 'bool'>":
                value = Confirm.ask(prompt_text, default=default_value if default_value is not None else False)
            else:
                value = Prompt.ask(prompt_text, default=str(default_value) if default_value is not None else None)
                
                # Try to convert to appropriate type
                if value and param_type != inspect.Parameter.empty:
                    try:
                        if param_type == int:
                            value = int(value)
                        elif param_type == float:
                            value = float(value)
                        elif param_type == bool:
                            value = value.lower() in ('true', 'yes', '1', 'on')
                        elif hasattr(param_type, '__origin__'):  # Handle generic types like List[str]
                            if str(param_type).startswith('typing.List') or str(param_type).startswith('list'):
                                # Simple list parsing - split by comma
                                value = [item.strip() for item in value.split(',') if item.strip()]
                    except (ValueError, TypeError) as e:
                        console.print(f"[yellow]Warning: Could not convert '{value}' to {param_type}, using as string[/yellow]")
            
            args[name] = value
        
        return args
    
    def create_instance(self, args: Optional[Dict[str, Any]] = None) -> CellineFunction:
        """Create an instance of the function with given arguments."""
        if args is None:
            args = {}
        
        try:
            return self.func_class(**args)
        except TypeError as e:
            raise ValueError(f"Could not instantiate {self.func_class.__name__}: {e}")
    
    def invoke(self, project: Project, interactive: bool = True) -> Any:
        """Invoke the function, prompting for args if needed."""
        try:
            # Try to create instance without arguments first
            if self.can_instantiate_without_args():
                instance = self.create_instance()
            elif interactive:
                # Prompt for arguments
                args = self.prompt_for_args()
                instance = self.create_instance(args)
            else:
                raise ValueError(f"Function {self.func_class.__name__} requires arguments but interactive mode is disabled")
            
            # Call the function
            console.print(f"[cyan]Executing {self.func_class.__name__}...[/cyan]")
            result = instance.call(project)
            console.print(f"[green]✓ {self.func_class.__name__} completed successfully[/green]")
            return result
            
        except KeyboardInterrupt:
            console.print("[yellow]Operation cancelled by user[/yellow]")
            raise
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise


def invoke_function(func_class: Type[CellineFunction], project: Project, interactive: bool = True) -> Any:
    """Convenience function to invoke a CellineFunction."""
    invoker = FunctionInvoker(func_class)
    return invoker.invoke(project, interactive)
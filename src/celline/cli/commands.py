"""
CLI commands for celline.
"""

import argparse
import sys
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.text import Text

from celline.cli.registry import get_registry
from celline.cli.enhanced_invoker import EnhancedFunctionInvoker
from celline.interfaces import Project


console = Console()


def cmd_list(args: argparse.Namespace) -> None:
    """List all available CellineFunction implementations."""
    registry = get_registry()
    functions = registry.list_functions()
    
    if not functions:
        console.print("[yellow]No CellineFunction implementations found.[/yellow]")
        return
    
    # Create a table
    table = Table(title="Available Celline Functions")
    table.add_column("Command", style="cyan", no_wrap=True)
    table.add_column("Class", style="magenta")
    table.add_column("Description", style="green")
    table.add_column("Module", style="dim")
    
    # Sort functions by name
    for func in sorted(functions, key=lambda f: f.name):
        table.add_row(
            func.name,
            func.class_name,
            func.description,
            func.module_path.replace('celline.functions.', '')
        )
    
    console.print(table)
    console.print(f"\n[dim]Total: {len(functions)} functions[/dim]")


def cmd_help(args: argparse.Namespace) -> None:
    """Show help information."""
    if args.function_name:
        # Show help for specific function
        registry = get_registry()
        func_info = registry.get_function(args.function_name)
        
        if not func_info:
            console.print(f"[red]Function '{args.function_name}' not found.[/red]")
            console.print("Use 'celline list' to see available functions.")
            return
        
        # Use enhanced invoker to get detailed help
        invoker = EnhancedFunctionInvoker(func_info.class_ref)
        help_text = invoker.get_help_text()
        console.print(help_text)
        
    else:
        # Show general help
        console.print("[bold]Celline - Single Cell Analysis Pipeline[/bold]")
        console.print()
        console.print("Usage:")
        console.print("  celline [command] [options]")
        console.print()
        console.print("Available commands:")
        console.print("  init [name]         Initialize a new celline project")
        console.print("  list                List all available functions")
        console.print("  help [function]     Show help for a specific function")
        console.print("  run <function>      Run a specific function")
        console.print("  run interactive     Launch interactive web interface")
        console.print("  interactive         Launch interactive web interface")
        console.print("  info                Show system information")
        console.print("  api                 Start API server only (for testing)")
        console.print()
        console.print("Use 'celline init' to create a new project.")
        console.print("Use 'celline list' to see all available functions.")
        console.print("Use 'celline help <function>' to see detailed help for a specific function.")


def cmd_run(args: argparse.Namespace) -> None:
    """Run a specific CellineFunction."""
    if not args.function_name:
        console.print("[red]Error: Function name is required.[/red]")
        console.print("Usage: celline run <function_name>")
        return
    
    registry = get_registry()
    func_info = registry.get_function(args.function_name)
    
    if not func_info:
        console.print(f"[red]Function '{args.function_name}' not found.[/red]")
        console.print("Use 'celline list' to see available functions.")
        return
    
    try:
        # Create a project instance
        project_dir = getattr(args, 'project_dir', '.')
        project_name = getattr(args, 'project_name', 'default')
        
        console.print(f"[dim]Project: {project_name} (dir: {project_dir})[/dim]")
        project = Project(project_dir, project_name)
        
        # Use enhanced invoker to handle function execution
        invoker = EnhancedFunctionInvoker(func_info.class_ref)
        
        # Extract function-specific arguments (everything after the function name)
        function_args = getattr(args, 'function_args', [])
        
        invoker.invoke(project, function_args)
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error running function '{func_info.name}': {e}[/red]")
        import traceback
        if console.is_terminal:
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


def cmd_init(args: argparse.Namespace) -> None:
    """Initialize a new celline project."""
    import os
    import shutil
    from pathlib import Path
    
    project_name = getattr(args, 'project_name', None)
    if not project_name:
        project_name = input("Enter project name: ").strip()
        if not project_name:
            console.print("[red]Project name is required.[/red]")
            return
    
    project_dir = Path(project_name)
    
    if project_dir.exists():
        console.print(f"[red]Directory '{project_name}' already exists.[/red]")
        return
    
    try:
        # Create project directory
        project_dir.mkdir(parents=True)
        console.print(f"[green]Created project directory: {project_name}[/green]")
        
        # Create basic project structure
        (project_dir / "data").mkdir()
        (project_dir / "results").mkdir()
        (project_dir / "scripts").mkdir()
        
        # Create config files
        setting_content = """[project]
name = "{}"
version = "1.0.0"
description = "Single cell analysis project"

[analysis]
# Analysis parameters go here
""".format(project_name)
        
        (project_dir / "setting.toml").write_text(setting_content)
        
        # Create sample config
        samples_content = """# Sample configuration
# Add your samples here following this format:
# [samples.sample1]
# name = "Sample 1"
# path = "data/sample1"
"""
        (project_dir / "samples.toml").write_text(samples_content)
        
        # Create README
        readme_content = f"""# {project_name}

This is a celline single cell analysis project.

## Directory Structure

- `data/`: Raw and processed data files
- `results/`: Analysis results and outputs
- `scripts/`: Custom analysis scripts
- `setting.toml`: Project configuration
- `samples.toml`: Sample configuration

## Usage

To run celline functions in this project:

```bash
cd {project_name}
celline list  # List available functions
celline run <function_name>  # Run a specific function
```
"""
        (project_dir / "README.md").write_text(readme_content)
        
        console.print(f"[green]Project '{project_name}' initialized successfully![/green]")
        console.print()
        console.print("Next steps:")
        console.print(f"  1. cd {project_name}")
        console.print("  2. Edit samples.toml to configure your samples")
        console.print("  3. Run 'celline list' to see available functions")
        
    except Exception as e:
        console.print(f"[red]Error creating project: {e}[/red]")
        # Clean up on error
        if project_dir.exists():
            shutil.rmtree(project_dir)


def cmd_info(args: argparse.Namespace) -> None:
    """Show information about the celline system."""
    console.print("[bold]Celline System Information[/bold]")
    console.print()
    
    registry = get_registry()
    functions = registry.list_functions()
    
    console.print(f"Available functions: {len(functions)}")
    console.print()
    
    # Group by module
    modules = {}
    for func in functions:
        module = func.module_path.replace('celline.functions.', '')
        if module not in modules:
            modules[module] = []
        modules[module].append(func)
    
    console.print("[bold]Functions by module:[/bold]")
    for module, funcs in sorted(modules.items()):
        console.print(f"  {module}: {', '.join(f.name for f in funcs)}")


def cmd_interactive(args: argparse.Namespace) -> None:
    """Launch Celline in interactive web mode."""
    from celline.cli.interactive import main as interactive_main
    
    console.print("[bold]🧬 Starting Celline Interactive Mode[/bold]")
    console.print("This will launch both the API server and web interface...")
    console.print()
    
    try:
        interactive_main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Interactive mode stopped[/yellow]")
    except Exception as e:
        console.print(f"[red]Error starting interactive mode: {e}[/red]")
        import traceback
        if console.is_terminal:
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


def cmd_api(args: argparse.Namespace) -> None:
    """Start only the API server for testing."""
    console.print("[bold]🚀 Starting Celline API Server[/bold]")
    console.print("This will start only the API server on http://localhost:8000")
    console.print()
    
    try:
        import sys
        from pathlib import Path
        
        # Add project root to Python path
        project_root = Path(__file__).parent.parent.parent
        sys.path.insert(0, str(project_root / "src"))
        
        from celline.cli.start_simple_api import main
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]API server stopped[/yellow]")
    except Exception as e:
        console.print(f"[red]Error starting API server: {e}[/red]")
        import traceback
        if console.is_terminal:
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
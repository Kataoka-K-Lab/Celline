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
    """Initialize celline system configuration (same as 'celline run init')."""
    from celline.functions.initialize import Initialize
    from celline import Project
    import os
    
    try:
        # Create a Project instance to properly initialize Config.PROJ_ROOT
        current_dir = os.getcwd()
        project = Project(current_dir)
        
        initialize_func = Initialize()
        initialize_func.call(project)
    except KeyboardInterrupt:
        console.print("\n[yellow]Initialization cancelled.[/yellow]")
    except Exception as e:
        console.print(f"[red]Error during initialization: {e}[/red]")


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


def cmd_config(args: argparse.Namespace) -> None:
    """Configure celline settings."""
    from celline.config import Config, Setting
    import os
    import toml
    
    # Set current directory as project directory if no setting.toml exists
    current_dir = os.getcwd()
    Config.PROJ_ROOT = current_dir
    
    # Load existing settings if available
    setting_file = f"{current_dir}/setting.toml"
    if os.path.isfile(setting_file):
        with open(setting_file, encoding="utf-8") as f:
            setting_data = toml.load(f)
            Setting.name = setting_data.get("project", {}).get("name", "default")
            Setting.version = setting_data.get("project", {}).get("version", "0.01")
            Setting.wait_time = setting_data.get("fetch", {}).get("wait_time", 4)
            Setting.r_path = setting_data.get("R", {}).get("r_path", "")
            execution_settings = setting_data.get("execution", {})
            Setting.system = execution_settings.get("system", "multithreading")
            Setting.nthread = execution_settings.get("nthread", 1)
            Setting.pbs_server = execution_settings.get("pbs_server", "")
    else:
        # Initialize default settings
        Setting.name = "default"
        Setting.version = "0.01"
        Setting.wait_time = 4
        Setting.r_path = ""
        Setting.system = "multithreading"
        Setting.nthread = 1
        Setting.pbs_server = ""
    
    # Check if any config options are provided
    config_changed = False
    
    if args.system:
        if args.system not in ["multithreading", "PBS"]:
            console.print("[red]Error: --system must be either 'multithreading' or 'PBS'[/red]")
            return
        Setting.system = args.system
        config_changed = True
        console.print(f"[green]System set to: {args.system}[/green]")
    
    if args.nthread:
        if args.nthread < 1:
            console.print("[red]Error: --nthread must be a positive integer[/red]")
            return
        Setting.nthread = args.nthread
        config_changed = True
        console.print(f"[green]Number of threads set to: {args.nthread}[/green]")
    
    if args.pbs_server:
        Setting.pbs_server = args.pbs_server
        config_changed = True
        console.print(f"[green]PBS server set to: {args.pbs_server}[/green]")
    
    if config_changed:
        # Save the updated configuration
        Setting.flush()
        console.print("[green]Configuration saved successfully.[/green]")
    else:
        # Show current configuration
        console.print("[bold]Current Celline Configuration:[/bold]")
        console.print()
        console.print(f"Project name: {Setting.name}")
        console.print(f"Version: {Setting.version}")
        console.print(f"R path: {Setting.r_path}")
        console.print(f"Wait time: {Setting.wait_time}")
        console.print(f"Execution system: {Setting.system}")
        console.print(f"Number of threads: {Setting.nthread}")
        if Setting.pbs_server:
            console.print(f"PBS server: {Setting.pbs_server}")
        console.print()
        console.print("Use --system, --nthread, or --pbs-server to modify settings.")
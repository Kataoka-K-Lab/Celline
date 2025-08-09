"""CLI commands for celline."""

import argparse
import sys
from typing import List, Optional

from rich.console import Console
from rich.table import Table
from rich.text import Text

from celline.cli.registry import get_registry

# Lazy imports to avoid heavy dependency loading


console = Console()


def cmd_list(args: argparse.Namespace) -> None:
    """List all available CellineFunction implementations."""
    # Initialize project root for custom function discovery
    import os

    import toml

    from celline.config import Config, Setting

    # Set current directory as project root
    current_dir = os.getcwd()
    Config.PROJ_ROOT = current_dir

    # Load settings if available for custom functions
    setting_file = f"{current_dir}/setting.toml"
    if os.path.isfile(setting_file):
        with open(setting_file, encoding="utf-8") as f:
            setting_data = toml.load(f)
            custom_settings = setting_data.get("custom_functions", {})
            Setting.custom_functions_dir = custom_settings.get("directory", "functions")
            Setting.enable_custom_functions = custom_settings.get("enabled", True)
    else:
        # Set defaults
        Setting.custom_functions_dir = "functions"
        Setting.enable_custom_functions = True

    registry = get_registry()
    functions = registry.list_functions()

    if not functions:
        console.print("[yellow]No CellineFunction implementations found.[/yellow]")
        return

    # Separate built-in and custom functions
    builtin_functions = [f for f in functions if not f.is_custom]
    custom_functions = [f for f in functions if f.is_custom]

    # Create a table for built-in functions
    if builtin_functions:
        table = Table(title="Built-in Celline Functions")
        table.add_column("Command", style="cyan", no_wrap=True)
        table.add_column("Class", style="magenta")
        table.add_column("Description", style="green")
        table.add_column("Module", style="dim")

        # Sort functions by name
        for func in sorted(builtin_functions, key=lambda f: f.name):
            table.add_row(
                func.name,
                func.class_name,
                func.description,
                func.module_path.replace("celline.functions.", ""),
            )

        console.print(table)
        console.print(f"[dim]Built-in functions: {len(builtin_functions)}[/dim]")

    # Create a table for custom functions
    if custom_functions:
        console.print()  # Add spacing
        custom_table = Table(title="Custom User Functions")
        custom_table.add_column("Command", style="yellow", no_wrap=True)
        custom_table.add_column("Class", style="bright_magenta")
        custom_table.add_column("Description", style="bright_green")
        custom_table.add_column("Module", style="bright_black")

        # Sort custom functions by name
        for func in sorted(custom_functions, key=lambda f: f.name):
            module_display = func.module_path.replace("custom.", "") if func.module_path.startswith("custom.") else func.module_path
            custom_table.add_row(
                func.name,
                func.class_name,
                func.description,
                module_display,
            )

        console.print(custom_table)
        console.print(f"[dim]Custom functions: {len(custom_functions)}[/dim]")

    # Print total
    console.print(f"\n[bold]Total: {len(functions)} functions[/bold]")

    # Show instructions for custom functions
    if not custom_functions:
        console.print()
        console.print("[dim]💡 Create your own custom functions with:[/dim]")
        console.print("[dim]   celline create <function_name>[/dim]")


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
        from celline.cli.enhanced_invoker import EnhancedFunctionInvoker

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
        console.print("  create <function>   Create a new custom function template")
        console.print("  list                List all available functions")
        console.print("  help [function]     Show help for a specific function")
        console.print("  run <function>      Run a specific function")
        console.print("  run interactive     Launch interactive web interface")
        console.print("  interactive         Launch interactive web interface")
        console.print("  config              Configure execution settings (system, threads)")
        console.print("  info                Show system information")
        console.print("  api                 Start API server only (for testing)")
        console.print()
        console.print("Use 'celline init' to create a new project.")
        console.print("Use 'celline create <function_name>' to create custom functions.")
        console.print("Use 'celline list' to see all available functions.")
        console.print("Use 'celline help <function>' to see detailed help for a specific function.")


def cmd_run(args: argparse.Namespace) -> None:
    """Run a specific CellineFunction."""
    if not args.function_name:
        console.print("[red]Error: Function name is required.[/red]")
        console.print("Usage: celline run <function_name>")
        return

    # Initialize project root for custom function discovery
    import os

    import toml

    from celline.config import Config, Setting

    # Set current directory as project root if not already set
    if not hasattr(Config, "PROJ_ROOT") or not Config.PROJ_ROOT:
        current_dir = os.getcwd()
        Config.PROJ_ROOT = current_dir

        # Load settings if available for custom functions
        setting_file = f"{current_dir}/setting.toml"
        if os.path.isfile(setting_file):
            with open(setting_file, encoding="utf-8") as f:
                setting_data = toml.load(f)
                custom_settings = setting_data.get("custom_functions", {})
                Setting.custom_functions_dir = custom_settings.get("directory", "functions")
                Setting.enable_custom_functions = custom_settings.get("enabled", True)
        else:
            # Set defaults
            Setting.custom_functions_dir = "functions"
            Setting.enable_custom_functions = True

    registry = get_registry()
    func_info = registry.get_function(args.function_name)

    if not func_info:
        console.print(f"[red]Function '{args.function_name}' not found.[/red]")
        console.print("Use 'celline list' to see available functions.")
        return

    try:
        # Create a project instance
        project_dir = getattr(args, "project_dir", ".")
        project_name = getattr(args, "project_name", "default")

        console.print(f"[dim]Project: {project_name} (dir: {project_dir})[/dim]")

        # Lazy import Project
        from celline.interfaces import Project

        project = Project(project_dir, project_name)

        # Use enhanced invoker to handle function execution
        from celline.cli.enhanced_invoker import EnhancedFunctionInvoker

        invoker = EnhancedFunctionInvoker(func_info.class_ref)

        # Extract function-specific arguments (everything after the function name)
        # This includes both positional args and options like --nthread
        function_args = getattr(args, "function_args", [])

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
    import os

    from celline.functions.initialize import Initialize

    try:
        # Create a Project instance to properly initialize Config.PROJ_ROOT
        current_dir = os.getcwd()

        # Lazy import Project
        from celline.interfaces import Project

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
        module = func.module_path.replace("celline.functions.", "")
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
    import os

    import inquirer
    import toml

    from celline.config import Config, Setting

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
            # Load custom functions settings
            custom_settings = setting_data.get("custom_functions", {})
            Setting.custom_functions_dir = custom_settings.get("directory", "functions")
            Setting.enable_custom_functions = custom_settings.get("enabled", True)
    else:
        # Initialize default settings
        Setting.name = "default"
        Setting.version = "0.01"
        Setting.wait_time = 4
        Setting.r_path = ""
        Setting.system = "multithreading"
        Setting.nthread = 1
        Setting.pbs_server = ""
        Setting.custom_functions_dir = "functions"
        Setting.enable_custom_functions = True

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
        # Interactive configuration mode
        console.print("[bold]🔧 Celline Configuration[/bold]")
        console.print()
        console.print("[dim]Current settings:[/dim]")
        console.print(f"  Execution system: {Setting.system}")
        console.print(f"  Number of threads: {Setting.nthread}")
        if Setting.pbs_server:
            console.print(f"  PBS server: {Setting.pbs_server}")
        console.print()

        try:
            # Ask if user wants to modify settings
            modify_question = [
                inquirer.Confirm(
                    name="modify",
                    message="Do you want to modify the execution settings?",
                    default=True,
                ),
            ]
            modify_result = inquirer.prompt(modify_question, raise_keyboard_interrupt=True)

            if modify_result is None or not modify_result["modify"]:
                console.print("[yellow]Configuration unchanged.[/yellow]")
                return

            # Interactive system selection
            system_question = [
                inquirer.List(
                    name="system",
                    message="Select execution system",
                    choices=[
                        ("Multithreading (recommended for local execution)", "multithreading"),
                        ("PBS (for cluster execution)", "PBS"),
                    ],
                    default=Setting.system,
                ),
            ]
            system_result = inquirer.prompt(system_question, raise_keyboard_interrupt=True)

            if system_result is None:
                console.print("[yellow]Configuration cancelled.[/yellow]")
                return

            new_system = system_result["system"]

            # Interactive thread count selection
            thread_question = [
                inquirer.Text(
                    name="nthread",
                    message="Enter number of threads (1-64)",
                    default=str(Setting.nthread),
                    validate=lambda _, x: x.isdigit() and 1 <= int(x) <= 64,
                ),
            ]
            thread_result = inquirer.prompt(thread_question, raise_keyboard_interrupt=True)

            if thread_result is None:
                console.print("[yellow]Configuration cancelled.[/yellow]")
                return

            new_nthread = int(thread_result["nthread"])

            # PBS server configuration if PBS is selected
            new_pbs_server = Setting.pbs_server
            if new_system == "PBS":
                pbs_question = [
                    inquirer.Text(
                        name="pbs_server",
                        message="Enter PBS server name",
                        default=Setting.pbs_server if Setting.pbs_server else "your-cluster-name",
                    ),
                ]
                pbs_result = inquirer.prompt(pbs_question, raise_keyboard_interrupt=True)

                if pbs_result is None:
                    console.print("[yellow]Configuration cancelled.[/yellow]")
                    return

                new_pbs_server = pbs_result["pbs_server"]

            # Apply changes
            Setting.system = new_system
            Setting.nthread = new_nthread
            Setting.pbs_server = new_pbs_server

            # Save configuration
            Setting.flush()

            console.print()
            console.print("[green]✅ Configuration updated successfully![/green]")
            console.print()
            console.print("[bold]New settings:[/bold]")
            console.print(f"  Execution system: {Setting.system}")
            console.print(f"  Number of threads: {Setting.nthread}")
            if Setting.pbs_server:
                console.print(f"  PBS server: {Setting.pbs_server}")
            console.print()
            console.print("[dim]These settings will be applied automatically when creating new Project instances.[/dim]")

        except KeyboardInterrupt:
            console.print("\n[yellow]Configuration cancelled by user.[/yellow]")


def cmd_export(args: argparse.Namespace) -> None:
    """Handle export commands."""
    if not hasattr(args, "export_command") or args.export_command is None:
        console.print("[red]Error: Export subcommand is required.[/red]")
        console.print("Usage: celline export <subcommand>")
        console.print("Available subcommands: metareport")
        return

    if args.export_command == "metareport":
        cmd_export_metareport(args)
    else:
        console.print(f"[red]Unknown export command: {args.export_command}[/red]")


def cmd_export_metareport(args: argparse.Namespace) -> None:
    """Generate metadata report from samples.toml."""
    import os

    from celline.functions.export_metareport import ExportMetaReport

    try:
        # Create a Project instance
        project_dir = getattr(args, "project_dir", ".")

        # Lazy import Project
        from celline.interfaces import Project

        project = Project(project_dir)

        # Set output file and AI flag
        output_file = getattr(args, "output", "metadata_report.html")
        use_ai = getattr(args, "ai", False)

        console.print("[dim]Generating metadata report...[/dim]")
        console.print(f"[dim]Project directory: {project_dir}[/dim]")
        console.print(f"[dim]Output file: {output_file}[/dim]")
        if use_ai:
            console.print("[dim]AI analysis: enabled[/dim]")

        # Create and run the export function
        export_func = ExportMetaReport(output_file=output_file, use_ai=use_ai)
        export_func.call(project)

        console.print(f"[green]✅ Metadata report generated: {output_file}[/green]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Export cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error generating report: {e}[/red]")
        import traceback

        if console.is_terminal:
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


def cmd_create(args: argparse.Namespace) -> None:
    """Create a new custom function template."""
    import os
    import re
    from pathlib import Path

    from celline.config import Config, Setting

    if not hasattr(args, "function_name") or not args.function_name:
        console.print("[red]Error: Function name is required.[/red]")
        console.print("Usage: celline create <function_name>")
        return

    function_name = args.function_name

    # Validate function name
    if not re.match(r"^[a-zA-Z_][a-zA-Z0-9_]*$", function_name):
        console.print("[red]Error: Function name must be a valid Python identifier.[/red]")
        console.print("Example: my_function, analyze_data, process_samples")
        return

    try:
        # Get project directory and settings
        project_dir = getattr(args, "project_dir", ".")

        # Initialize Config.PROJ_ROOT
        Config.PROJ_ROOT = os.path.abspath(project_dir)

        # Load settings if available
        setting_file = f"{Config.PROJ_ROOT}/setting.toml"
        if os.path.isfile(setting_file):
            import toml

            with open(setting_file, encoding="utf-8") as f:
                setting_data = toml.load(f)
                custom_config = setting_data.get("custom_functions", {})
                Setting.custom_functions_dir = custom_config.get("directory", "functions")
                Setting.enable_custom_functions = custom_config.get("enabled", True)

        # Create custom functions directory
        custom_functions_path = Path(Config.PROJ_ROOT) / Setting.custom_functions_dir
        custom_functions_path.mkdir(parents=True, exist_ok=True)

        # Create function file
        function_file = custom_functions_path / f"{function_name}.py"

        if function_file.exists():
            console.print(f"[yellow]Warning: Function file already exists: {function_file}[/yellow]")

            import inquirer

            overwrite_question = [
                inquirer.Confirm(
                    name="overwrite",
                    message="Do you want to overwrite the existing file?",
                    default=False,
                ),
            ]
            overwrite_result = inquirer.prompt(overwrite_question, raise_keyboard_interrupt=True)

            if overwrite_result is None or not overwrite_result["overwrite"]:
                console.print("[yellow]Function creation cancelled.[/yellow]")
                return

        # Generate function template
        template_content = _generate_function_template(function_name)

        # Write function file
        with open(function_file, "w", encoding="utf-8") as f:
            f.write(template_content)

        console.print(f"[green]✅ Custom function created: {function_file}[/green]")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print(f"1. Edit {function_file} to implement your function")
        console.print("2. Use 'celline list' to see your function in the list")
        console.print(f"3. Run your function with 'celline run custom_{function_name}'")
        console.print()
        console.print("[dim]The function template includes:")
        console.print("- Basic CellineFunction structure")
        console.print("- CLI argument handling")
        console.print("- Documentation templates")
        console.print("- Usage examples[/dim]")

    except KeyboardInterrupt:
        console.print("\n[yellow]Function creation cancelled by user[/yellow]")
    except Exception as e:
        console.print(f"[red]Error creating function: {e}[/red]")
        import traceback

        if console.is_terminal:
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


def _generate_function_template(function_name: str) -> str:
    """Generate a template for a custom CellineFunction."""
    class_name = "".join(word.capitalize() for word in function_name.split("_"))

    return f'''"""
Custom Celline Function: {function_name}

This is an auto-generated template for a custom Celline function.
Implement your functionality in the call() method below.

Generated by: celline create {function_name}
"""

import argparse
from typing import TYPE_CHECKING

from celline.functions._base import CellineFunction
from rich.console import Console

if TYPE_CHECKING:
    from celline import Project

console = Console()


class {class_name}(CellineFunction):
    """Custom function: {function_name}

    TODO: Add a description of what this function does.

    Example usage:
    - celline run custom_{function_name}
    - celline run custom_{function_name} --example-arg value
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Initialize your parameters here
        # Example:
        # self.example_param = kwargs.get('example_param', 'default_value')

    def register(self) -> str:
        """Register this function with a specific name."""
        return "custom_{function_name}"

    def call(self, project: "Project"):
        """Main function implementation.

        Args:
            project: The Celline project instance

        Returns:
            project: The project instance (for chaining)
        """
        console.print(f"[cyan]Running custom function: {function_name}[/cyan]")

        # TODO: Implement your function logic here
        # You can access:
        # - project.samples: Sample information
        # - project.config: Project configuration
        # - Any parameters from self.__init__

        # Example implementation:
        console.print("Hello from your custom function!")
        console.print(f"Project directory: {{project.config.PROJ_ROOT}}")

        # TODO: Add your data processing, analysis, or visualization code

        console.print("[green]Custom function completed successfully![/green]")
        return project

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add command-line arguments for this function.

        Args:
            parser: The ArgumentParser to add arguments to
        """
        # TODO: Add your custom CLI arguments here
        # Examples:
        # parser.add_argument("--input-file", type=str, help="Input file path")
        # parser.add_argument("--output-dir", type=str, default="output", help="Output directory")
        # parser.add_argument("--threads", type=int, default=1, help="Number of threads")
        # parser.add_argument("--force", action="store_true", help="Force overwrite existing files")
        pass

    def cli(self, project: "Project", args: argparse.Namespace | None = None) -> "Project":
        """CLI entry point for this function.

        Args:
            project: The Project instance
            args: Parsed CLI arguments

        Returns:
            Project: The project instance (for chaining)
        """
        # TODO: Process CLI arguments and set instance variables
        # Example:
        # if args and hasattr(args, 'input_file'):
        #     self.input_file = args.input_file
        # if args and hasattr(args, 'threads'):
        #     self.threads = args.threads

        console.print(f"[dim]Starting custom function: {function_name}[/dim]")

        # Call the main implementation
        return self.call(project)

    def get_description(self) -> str:
        """Get a description of this function for CLI help."""
        return """Custom function: {function_name}

TODO: Provide a detailed description of what this function does.

This function can be used to:
- TODO: List main capabilities
- TODO: Describe input/output
- TODO: Mention any requirements or dependencies

Example workflow:
1. TODO: Step 1
2. TODO: Step 2
3. TODO: Step 3
"""

    def get_usage_examples(self) -> list[str]:
        """Get usage examples for CLI help."""
        return [
            # TODO: Add realistic usage examples
            "celline run custom_{function_name}",
            "celline run custom_{function_name} --help",
            # "celline run custom_{function_name} --input-file data.csv --output-dir results",
            # "celline run custom_{function_name} --threads 4 --force",
        ]


# You can add additional helper functions or classes here if needed

def helper_function():
    """Example helper function."""
    pass
'''

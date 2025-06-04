import inquirer
from rich.console import Console
from pathlib import Path

from celline.config import Setting
from celline.functions._base import CellineFunction
from celline.utils.dependencies import DependencyValidator


class Initialize(CellineFunction):
    def register(self) -> str:
        return "init"

    def call(self, project):
        console = Console()
        
        # Check system dependencies first
        console.print("[cyan]Checking system dependencies...[/cyan]")
        
        # First check all system dependencies (cellranger, R, fastq-dump)
        if not DependencyValidator.validate_dependencies(show_details=True, check_r_packages=False):
            console.print("\n[red]Initialization failed due to missing dependencies.[/red]")
            console.print("[yellow]Please install the required dependencies and run 'celline init' again.[/yellow]")
            return project
        
        console.print("\n[green]All system dependencies are available![/green]")
        
        # Now select R installation (R is guaranteed to be available now)
        console.print("\n[cyan]Setting up R environment...[/cyan]")
        selected_r_path = DependencyValidator.select_r_installation()
        if selected_r_path is None:
            console.print("\n[red]R installation selection cancelled or failed.[/red]")
            return project
        
        console.print("\n[green]All dependencies are ready! Proceeding with initialization...[/green]\n")
        
        settings = Setting()
        questions = [
            inquirer.Text(name="projname", message="What is a name of your project?"),
        ]
        result = inquirer.prompt(questions, raise_keyboard_interrupt=True)
        if result is None:
            quit()
        
        project_name = result["projname"]
        settings.name = project_name
        settings.r_path = selected_r_path
        settings.version = "0.1"
        settings.wait_time = 4
        settings.flush()
        
        # Create project files and directories
        console.print("[cyan]Setting up project structure...[/cyan]")
        
        # Create data directory if it doesn't exist
        
        project_root = Path.cwd()
        data_dir = project_root / "data"
        results_dir = project_root / "results"
        scripts_dir = project_root / "scripts"
        
        # Create directories
        data_dir.mkdir(exist_ok=True)
        results_dir.mkdir(exist_ok=True)  
        scripts_dir.mkdir(exist_ok=True)
        
        # Create samples.toml if it doesn't exist
        samples_file = project_root / "samples.toml"
        if not samples_file.exists():
            samples_content = f"""# Sample configuration for {project_name}
# Add your samples here following this format:
#
# [samples.sample1]
# name = "Sample 1"
# path = "data/sample1"
#
# [samples.sample2] 
# name = "Sample 2"
# path = "data/sample2"

# Example:
# [samples.GSM123456]
# name = "Control sample"
# path = "data/GSM123456"
"""
            samples_file.write_text(samples_content)
            console.print(f"[green]Created samples.toml[/green]")
        
        # Create setting.toml if it doesn't exist
        setting_file = project_root / "setting.toml"
        if not setting_file.exists():
            setting_content = f"""[project]
name = "{project_name}"
version = "1.0.0"
description = "Single cell analysis project"

[analysis]
# Analysis parameters go here
# threads = 4
# memory_limit = "8G"

[paths]
data_dir = "data"
results_dir = "results"
scripts_dir = "scripts"
"""
            setting_file.write_text(setting_content)
            console.print(f"[green]Created setting.toml[/green]")
        
        console.print(f"[green]Project structure created:[/green]")
        console.print(f"  📁 {data_dir.name}/     - Raw and processed data files")
        console.print(f"  📁 {results_dir.name}/  - Analysis results and outputs")  
        console.print(f"  📁 {scripts_dir.name}/  - Custom analysis scripts")
        console.print(f"  📄 samples.toml   - Sample configuration")
        console.print(f"  📄 setting.toml   - Project settings")
        
        console.print(f"\n[green]Initialization completed successfully![/green]")
        console.print(f"\n[bold cyan]Next steps:[/bold cyan]")
        console.print(f"  1. Edit samples.toml to configure your samples")
        console.print(f"  2. Run 'celline list' to see available functions")
        console.print(f"  3. Run 'celline run add <sample_id>' to add samples")
        
        return project

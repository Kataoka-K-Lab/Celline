import subprocess

import inquirer
from rich.console import Console

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
        
        # First check all system dependencies (cellranger, rig, fastq-dump)
        if not DependencyValidator.validate_dependencies(show_details=True, check_r_packages=False):
            console.print("\n[red]Initialization failed due to missing dependencies.[/red]")
            console.print("[yellow]Please install the required dependencies and run 'celline init' again.[/yellow]")
            return project
        
        console.print("\n[green]All system dependencies are available![/green]")
        
        # Now select R installation using rig (rig is guaranteed to be available now)
        console.print("\n[cyan]Setting up R environment...[/cyan]")
        selected_r_path = DependencyValidator.select_r_installation()
        if selected_r_path is None:
            console.print("\n[red]R installation selection cancelled or failed.[/red]")
            return project
        
        # Check and install R packages
        console.print("\n" + "="*50)
        if not DependencyValidator.validate_r_packages(selected_r_path, interactive=True):
            console.print("\n[red]R package setup failed.[/red]")
            console.print("[yellow]Please install the required R packages and run 'celline init' again.[/yellow]")
            return project
        
        console.print("\n[green]All dependencies and R packages are ready! Proceeding with initialization...[/green]\n")
        
        settings = Setting()
        questions = [
            inquirer.Text(name="projname", message="What is a name of your project?"),
        ]
        result = inquirer.prompt(questions, raise_keyboard_interrupt=True)
        if result is None:
            quit()
        settings.name = result["projname"]
        settings.r_path = selected_r_path
        settings.version = "0.1"
        settings.wait_time = 4
        settings.flush()
        console.print("[green]Initialization completed successfully![/green]")
        return project

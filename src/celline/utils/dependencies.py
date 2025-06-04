import subprocess
import shutil
import re
import os
from pathlib import Path
from typing import List, NamedTuple, Optional, Set
from rich.console import Console
from rich.table import Table
from rich.prompt import Confirm
import inquirer

console = Console()


class DependencyCheck(NamedTuple):
    """Represents a dependency check result."""
    name: str
    available: bool
    path: Optional[str] = None
    version: Optional[str] = None


class RPackageCheck(NamedTuple):
    """Represents an R package check result."""
    name: str
    available: bool
    version: Optional[str] = None


class DependencyValidator:
    """Validates system dependencies for Celline."""
    
    REQUIRED_DEPENDENCIES = [
        "cellranger",
        "rig",
        "fastq-dump"
    ]
    
    OPTIONAL_DEPENDENCIES = [
        "wget",
        "curl"
    ]
    
    # Required R packages found in the codebase
    REQUIRED_R_PACKAGES = [
        "pacman",
        "Seurat", 
        "SeuratDisk",
        "SeuratObject",
        "tidyverse",
        "scPred",
        "doParallel",
        "scran",
        "batchelor",
        "Matrix"
    ]
    
    @staticmethod
    def check_command(command: str) -> DependencyCheck:
        """Check if a command is available in the system PATH."""
        path = shutil.which(command)
        if path:
            version = DependencyValidator._get_version(command)
            return DependencyCheck(name=command, available=True, path=path, version=version)
        else:
            return DependencyCheck(name=command, available=False)
    
    @staticmethod
    def _get_version(command: str) -> Optional[str]:
        """Get version of a command if possible."""
        try:
            if command == "cellranger":
                result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return result.stdout.strip().split('\n')[0]
            elif command == "R":
                result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if "R version" in line:
                            return line.split()[2]
            elif command == "rig":
                result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return result.stdout.strip().split('\n')[0]
            elif command == "fastq-dump":
                result = subprocess.run([command, "--version"], capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return result.stdout.strip().split('\n')[0]
        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
        return None
    
    @staticmethod
    def check_r_package(package: str, r_path: Optional[str] = None) -> RPackageCheck:
        """Check if an R package is installed."""
        r_command = r_path if r_path else "R"
        
        try:
            # Create R script to check package
            r_script = f'''
            if (require("{package}", quietly = TRUE, character.only = TRUE)) {{
                version <- packageVersion("{package}")
                cat("AVAILABLE:", version)
            }} else {{
                cat("NOT_AVAILABLE")
            }}
            '''
            
            result = subprocess.run(
                [r_command, "--slave", "--vanilla", "-e", r_script],
                capture_output=True, text=True, timeout=30
            )
            
            if result.returncode == 0:
                output = result.stdout.strip()
                if output.startswith("AVAILABLE:"):
                    version = output.replace("AVAILABLE:", "").strip()
                    return RPackageCheck(name=package, available=True, version=version)
                else:
                    return RPackageCheck(name=package, available=False)
            else:
                return RPackageCheck(name=package, available=False)
                
        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            return RPackageCheck(name=package, available=False)
    
    @staticmethod
    def install_r_packages(packages: List[str], r_path: Optional[str] = None) -> bool:
        """Install R packages using rig-managed R installation."""
        if r_path is None:
            console.print("[red]R path is required for package installation[/red]")
            return False
        
        return DependencyValidator.install_r_packages_with_rig(r_path, packages)
    
    @classmethod
    def check_r_packages(cls, r_path: Optional[str] = None) -> List[RPackageCheck]:
        """Check all required R packages."""
        return [cls.check_r_package(pkg, r_path) for pkg in cls.REQUIRED_R_PACKAGES]
    
    @classmethod
    def validate_r_packages(cls, r_path: Optional[str] = None, interactive: bool = True) -> bool:
        """Validate R packages and optionally install missing ones."""
        console.print("[cyan]Checking R packages...[/cyan]")
        
        checks = cls.check_r_packages(r_path)
        missing_packages = [check.name for check in checks if not check.available]
        
        # Display R package status
        cls.display_r_package_status(checks)
        
        if missing_packages:
            if interactive:
                console.print(f"\n[yellow]Found {len(missing_packages)} missing R packages.[/yellow]")
                
                install = Confirm.ask(
                    "Would you like to install the missing R packages automatically?",
                    default=True
                )
                
                if install:
                    success = cls.install_r_packages(missing_packages, r_path)
                    if success:
                        # Re-check packages after installation
                        console.print("\n[cyan]Re-checking R packages...[/cyan]")
                        new_checks = cls.check_r_packages(r_path)
                        still_missing = [check.name for check in new_checks if not check.available]
                        
                        if still_missing:
                            console.print(f"[red]Some packages failed to install: {', '.join(still_missing)}[/red]")
                            cls.display_r_installation_instructions(still_missing)
                            return False
                        else:
                            console.print("[green]All R packages are now available![/green]")
                            return True
                    else:
                        cls.display_r_installation_instructions(missing_packages)
                        return False
                else:
                    cls.display_r_installation_instructions(missing_packages)
                    return False
            else:
                cls.display_r_installation_instructions(missing_packages)
                return False
        else:
            console.print("[green]All required R packages are available![/green]")
            return True
    
    @staticmethod
    def display_r_package_status(checks: List[RPackageCheck]):
        """Display R package status in a formatted table."""
        table = Table(title="R Package Status", show_header=True, header_style="bold cyan")
        table.add_column("Package", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Version")
        
        for check in checks:
            status = "[green]✓ Available[/green]" if check.available else "[red]✗ Missing[/red]"
            version = check.version or "[dim]Unknown[/dim]"
            table.add_row(check.name, status, version)
        
        console.print(table)
    
    @staticmethod
    def display_r_installation_instructions(missing_packages: List[str]):
        """Display installation instructions for missing R packages."""
        console.print("\n[bold red]Missing R Packages[/bold red]")
        console.print("The following required R packages are missing:\n")
        
        packages_str = '", "'.join(missing_packages)
        
        console.print(f"[red]Missing packages: {', '.join(missing_packages)}[/red]\n")
        
        console.print("[bold]Manual Installation Instructions:[/bold]")
        console.print("You can install these packages manually in R:")
        console.print()
        console.print(f'[dim]# Install pak first (if not available)[/dim]')
        console.print(f'[cyan]install.packages("pak")[/cyan]')
        console.print()
        console.print(f'[dim]# Install all required packages[/dim]')
        console.print(f'[cyan]pak::pkg_install(c("{packages_str}"))[/cyan]')
        console.print()
        console.print("[yellow]Please install the missing R packages before proceeding.[/yellow]")
    
    @classmethod
    def check_all_dependencies(cls) -> List[DependencyCheck]:
        """Check all required and optional dependencies."""
        results = []
        
        for dep in cls.REQUIRED_DEPENDENCIES:
            results.append(cls.check_command(dep))
        
        for dep in cls.OPTIONAL_DEPENDENCIES:
            results.append(cls.check_command(dep))
        
        return results
    
    @classmethod
    def check_required_dependencies(cls) -> List[DependencyCheck]:
        """Check only required dependencies."""
        return [cls.check_command(dep) for dep in cls.REQUIRED_DEPENDENCIES]
    
    @classmethod
    def validate_dependencies(cls, show_details: bool = True, check_r_packages: bool = True, r_path: Optional[str] = None) -> bool:
        """Validate all required dependencies and show results."""
        checks = cls.check_required_dependencies()
        missing_deps = [check for check in checks if not check.available]
        
        if show_details:
            cls.display_dependency_status(checks)
        
        if missing_deps:
            if show_details:
                cls.display_installation_instructions(missing_deps)
        
        # Check R packages even if other dependencies are missing, but only if rig is available
        rig_available = any(check.name == "rig" and check.available for check in checks)
        if check_r_packages and rig_available and r_path:
            console.print("\n" + "="*50)
            r_packages_valid = cls.validate_r_packages(r_path, interactive=True)
            if not r_packages_valid:
                return False
        
        # Return False if any system dependencies are missing
        if missing_deps:
            return False
        
        return True
    
    @staticmethod
    def display_dependency_status(checks: List[DependencyCheck]):
        """Display dependency status in a formatted table."""
        table = Table(title="Dependency Status", show_header=True, header_style="bold cyan")
        table.add_column("Dependency", style="bold")
        table.add_column("Status", justify="center")
        table.add_column("Path")
        table.add_column("Version")
        
        for check in checks:
            status = "[green]✓ Available[/green]" if check.available else "[red]✗ Missing[/red]"
            path = check.path or "[dim]Not found[/dim]"
            version = check.version or "[dim]Unknown[/dim]"
            table.add_row(check.name, status, path, version)
        
        console.print(table)
    
    @staticmethod
    def display_installation_instructions(missing_deps: List[DependencyCheck]):
        """Display installation instructions for missing dependencies."""
        console.print("\n[bold red]Missing Dependencies[/bold red]")
        console.print("The following required dependencies are missing:\n")
        
        for dep in missing_deps:
            console.print(f"[red]✗ {dep.name}[/red]")
            
            if dep.name == "cellranger":
                console.print("  Installation: Download from 10x Genomics website")
                console.print("  URL: https://support.10xgenomics.com/single-cell-gene-expression/software/downloads/latest")
                console.print("  After installation, add cellranger to your PATH\n")
                
            elif dep.name == "R":
                console.print("  Installation:")
                console.print("  - macOS: brew install r")
                console.print("  - Ubuntu/Debian: sudo apt-get install r-base")
                console.print("  - CentOS/RHEL: sudo yum install R")
                console.print("  - Or download from: https://cran.r-project.org/\n")
                
            elif dep.name == "rig":
                console.print("  Installation: Install R Installation Manager (rig)")
                console.print("  rig is a tool for managing multiple R versions")
                console.print("")
                console.print("  [bold cyan]Quick Installation:[/bold cyan]")
                console.print("  - macOS:")
                console.print("    curl -Ls https://github.com/r-lib/rig/releases/latest/download/rig-macos-latest.tar.gz | sudo tar xz -C /usr/local/bin")
                console.print("  - Linux:")
                console.print("    curl -Ls https://github.com/r-lib/rig/releases/latest/download/rig-linux-latest.tar.gz | sudo tar xz -C /usr/local/bin")
                console.print("  - Windows: Download installer from GitHub releases")
                console.print("")
                console.print("  [bold cyan]Alternative Installation:[/bold cyan]")
                console.print("  - Download from: https://github.com/r-lib/rig/releases")
                console.print("  - macOS: Download .pkg installer")
                console.print("  - Linux: Download .deb/.rpm package")
                console.print("  - Windows: Download .exe installer")
                console.print("")
                console.print("  [bold yellow]After installation, verify with: rig --version[/bold yellow]\n")
                
            elif dep.name == "fastq-dump":
                console.print("  Installation: Install SRA Toolkit")
                console.print("  - macOS: brew install sratoolkit")
                console.print("  - Ubuntu/Debian: sudo apt-get install sra-toolkit")
                console.print("  - Or download from: https://github.com/ncbi/sra-tools\n")
        
        console.print("[yellow]Please install the missing dependencies before proceeding.[/yellow]")
    
    @staticmethod
    def get_rig_installations() -> List[tuple]:
        """Get R installations managed by rig."""
        installations = []
        
        try:
            result = subprocess.run(
                ["rig", "list"], 
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if line.strip() and not line.startswith('*'):
                        # Parse rig list output: "4.3.2 /usr/local/lib/R/4.3.2"
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            version = parts[0]
                            path = parts[1]
                            r_executable = os.path.join(path, "bin", "R")
                            if os.path.exists(r_executable):
                                installations.append((version, r_executable))
        except (subprocess.SubprocessError, subprocess.TimeoutExpired, FileNotFoundError):
            pass
        
        return installations
    
    @staticmethod
    def create_rig_environment(r_version: str = "release") -> Optional[str]:
        """Create a new R environment using rig."""
        console.print(f"[cyan]Creating R environment with rig (version: {r_version})...[/cyan]")
        
        try:
            # Install the R version if not already installed
            console.print(f"[cyan]Installing R {r_version}...[/cyan]")
            
            # Use rig add without sudo - rig handles user installations
            cmd = ["rig", "add", r_version]
            console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")
            
            # Run with real-time output
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Show real-time output
            output_lines = []
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    output_lines.append(output.strip())
                    console.print(f"[dim]{output.strip()}[/dim]")
            
            # Wait for completion
            return_code = process.poll()
            
            if return_code != 0:
                console.print(f"[red]Failed to install R {r_version}[/red]")
                console.print(f"[red]Exit code: {return_code}[/red]")
                if output_lines:
                    console.print("[red]Output:[/red]")
                    for line in output_lines[-10:]:  # Show last 10 lines
                        console.print(f"[red]{line}[/red]")
                return None
            
            console.print(f"[green]Successfully installed R {r_version}[/green]")
            
            # Get the path of the installed R
            list_result = subprocess.run(
                ["rig", "list"], 
                capture_output=True, text=True, timeout=10
            )
            
            if list_result.returncode == 0:
                lines = list_result.stdout.strip().split('\n')
                for line in lines:
                    if line.strip():
                        parts = line.strip().split()
                        if len(parts) >= 2:
                            version_part = parts[0]
                            path = parts[1]
                            # Check if this matches our requested version
                            if (r_version == "release" and "*" in line) or r_version in version_part:
                                r_executable = os.path.join(path, "bin", "R")
                                if os.path.exists(r_executable):
                                    console.print(f"[green]R {version_part} is available at: {r_executable}[/green]")
                                    return r_executable
            
            console.print(f"[red]Could not find installed R {r_version}[/red]")
            return None
            
        except subprocess.TimeoutExpired:
            console.print("[red]R installation timed out[/red]")
            return None
        except Exception as e:
            console.print(f"[red]Error creating R environment: {e}[/red]")
            return None
    
    @staticmethod
    def install_r_packages_with_rig(r_path: str, packages: List[str]) -> bool:
        """Install R packages using the rig-managed R installation."""
        console.print(f"[cyan]Installing R packages with rig-managed R: {', '.join(packages)}[/cyan]")
        
        try:
            # Create R script for package installation
            packages_str = '", "'.join(packages)
            r_script = f'''
            # Install pacman if not available
            if (!require("pak", quietly = TRUE)) {{
                install.packages("pak", repos = "https://cloud.r-project.org/")
            }}
            
            # Install packages using pak (faster than install.packages)
            pak::pkg_install(c("{packages_str}"))
            '''
            
            console.print("[cyan]Installing packages (this may take several minutes)...[/cyan]")
            result = subprocess.run(
                [r_path, "--slave", "--vanilla", "-e", r_script],
                capture_output=True, text=True, timeout=1800  # 30 minutes timeout
            )
            
            if result.returncode == 0:
                console.print("[green]Successfully installed R packages![/green]")
                return True
            else:
                console.print(f"[red]Failed to install R packages: {result.stderr}[/red]")
                return False
                
        except subprocess.TimeoutExpired:
            console.print("[red]Package installation timed out[/red]")
            return False
        except Exception as e:
            console.print(f"[red]Error during package installation: {e}[/red]")
            return False
    
    @staticmethod
    def select_r_installation() -> Optional[str]:
        """Interactive R installation selection using rig."""
        console.print("\n[cyan]Selecting R installation...[/cyan]")
        
        # Check if rig is available
        rig_available = shutil.which("rig") is not None
        
        if not rig_available:
            console.print("[red]rig is not available. Please install rig first.[/red]")
            return None
        
        # Get existing rig installations
        rig_installations = DependencyValidator.get_rig_installations()
        
        # Create choices for inquirer
        choices = []
        
        # Add existing rig installations
        for version, path in rig_installations:
            choices.append(f"R {version} (rig) - {path}")
        
        # Add option to create new environment
        choices.extend([
            "Create new R environment (latest release)",
            "Create new R environment (devel)",
            "Create new R environment (custom version)",
            "Enter custom path manually"
        ])
        
        # Use inquirer for selection
        questions = [
            inquirer.List(
                'r_selection',
                message="Select R installation to use",
                choices=choices,
                carousel=True
            )
        ]
        
        try:
            result = inquirer.prompt(questions, raise_keyboard_interrupt=True)
            if result is None:
                return None
            
            selection = result['r_selection']
            
            if selection == "Create new R environment (latest release)":
                return DependencyValidator.create_rig_environment("release")
            elif selection == "Create new R environment (devel)":
                return DependencyValidator.create_rig_environment("devel")
            elif selection == "Create new R environment (custom version)":
                version_questions = [
                    inquirer.Text(
                        'r_version',
                        message="Enter R version to install (e.g., 4.3.2, 4.4.0)"
                    )
                ]
                version_result = inquirer.prompt(version_questions, raise_keyboard_interrupt=True)
                if version_result is None:
                    return None
                return DependencyValidator.create_rig_environment(version_result['r_version'])
            elif selection == "Enter custom path manually":
                # Manual path input
                manual_questions = [
                    inquirer.Path(
                        'r_path',
                        message="Enter the full path to R executable",
                        path_type=inquirer.Path.FILE
                    )
                ]
                manual_result = inquirer.prompt(manual_questions, raise_keyboard_interrupt=True)
                if manual_result is None:
                    return None
                
                manual_path = manual_result['r_path']
                
                # Validate the manual path
                if os.path.exists(manual_path) and os.access(manual_path, os.X_OK):
                    console.print(f"[green]Selected R: {manual_path}[/green]")
                    return manual_path
                else:
                    console.print(f"[red]Invalid R path: {manual_path}[/red]")
                    return None
            else:
                # Extract actual path from rig installation selection
                if " - " in selection:
                    r_path = selection.split(" - ")[1]
                    console.print(f"[green]Selected R: {r_path}[/green]")
                    return r_path
                else:
                    console.print(f"[red]Could not parse selection: {selection}[/red]")
                    return None
                
        except KeyboardInterrupt:
            console.print("\n[yellow]R selection cancelled.[/yellow]")
            return None
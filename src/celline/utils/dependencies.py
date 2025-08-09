import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, NamedTuple, Optional, Set

import inquirer
from rich.console import Console
from rich.prompt import Confirm
from rich.table import Table

console = Console()


class DependencyCheck(NamedTuple):
    """Represents a dependency check result."""

    name: str
    available: bool
    path: str | None = None
    version: str | None = None


class RPackageCheck(NamedTuple):
    """Represents an R package check result."""

    name: str
    available: bool
    version: str | None = None


class DependencyValidator:
    """Validates system dependencies for Celline."""

    REQUIRED_DEPENDENCIES = ["cellranger", "R", "fastq-dump"]

    OPTIONAL_DEPENDENCIES = ["wget", "curl"]

    # Required R packages found in the codebase
    REQUIRED_R_PACKAGES = ["pacman", "Seurat", "SeuratDisk", "SeuratObject", "tidyverse", "scPred", "doParallel", "scran", "batchelor", "Matrix"]

    @staticmethod
    def check_command(command: str) -> DependencyCheck:
        """Check if a command is available in the system PATH or conda/micromamba environments."""
        path = shutil.which(command)
        if path:
            version = DependencyValidator._get_version(command)
            return DependencyCheck(name=command, available=True, path=path, version=version)

        # Special handling for R - also check conda/micromamba environments
        if command == "R":
            conda_installations = DependencyValidator.get_conda_micromamba_r_installations()
            if conda_installations:
                # Use the first available R installation
                _, version, r_path = conda_installations[0]
                return DependencyCheck(name=command, available=True, path=r_path, version=version)

        return DependencyCheck(name=command, available=False)

    @staticmethod
    def _get_version(command: str) -> str | None:
        """Get version of a command if possible."""
        try:
            if command == "cellranger":
                result = subprocess.run([command, "--version"], check=False, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return result.stdout.strip().split("\n")[0]
            elif command == "R":
                result = subprocess.run([command, "--version"], check=False, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    for line in lines:
                        if "R version" in line:
                            return line.split()[2]
            elif command == "fastq-dump":
                result = subprocess.run([command, "--version"], check=False, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    return result.stdout.strip().split("\n")[0]
        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            pass
        return None

    @staticmethod
    def check_r_package(package: str, r_path: str | None = None) -> RPackageCheck:
        """Check if an R package is installed."""
        r_command = r_path if r_path else "R"

        try:
            # Create R script to check package
            r_script = f"""
            if (require("{package}", quietly = TRUE, character.only = TRUE)) {{
                version <- packageVersion("{package}")
                cat("AVAILABLE:", version)
            }} else {{
                cat("NOT_AVAILABLE")
            }}
            """

            result = subprocess.run([r_command, "--slave", "--vanilla", "-e", r_script], check=False, capture_output=True, text=True, timeout=30)

            if result.returncode == 0:
                output = result.stdout.strip()
                if output.startswith("AVAILABLE:"):
                    version = output.replace("AVAILABLE:", "").strip()
                    return RPackageCheck(name=package, available=True, version=version)
                return RPackageCheck(name=package, available=False)
            return RPackageCheck(name=package, available=False)

        except (subprocess.SubprocessError, subprocess.TimeoutExpired):
            return RPackageCheck(name=package, available=False)

    @staticmethod
    def install_r_packages(packages: list[str], r_path: str | None = None) -> bool:
        """Install R packages using pak."""
        r_command = r_path if r_path else "R"

        console.print(f"[cyan]Installing R packages: {', '.join(packages)}[/cyan]")

        try:
            # Create R script for package installation using pak (faster and more reliable)
            packages_str = '", "'.join(packages)
            r_script = f"""
            # Install pak if not available
            if (!require("pak", quietly = TRUE)) {{
                install.packages("pak", repos = "https://cloud.r-project.org/")
            }}

            # Install packages using pak
            pak::pkg_install(c("{packages_str}"))
            """

            console.print("[cyan]Installing packages (this may take several minutes)...[/cyan]")
            result = subprocess.run(
                [r_command, "--slave", "--vanilla", "-e", r_script],
                check=False,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minutes timeout
            )

            if result.returncode == 0:
                console.print("[green]Successfully installed R packages![/green]")
                return True
            console.print(f"[red]Failed to install R packages: {result.stderr}[/red]")
            return False

        except subprocess.TimeoutExpired:
            console.print("[red]Installation timed out. Please install packages manually.[/red]")
            return False
        except Exception as e:
            console.print(f"[red]Error during installation: {e}[/red]")
            return False

    @classmethod
    def check_r_packages(cls, r_path: str | None = None) -> list[RPackageCheck]:
        """Check all required R packages."""
        return [cls.check_r_package(pkg, r_path) for pkg in cls.REQUIRED_R_PACKAGES]

    @classmethod
    def validate_r_packages(cls, r_path: str | None = None, interactive: bool = True) -> bool:
        """Validate R packages and optionally install missing ones."""
        console.print("[cyan]Checking R packages...[/cyan]")

        checks = cls.check_r_packages(r_path)
        missing_packages = [check.name for check in checks if not check.available]

        # Display R package status
        cls.display_r_package_status(checks)

        if missing_packages:
            if interactive:
                console.print(f"\n[yellow]Found {len(missing_packages)} missing R packages.[/yellow]")

                install = Confirm.ask("Would you like to install the missing R packages automatically?", default=True)

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
                        console.print("[green]All R packages are now available![/green]")
                        return True
                    cls.display_r_installation_instructions(missing_packages)
                    return False
                cls.display_r_installation_instructions(missing_packages)
                return False
            cls.display_r_installation_instructions(missing_packages)
            return False
        console.print("[green]All required R packages are available![/green]")
        return True

    @staticmethod
    def display_r_package_status(checks: list[RPackageCheck]):
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
    def display_r_installation_instructions(missing_packages: list[str]):
        """Display installation instructions for missing R packages."""
        console.print("\n[bold red]Missing R Packages[/bold red]")
        console.print("The following required R packages are missing:\n")

        packages_str = '", "'.join(missing_packages)

        console.print(f"[red]Missing packages: {', '.join(missing_packages)}[/red]\n")

        console.print("[bold]Manual Installation Instructions:[/bold]")
        console.print("You can install these packages manually in R:")
        console.print()
        console.print("[dim]# Install pak first (if not available)[/dim]")
        console.print('[cyan]install.packages("pak")[/cyan]')
        console.print()
        console.print("[dim]# Install all required packages[/dim]")
        console.print(f'[cyan]pak::pkg_install(c("{packages_str}"))[/cyan]')
        console.print()
        console.print("[yellow]Please install the missing R packages before proceeding.[/yellow]")

    @classmethod
    def check_all_dependencies(cls) -> list[DependencyCheck]:
        """Check all required and optional dependencies."""
        results = []

        for dep in cls.REQUIRED_DEPENDENCIES:
            results.append(cls.check_command(dep))

        for dep in cls.OPTIONAL_DEPENDENCIES:
            results.append(cls.check_command(dep))

        return results

    @classmethod
    def check_required_dependencies(cls) -> list[DependencyCheck]:
        """Check only required dependencies."""
        return [cls.check_command(dep) for dep in cls.REQUIRED_DEPENDENCIES]

    @classmethod
    def validate_dependencies(cls, show_details: bool = True, check_r_packages: bool = True, r_path: str | None = None) -> bool:
        """Validate all required dependencies and show results."""
        checks = cls.check_required_dependencies()
        missing_deps = [check for check in checks if not check.available]

        if show_details:
            cls.display_dependency_status(checks)

        if missing_deps:
            if show_details:
                cls.display_installation_instructions(missing_deps)

        # Check R packages even if other dependencies are missing, but only if R is available
        r_available = any(check.name == "R" and check.available for check in checks)
        if check_r_packages and r_available and r_path:
            console.print("\n" + "=" * 50)
            r_packages_valid = cls.validate_r_packages(r_path, interactive=True)
            if not r_packages_valid:
                return False

        # Return False if any system dependencies are missing
        if missing_deps:
            return False

        return True

    @staticmethod
    def display_dependency_status(checks: list[DependencyCheck]):
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
    def display_installation_instructions(missing_deps: list[DependencyCheck]):
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

            elif dep.name == "fastq-dump":
                console.print("  Installation: Install SRA Toolkit")
                console.print("  - macOS: brew install sratoolkit")
                console.print("  - Ubuntu/Debian: sudo apt-get install sra-toolkit")
                console.print("  - Or download from: https://github.com/ncbi/sra-tools\n")

        console.print("[yellow]Please install the missing dependencies before proceeding.[/yellow]")

    @staticmethod
    def get_conda_micromamba_r_installations() -> list[tuple]:
        """Get R installations from conda/micromamba environments."""
        installations = []

        # Check for micromamba
        micromamba_paths = ["/home/yuyasato/.local/bin/micromamba", shutil.which("micromamba")]

        for micromamba_path in micromamba_paths:
            if micromamba_path and os.path.exists(micromamba_path):
                try:
                    # Get list of environments
                    result = subprocess.run([micromamba_path, "env", "list"], check=False, capture_output=True, text=True, timeout=15)
                    if result.returncode == 0:
                        lines = result.stdout.strip().split("\n")
                        for line in lines:
                            # Skip header and empty lines
                            if line.strip() and not line.startswith("Name") and "──" not in line:
                                parts = line.strip().split()
                                if len(parts) >= 1:  # At least path
                                    # Handle cases where environment name might be empty (first line with just path)
                                    if len(parts) == 1:
                                        # This is a path without environment name, skip it
                                        continue

                                    env_name = parts[0]
                                    env_path = parts[-1]  # Last part is the path

                                    # Skip if path doesn't look like an environment path
                                    if not ("/envs/" in env_path or env_path.endswith("micromamba")):
                                        continue

                                    r_executable = os.path.join(env_path, "bin", "R")
                                    if os.path.exists(r_executable):
                                        # Get R version
                                        try:
                                            version_result = subprocess.run([r_executable, "--version"], check=False, capture_output=True, text=True, timeout=10)
                                            version = "Unknown"
                                            if version_result.returncode == 0:
                                                for v_line in version_result.stdout.split("\n"):
                                                    if "R version" in v_line:
                                                        version = v_line.split()[2]
                                                        break
                                            installations.append((f"micromamba:{env_name}", version, r_executable))
                                        except:
                                            installations.append((f"micromamba:{env_name}", "Unknown", r_executable))
                except (subprocess.SubprocessError, subprocess.TimeoutExpired):
                    continue
                break  # Found working micromamba, no need to try others

        # Check for conda
        conda_paths = ["/home/yuyasato/work3/opt/mambaforge/condabin/conda", shutil.which("conda")]

        for conda_path in conda_paths:
            if conda_path and os.path.exists(conda_path):
                try:
                    # Get list of environments
                    result = subprocess.run([conda_path, "env", "list"], check=False, capture_output=True, text=True, timeout=15)
                    if result.returncode == 0:
                        lines = result.stdout.strip().split("\n")
                        for line in lines:
                            # Skip header and empty lines, look for environment paths
                            if line.strip() and not line.startswith("#") and "/envs/" in line:
                                parts = line.strip().split()
                                if len(parts) >= 2:
                                    env_name = parts[0]
                                    env_path = parts[-1]  # Last part is the path
                                    r_executable = os.path.join(env_path, "bin", "R")
                                    if os.path.exists(r_executable):
                                        # Get R version
                                        try:
                                            version_result = subprocess.run([r_executable, "--version"], check=False, capture_output=True, text=True, timeout=10)
                                            version = "Unknown"
                                            if version_result.returncode == 0:
                                                for v_line in version_result.stdout.split("\n"):
                                                    if "R version" in v_line:
                                                        version = v_line.split()[2]
                                                        break
                                            installations.append((f"conda:{env_name}", version, r_executable))
                                        except:
                                            installations.append((f"conda:{env_name}", "Unknown", r_executable))
                except (subprocess.SubprocessError, subprocess.TimeoutExpired):
                    continue
                break  # Found working conda, no need to try others

        return installations

    @staticmethod
    def get_rig_installations() -> list[tuple]:
        """Get R installations managed by rig."""
        installations = []

        try:
            result = subprocess.run(["rig", "list"], check=False, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                for line in lines:
                    if line.strip() and not line.startswith("*"):
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
    def create_rig_environment(r_version: str = "release") -> str | None:
        """Create a new R environment using rig."""
        console.print(f"[cyan]Creating R environment with rig (version: {r_version})...[/cyan]")

        try:
            # Install the R version if not already installed
            console.print(f"[cyan]Installing R {r_version}...[/cyan]")

            # Use rig add without sudo - rig handles user installations
            cmd = ["rig", "add", r_version]
            console.print(f"[dim]Running: {' '.join(cmd)}[/dim]")

            # Run with real-time output
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, universal_newlines=True)

            # Show real-time output
            output_lines = []
            while True:
                output = process.stdout.readline()
                if output == "" and process.poll() is not None:
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
            list_result = subprocess.run(["rig", "list"], check=False, capture_output=True, text=True, timeout=10)

            if list_result.returncode == 0:
                lines = list_result.stdout.strip().split("\n")
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
    def install_r_packages_with_rig(r_path: str, packages: list[str]) -> bool:
        """Install R packages using the rig-managed R installation."""
        console.print(f"[cyan]Installing R packages with rig-managed R: {', '.join(packages)}[/cyan]")

        try:
            # Create R script for package installation
            packages_str = '", "'.join(packages)
            r_script = f"""
            # Install pacman if not available
            if (!require("pak", quietly = TRUE)) {{
                install.packages("pak", repos = "https://cloud.r-project.org/")
            }}

            # Install packages using pak (faster than install.packages)
            pak::pkg_install(c("{packages_str}"))
            """

            console.print("[cyan]Installing packages (this may take several minutes)...[/cyan]")
            result = subprocess.run(
                [r_path, "--slave", "--vanilla", "-e", r_script],
                check=False,
                capture_output=True,
                text=True,
                timeout=1800,  # 30 minutes timeout
            )

            if result.returncode == 0:
                console.print("[green]Successfully installed R packages![/green]")
                return True
            console.print(f"[red]Failed to install R packages: {result.stderr}[/red]")
            return False

        except subprocess.TimeoutExpired:
            console.print("[red]Package installation timed out[/red]")
            return False
        except Exception as e:
            console.print(f"[red]Error during package installation: {e}[/red]")
            return False

    @staticmethod
    def select_r_installation() -> str | None:
        """Interactive R installation selection."""
        console.print("\n[cyan]Selecting R installation...[/cyan]")

        # Get current R path
        current_r = shutil.which("R")

        # Create choices for inquirer
        choices = []

        # Store full paths for later use
        choice_to_path = {}

        if current_r:
            # Get version info for current R
            try:
                result = subprocess.run([current_r, "--version"], check=False, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    version = "Unknown"
                    for line in lines:
                        if "R version" in line:
                            version = line.split()[2]
                            break
                    current_choice = f"System R (R {version})"
                    choices.append(current_choice)
                    choice_to_path[current_choice] = current_r
                else:
                    current_choice = "System R"
                    choices.append(current_choice)
                    choice_to_path[current_choice] = current_r
            except:
                current_choice = "System R"
                choices.append(current_choice)
                choice_to_path[current_choice] = current_r

        # Get conda/micromamba R installations
        conda_installations = DependencyValidator.get_conda_micromamba_r_installations()
        for env_name, version, r_path in conda_installations:
            choice_key = f"{env_name} (R {version})"
            choices.append(choice_key)
            choice_to_path[choice_key] = r_path

        # Get rig installations
        rig_installations = DependencyValidator.get_rig_installations()
        for version, r_path in rig_installations:
            choice_key = f"rig R {version}"
            choices.append(choice_key)
            choice_to_path[choice_key] = r_path

        choices.append("Enter custom R path manually")

        # Use inquirer for selection with simplified interface
        questions = [inquirer.List("r_selection", message="Select R installation to use", choices=choices)]

        try:
            result = inquirer.prompt(questions, raise_keyboard_interrupt=True)
            if result is None:
                return None

            selection = result["r_selection"]

            if selection == "Enter custom R path manually":
                # Manual path input
                manual_questions = [inquirer.Path("r_path", message="Enter the full path to R executable", path_type=inquirer.Path.FILE)]
                manual_result = inquirer.prompt(manual_questions, raise_keyboard_interrupt=True)
                if manual_result is None:
                    return None

                manual_path = manual_result["r_path"]

                # Validate the manual path
                if os.path.exists(manual_path) and os.access(manual_path, os.X_OK):
                    console.print(f"[green]Selected R: {manual_path}[/green]")
                    return manual_path
                console.print(f"[red]Invalid R path: {manual_path}[/red]")
                return None
            # Use the mapping to get the actual path
            r_path = choice_to_path.get(selection)
            if r_path and os.path.exists(r_path):
                console.print(f"[green]Selected R: {selection} -> {r_path}[/green]")
                return r_path
            console.print(f"[red]Could not find R path for selection: {selection}[/red]")
            return None

        except KeyboardInterrupt:
            console.print("\n[yellow]R selection cancelled.[/yellow]")
            return None

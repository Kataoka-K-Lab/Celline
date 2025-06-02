import argparse
import os
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from celline.functions._base import CellineFunction
from celline.log.logger import get_logger

if TYPE_CHECKING:
    from celline import Project

console = Console()
logger = get_logger(__name__)


class Interactive(CellineFunction):
    """Launch interactive web interface for Celline."""

    def __init__(self, host: str = "localhost", port: int = 3000, auto_open: bool = True) -> None:
        """Initialize Interactive function.
        
        Args:
            host (str): Host to bind the server to. Defaults to "localhost".
            port (int): Port to run the server on. Defaults to 3000.
            auto_open (bool): Whether to automatically open browser. Defaults to True.
        """
        self.host = host
        self.port = port
        self.auto_open = auto_open
        self.process: Optional[subprocess.Popen] = None

    def register(self) -> str:
        return "interactive"

    def _get_frontend_path(self) -> Path:
        """Get the path to the frontend directory."""
        # First try the existing Vue.js frontend in src/celline/frontend
        current_file = Path(__file__).parent.parent
        vue_frontend = current_file / "frontend"
        
        if vue_frontend.exists():
            return vue_frontend
            
        # Fallback to project root frontend directory
        current_dir = Path.cwd()
        frontend_path = current_dir / "frontend"
        
        if not frontend_path.exists():
            # If not found in current directory, look relative to this file
            from celline.config import Config
            project_root = Path(Config.PROJ_ROOT) if hasattr(Config, 'PROJ_ROOT') else current_dir
            frontend_path = project_root / "frontend"
            
        return frontend_path

    def _check_node_installed(self) -> bool:
        """Check if Node.js is installed."""
        try:
            result = subprocess.run(["node", "--version"], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _check_npm_installed(self) -> bool:
        """Check if npm is installed."""
        try:
            result = subprocess.run(["npm", "--version"], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _check_vue_cli_installed(self) -> bool:
        """Check if Vue CLI is installed globally."""
        try:
            result = subprocess.run(["vue", "--version"], capture_output=True, text=True)
            return result.returncode == 0
        except FileNotFoundError:
            return False

    def _install_vue_cli_globally(self) -> bool:
        """Install Vue CLI globally."""
        try:
            console.print("[dim]  ├─ Installing Vue CLI globally...[/dim]")
            
            process = subprocess.Popen(
                ["npm", "install", "-g", "@vue/cli"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    line = output.strip()
                    if line:
                        if 'added' in line.lower() or 'changed' in line.lower():
                            console.print(f"[dim]  │  [green]{line}[/green][/dim]")
                        elif 'warn' in line.lower():
                            console.print(f"[dim]  │  [yellow]{line}[/yellow][/dim]")
                        elif 'error' in line.lower():
                            console.print(f"[dim]  │  [red]{line}[/red][/dim]")
                        else:
                            console.print(f"[dim]  │  {line}[/dim]")
            
            return_code = process.wait()
            if return_code == 0:
                console.print("[dim]  ├─ [green]✓ Vue CLI installed successfully[/green][/dim]")
                return True
            else:
                console.print("[dim]  ├─ [red]Failed to install Vue CLI[/red][/dim]")
                return False
                
        except Exception as e:
            console.print(f"[dim]  ├─ [red]Error installing Vue CLI: {str(e)}[/red][/dim]")
            return False

    def _create_vue_project(self, frontend_path: Path) -> bool:
        """Create a new Vue.js project if it doesn't exist."""
        try:
            console.print("[dim]  ├─ Creating Vue.js project with TypeScript...[/dim]")
            
            # Create parent directory if it doesn't exist
            frontend_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Create a manual preset file for TypeScript
            preset_content = {
                "useConfigFiles": True,
                "cssPreprocessor": "node-sass",
                "plugins": {
                    "@vue/cli-plugin-babel": {},
                    "@vue/cli-plugin-typescript": {
                        "classComponent": False,
                        "useTsWithBabel": True
                    },
                    "@vue/cli-plugin-eslint": {
                        "config": "typescript",
                        "lintOn": ["save"]
                    }
                }
            }
            
            import json
            preset_path = frontend_path.parent / "vue-preset.json"
            with open(preset_path, 'w') as f:
                json.dump(preset_content, f, indent=2)
            
            # Vue create command with TypeScript preset
            process = subprocess.Popen(
                ["vue", "create", frontend_path.name, "--preset", str(preset_path), "--packageManager", "npm"],
                cwd=frontend_path.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    line = output.strip()
                    if line:
                        if 'successfully' in line.lower() or 'created' in line.lower():
                            console.print(f"[dim]  │  [green]{line}[/green][/dim]")
                        elif 'installing' in line.lower() or 'invoking' in line.lower():
                            console.print(f"[dim]  │  [cyan]{line}[/cyan][/dim]")
                        else:
                            console.print(f"[dim]  │  {line}[/dim]")
            
            return_code = process.wait()
            
            # Clean up preset file
            if preset_path.exists():
                preset_path.unlink()
            
            if return_code == 0:
                console.print("[dim]  ├─ [green]✓ Vue.js project created successfully[/green][/dim]")
                
                # Setup TypeScript configuration
                self._create_typescript_config(frontend_path)
                
                # Copy our enhanced App.vue to the new project
                self._setup_celline_frontend(frontend_path)
                return True
            else:
                console.print("[dim]  ├─ [red]Failed to create Vue.js project[/red][/dim]")
                # Fallback to simple project creation
                return self._create_simple_vue_project(frontend_path)
                
        except Exception as e:
            console.print(f"[dim]  ├─ [red]Error creating Vue.js project: {str(e)}[/red][/dim]")
            # Fallback to simple project creation
            return self._create_simple_vue_project(frontend_path)

    def _create_simple_vue_project(self, frontend_path: Path) -> bool:
        """Create a simple Vue.js project as fallback."""
        try:
            console.print("[dim]  ├─ Creating simple Vue.js project...[/dim]")
            
            process = subprocess.Popen(
                ["vue", "create", frontend_path.name, "--preset", "default", "--packageManager", "npm"],
                cwd=frontend_path.parent,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    line = output.strip()
                    if line:
                        console.print(f"[dim]  │  {line}[/dim]")
            
            return_code = process.wait()
            if return_code == 0:
                console.print("[dim]  ├─ [green]✓ Simple Vue.js project created[/green][/dim]")
                
                # Setup TypeScript configuration manually
                self._create_typescript_config(frontend_path)
                self._setup_celline_frontend(frontend_path)
                return True
            else:
                console.print("[dim]  ├─ [red]Failed to create simple Vue.js project[/red][/dim]")
                return False
                
        except Exception as e:
            console.print(f"[dim]  ├─ [red]Error creating simple Vue.js project: {str(e)}[/red][/dim]")
            return False

    def _create_typescript_config(self, frontend_path: Path) -> None:
        """Create TypeScript configuration file."""
        try:
            ts_config = {
                "compilerOptions": {
                    "target": "ES2020",
                    "useDefineForClassFields": True,
                    "lib": ["ES2020", "DOM", "DOM.Iterable"],
                    "module": "ESNext",
                    "skipLibCheck": True,
                    "moduleResolution": "bundler",
                    "allowImportingTsExtensions": True,
                    "resolveJsonModule": True,
                    "isolatedModules": True,
                    "noEmit": True,
                    "jsx": "preserve",
                    "strict": True,
                    "noUnusedLocals": True,
                    "noUnusedParameters": True,
                    "noFallthroughCasesInSwitch": True
                },
                "include": ["src/**/*.ts", "src/**/*.d.ts", "src/**/*.tsx", "src/**/*.vue"],
                "references": [{"path": "./tsconfig.node.json"}]
            }
            
            import json
            ts_config_path = frontend_path / "tsconfig.json"
            with open(ts_config_path, 'w') as f:
                json.dump(ts_config, f, indent=2)
            
            console.print("[dim]  │  [green]✓ Created TypeScript configuration[/green][/dim]")
            
        except Exception as e:
            console.print(f"[dim]  │  [yellow]Warning: Could not create TypeScript config: {str(e)}[/yellow][/dim]")

    def _setup_celline_frontend(self, frontend_path: Path) -> None:
        """Setup Celline-specific frontend files."""
        try:
            console.print("[dim]  ├─ Setting up Celline frontend files...[/dim]")
            
            # Update package.json to support TypeScript properly
            self._update_package_json(frontend_path)
            
            # Update ESLint configuration
            self._update_eslint_config(frontend_path)
            
            # Read the enhanced App.vue from our existing frontend
            existing_frontend = Path(__file__).parent.parent / "frontend"
            if existing_frontend.exists():
                app_vue_source = existing_frontend / "src" / "App.vue"
                if app_vue_source.exists():
                    app_vue_target = frontend_path / "src" / "App.vue"
                    
                    import shutil
                    shutil.copy2(app_vue_source, app_vue_target)
                    console.print("[dim]  │  [green]✓ Copied enhanced App.vue[/green][/dim]")
            
            # Remove problematic template.vue if it exists
            template_vue = frontend_path / "template.vue"
            if template_vue.exists():
                template_vue.unlink()
                console.print("[dim]  │  [green]✓ Removed problematic template.vue[/green][/dim]")
                    
        except Exception as e:
            console.print(f"[dim]  │  [yellow]Warning: Could not setup Celline files: {str(e)}[/yellow][/dim]")

    def _update_package_json(self, frontend_path: Path) -> None:
        """Update package.json to include TypeScript and modern dependencies."""
        try:
            import json
            
            package_json_path = frontend_path / "package.json"
            if package_json_path.exists():
                with open(package_json_path, 'r') as f:
                    package_data = json.load(f)
                
                # Update dependencies and devDependencies
                package_data.setdefault("dependencies", {}).update({
                    "vue": "^3.3.0",
                    "vue-router": "^4.2.0"
                })
                
                package_data.setdefault("devDependencies", {}).update({
                    "@vue/cli-plugin-typescript": "^5.0.0",
                    "typescript": "^5.0.0",
                    "@typescript-eslint/eslint-plugin": "^6.0.0",
                    "@typescript-eslint/parser": "^6.0.0"
                })
                
                # Update ESLint config in package.json
                if "eslintConfig" in package_data:
                    package_data["eslintConfig"]["extends"] = [
                        "plugin:vue/vue3-essential",
                        "@vue/typescript/recommended"
                    ]
                    package_data["eslintConfig"]["parser"] = "@typescript-eslint/parser"
                    package_data["eslintConfig"]["parserOptions"] = {
                        "ecmaVersion": 2020,
                        "sourceType": "module"
                    }
                
                with open(package_json_path, 'w') as f:
                    json.dump(package_data, f, indent=2)
                
                console.print("[dim]  │  [green]✓ Updated package.json for TypeScript support[/green][/dim]")
                    
        except Exception as e:
            console.print(f"[dim]  │  [yellow]Warning: Could not update package.json: {str(e)}[/yellow][/dim]")

    def _update_eslint_config(self, frontend_path: Path) -> None:
        """Create or update ESLint configuration file."""
        try:
            import json
            
            eslint_config = {
                "root": True,
                "env": {
                    "node": True,
                    "browser": True,
                    "es2021": True
                },
                "extends": [
                    "plugin:vue/vue3-essential",
                    "@vue/typescript/recommended"
                ],
                "parserOptions": {
                    "ecmaVersion": 2020,
                    "sourceType": "module",
                    "parser": "@typescript-eslint/parser"
                },
                "rules": {
                    "@typescript-eslint/no-explicit-any": "off",
                    "@typescript-eslint/no-unused-vars": "off",
                    "@typescript-eslint/interface-name-prefix": "off",
                    "vue/multi-word-component-names": "off"
                }
            }
            
            # Write .eslintrc.json
            eslint_path = frontend_path / ".eslintrc.json"
            with open(eslint_path, 'w') as f:
                json.dump(eslint_config, f, indent=2)
            
            console.print("[dim]  │  [green]✓ Created ESLint configuration[/green][/dim]")
            
        except Exception as e:
            console.print(f"[dim]  │  [yellow]Warning: Could not update ESLint config: {str(e)}[/yellow][/dim]")

    def _clean_npm_cache(self) -> bool:
        """Clean npm cache to resolve dependency issues."""
        try:
            console.print("[dim]  ├─ Cleaning npm cache...[/dim]")
            result = subprocess.run(["npm", "cache", "clean", "--force"], capture_output=True, text=True)
            if result.returncode == 0:
                console.print("[dim]  │  [green]✓ npm cache cleaned[/green][/dim]")
                return True
            else:
                console.print("[dim]  │  [yellow]Warning: Could not clean npm cache[/yellow][/dim]")
                return False
        except Exception as e:
            console.print(f"[dim]  │  [yellow]Warning: npm cache clean failed: {str(e)}[/yellow][/dim]")
            return False

    def _fix_package_lock(self, frontend_path: Path) -> bool:
        """Remove package-lock.json and node_modules to fix dependency issues."""
        try:
            console.print("[dim]  ├─ Fixing dependency conflicts...[/dim]")
            
            # Remove package-lock.json
            package_lock = frontend_path / "package-lock.json"
            if package_lock.exists():
                package_lock.unlink()
                console.print("[dim]  │  [green]✓ Removed package-lock.json[/green][/dim]")
            
            # Remove node_modules
            node_modules = frontend_path / "node_modules"
            if node_modules.exists():
                import shutil
                shutil.rmtree(node_modules)
                console.print("[dim]  │  [green]✓ Removed node_modules[/green][/dim]")
            
            return True
        except Exception as e:
            console.print(f"[dim]  │  [yellow]Warning: Could not clean existing files: {str(e)}[/yellow][/dim]")
            return False

    def _try_install_with_legacy_deps(self, frontend_path: Path) -> bool:
        """Try installing with legacy peer deps flag."""
        try:
            console.print("[dim]  ├─ Trying install with legacy peer deps...[/dim]")
            
            process = subprocess.Popen(
                ["npm", "install", "--legacy-peer-deps"],
                cwd=frontend_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    line = output.strip()
                    if line:
                        if 'added' in line.lower() or 'packages' in line.lower():
                            console.print(f"[dim]  │  [green]{line}[/green][/dim]")
                        elif 'warn' in line.lower():
                            console.print(f"[dim]  │  [yellow]{line}[/yellow][/dim]")
                        elif 'error' in line.lower():
                            console.print(f"[dim]  │  [red]{line}[/red][/dim]")
                        else:
                            console.print(f"[dim]  │  {line}[/dim]")
            
            return_code = process.wait()
            return return_code == 0
            
        except Exception as e:
            console.print(f"[dim]  │  [red]Legacy install failed: {str(e)}[/red][/dim]")
            return False

    def _install_dependencies(self, frontend_path: Path) -> bool:
        """Install frontend dependencies."""
        try:
            console.print("[cyan]Setting up frontend environment...[/cyan]")
            
            # Check if project structure exists
            package_json = frontend_path / "package.json"
            if not package_json.exists():
                console.print("[dim]  ├─ No existing Vue.js project found[/dim]")
                
                # Check if Vue CLI is installed
                if not self._check_vue_cli_installed():
                    console.print("[dim]  ├─ Vue CLI not found, installing globally...[/dim]")
                    if not self._install_vue_cli_globally():
                        return False
                
                # Create new Vue.js project
                if not self._create_vue_project(frontend_path):
                    return False
            else:
                console.print("[dim]  ├─ Found existing Vue.js project[/dim]")
            
            # Install dependencies with error recovery
            console.print("[dim]  ├─ Installing dependencies...[/dim]")
            
            # First, try normal install
            success = self._try_npm_install(frontend_path)
            
            if not success:
                console.print("[dim]  ├─ [yellow]Normal install failed, trying recovery methods...[/yellow][/dim]")
                
                # Clean npm cache
                self._clean_npm_cache()
                
                # Fix package lock issues
                self._fix_package_lock(frontend_path)
                
                # Try with legacy peer deps
                success = self._try_install_with_legacy_deps(frontend_path)
                
                if not success:
                    console.print("[dim]  ├─ [yellow]Legacy install failed, creating fresh project...[/yellow][/dim]")
                    
                    # Remove the problematic frontend and create fresh
                    if frontend_path.exists():
                        import shutil
                        shutil.rmtree(frontend_path)
                    
                    # Create new Vue.js project
                    if not self._create_vue_project(frontend_path):
                        return False
                    
                    # Try installing again
                    success = self._try_npm_install(frontend_path)
            
            if success:
                console.print("[dim]  └─ [green]✓ Frontend environment ready[/green][/dim]")
                return True
            else:
                console.print("[dim]  └─ [red]Failed to setup frontend environment[/red][/dim]")
                return False
                
        except Exception as e:
            console.print(f"[dim]  └─ [red]Error setting up frontend: {str(e)}[/red][/dim]")
            return False

    def _try_npm_install(self, frontend_path: Path) -> bool:
        """Try npm install and return success status."""
        try:
            # Start the process with real-time output
            process = subprocess.Popen(
                ["npm", "install"],
                cwd=frontend_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Read output line by line and display with prefix
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    # Clean and display the output with nested formatting
                    line = output.strip()
                    if line:
                        # Skip some verbose npm output
                        if any(skip in line.lower() for skip in ['npm warn', 'npm notice', 'deprecated']):
                            console.print(f"[dim]  │  [yellow]{line}[/yellow][/dim]")
                        elif 'added' in line.lower() or 'packages' in line.lower():
                            console.print(f"[dim]  │  [green]{line}[/green][/dim]")
                        elif 'error' in line.lower() or 'err!' in line.lower():
                            console.print(f"[dim]  │  [red]{line}[/red][/dim]")
                        else:
                            console.print(f"[dim]  │  {line}[/dim]")
            
            # Wait for process to complete
            return_code = process.wait()
            return return_code == 0
            
        except Exception as e:
            console.print(f"[dim]  │  [red]npm install error: {str(e)}[/red][/dim]")
            return False

    def _start_frontend_server(self, frontend_path: Path) -> bool:
        """Start the Vue.js frontend server."""
        try:
            console.print(f"[cyan]Starting Vue.js server on {self.host}:{self.port}...[/cyan]")
            console.print("[dim]  ├─ Setting up environment...[/dim]")
            
            # Set environment variables
            env = os.environ.copy()
            env["HOST"] = self.host
            env["PORT"] = str(self.port)
            
            console.print("[dim]  ├─ Launching vue-cli-service serve...[/dim]")
            
            # Start the Vue.js development server (vue-cli-service serve)
            self.process = subprocess.Popen(
                ["npm", "run", "serve"],
                cwd=frontend_path,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Monitor startup output for a few seconds
            logger.info("Waiting for Vue.js server to start...")
            console.print("[dim]  ├─ Monitoring startup output...[/dim]")
            
            startup_timeout = 10  # seconds
            start_time = time.time()
            server_ready = False
            
            while time.time() - start_time < startup_timeout:
                # Check if process is still running
                if self.process.poll() is not None:
                    # Process died, get error output
                    stdout, _ = self.process.communicate()
                    console.print("[dim]  └─ [red]Frontend server failed to start[/red][/dim]")
                    if stdout:
                        console.print(f"[dim]     [red]Error: {stdout.strip()}[/red][/dim]")
                    return False
                
                # Read any available output
                try:
                    # Non-blocking read with a short timeout
                    import select
                    import sys
                    
                    if sys.platform != 'win32':
                        ready, _, _ = select.select([self.process.stdout], [], [], 0.1)
                        if ready:
                            line = self.process.stdout.readline()
                            if line:
                                line = line.strip()
                                if line:
                                    if 'local:' in line.lower() or 'network:' in line.lower():
                                        console.print(f"[dim]  │  [green]{line}[/green][/dim]")
                                        server_ready = True
                                    elif 'compiled' in line.lower() and 'successfully' in line.lower():
                                        console.print(f"[dim]  │  [green]{line}[/green][/dim]")
                                        server_ready = True
                                    elif 'error' in line.lower() or 'failed' in line.lower():
                                        console.print(f"[dim]  │  [red]{line}[/red][/dim]")
                                    else:
                                        console.print(f"[dim]  │  {line}[/dim]")
                    else:
                        # Windows fallback - just wait
                        time.sleep(0.5)
                        server_ready = True  # Assume it's ready after timeout
                        
                except (ImportError, OSError):
                    # Fallback for systems without select
                    time.sleep(0.5)
                    server_ready = True
                    
                if server_ready:
                    break
                    
                time.sleep(0.5)
            
            # Final check if process is still running
            if self.process.poll() is None:
                console.print("[dim]  └─ [green]✓ Frontend server started successfully[/green][/dim]")
                console.print(f"[blue]Server running at: http://{self.host}:{self.port}[/blue]")
                
                if self.auto_open:
                    console.print("[dim]     ├─ Opening browser...[/dim]")
                    time.sleep(1)  # Give server a moment to fully start
                    try:
                        webbrowser.open(f"http://{self.host}:{self.port}")
                        console.print("[dim]     └─ [green]✓ Browser opened automatically[/green][/dim]")
                    except Exception as e:
                        logger.warning(f"Could not open browser automatically: {e}")
                        console.print(f"[dim]     └─ [yellow]⚠ Please open http://{self.host}:{self.port} in your browser[/yellow][/dim]")
                
                return True
            else:
                console.print("[dim]  └─ [red]Frontend server process terminated[/red][/dim]")
                return False
                
        except Exception as e:
            console.print(f"[dim]  └─ [red]Error starting frontend server: {str(e)}[/red][/dim]")
            return False

    def _wait_for_shutdown(self):
        """Wait for user to stop the server."""
        try:
            console.print("\n[yellow]Press Ctrl+C to stop the server[/yellow]")
            
            # Wait for the process or keyboard interrupt
            while self.process and self.process.poll() is None:
                time.sleep(1)
                
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopping server...[/yellow]")
            self._stop_server()
        except Exception as e:
            logger.error(f"Error in wait_for_shutdown: {e}")
            self._stop_server()

    def _stop_server(self):
        """Stop the frontend server."""
        if self.process:
            try:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
                console.print("[green]✓ Server stopped[/green]")
            except Exception as e:
                logger.error(f"Error stopping server: {e}")
                console.print(f"[red]Error stopping server: {e}[/red]")
            finally:
                self.process = None

    def call(self, project: "Project") -> "Project":
        """Launch the interactive web interface.
        
        Args:
            project: The current project instance.
            
        Returns:
            The project instance.
        """
        logger.info("Starting interactive web interface")
        
        # Display welcome panel
        welcome_text = Text()
        welcome_text.append("Celline Interactive Web Interface\n", style="bold blue")
        welcome_text.append("Vue.js Frontend with Sample Management\n\n", style="cyan")
        welcome_text.append(f"Starting server on: ", style="white")
        welcome_text.append(f"http://{self.host}:{self.port}", style="bold cyan")
        
        console.print(Panel(welcome_text, title="🚀 Interactive Mode", border_style="blue"))
        
        # Check prerequisites
        frontend_path = self._get_frontend_path()
        
        if not frontend_path.exists():
            console.print(f"[yellow]Frontend directory not found at: {frontend_path}[/yellow]")
            console.print("[cyan]Will create a new Vue.js project automatically...[/cyan]")
            
        if not self._check_node_installed():
            console.print("[red]Node.js is not installed. Please install Node.js to use interactive mode.[/red]")
            return project
            
        if not self._check_npm_installed():
            console.print("[red]npm is not installed. Please install npm to use interactive mode.[/red]")
            return project
        
        # Setup frontend environment (will create project if needed)
        if not self._install_dependencies(frontend_path):
            return project
        
        # Start the server
        if self._start_frontend_server(frontend_path):
            try:
                self._wait_for_shutdown()
            finally:
                self._stop_server()
        
        return project

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Interactive function."""
        parser.add_argument(
            '--host',
            default='localhost',
            help='Host to bind the server to (default: localhost)'
        )
        parser.add_argument(
            '--port', '-p',
            type=int,
            default=3000,
            help='Port to run the server on (default: 3000)'
        )
        parser.add_argument(
            '--no-open',
            action='store_true',
            help='Do not automatically open browser'
        )

    def cli(self, project: "Project", args: Optional[argparse.Namespace] = None) -> "Project":
        """CLI entry point for Interactive function."""
        if args is None:
            # Use defaults
            interactive = Interactive()
        else:
            # Use getattr with defaults to handle missing attributes
            host = getattr(args, 'host', 'localhost')
            port = getattr(args, 'port', 3000)
            no_open = getattr(args, 'no_open', False)
            
            interactive = Interactive(
                host=host,
                port=port,
                auto_open=not no_open
            )
        
        return interactive.call(project)

    def get_description(self) -> str:
        """Get description for CLI help."""
        return """Launch interactive web interface for Celline.
        
This starts a Vue.js web application that provides a graphical interface
for managing projects, samples, and running analysis workflows."""

    def get_usage_examples(self) -> list[str]:
        """Get usage examples for CLI help."""
        return [
            "celline run interactive",
            "celline run interactive --port 8080",
            "celline run interactive --host 0.0.0.0 --port 3000",
            "celline run interactive --no-open"
        ]

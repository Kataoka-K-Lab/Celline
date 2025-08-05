"""
Function registry for discovering and managing CellineFunction classes.
"""

import inspect
import importlib
import importlib.util
import pkgutil
import os
import sys
from pathlib import Path
from typing import Dict, List, Type, Optional
from dataclasses import dataclass

from celline.functions._base import CellineFunction


@dataclass
class FunctionInfo:
    """Information about a discovered CellineFunction."""
    name: str
    class_name: str
    module_path: str
    description: str
    class_ref: Type[CellineFunction]
    is_custom: bool = False  # Flag to indicate if this is a custom user function


class FunctionRegistry:
    """Registry for discovering and managing CellineFunction implementations."""
    
    def __init__(self):
        self._functions: Dict[str, FunctionInfo] = {}
        self._discovered = False
        self._lazy_discovery = True  # Enable lazy discovery by default
    
    def discover_functions(self) -> None:
        """Discover all CellineFunction implementations in the functions package and custom functions."""
        if self._discovered:
            return
        
        # Import rich for progress display
        try:
            from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn
            from rich.console import Console
            use_rich = True
            console = Console()
        except ImportError:
            use_rich = False
        
        if use_rich:
            # Show initial search message
            console.print("🔍 [dim]Searching for functions...[/dim]")
            
            # Create rich progress display
            with Progress(
                SpinnerColumn(),
                TextColumn("[bold blue]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeElapsedColumn(),
                console=console,
                transient=True,  # Remove progress bar when complete
                refresh_per_second=10  # Smooth animation
            ) as progress:
                # Estimate total steps based on typical module counts
                import celline.functions as functions_package
                modules_to_process = []
                for importer, modname, ispkg in pkgutil.iter_modules(functions_package.__path__, functions_package.__name__ + "."):
                    if not modname.endswith('._base') and not modname.endswith('.vcount'):
                        modules_to_process.append(modname)
                
                # Check for custom functions
                custom_count = 0
                try:
                    from celline.config import Config, Setting
                    if hasattr(Config, 'PROJ_ROOT') and Config.PROJ_ROOT:
                        custom_dir = getattr(Setting, 'custom_functions_dir', 'functions')
                        custom_functions_path = Path(Config.PROJ_ROOT) / custom_dir
                        if custom_functions_path.exists():
                            custom_count = len([f for f in custom_functions_path.glob('*.py') if not f.name.startswith('_')])
                except:
                    pass
                
                total_modules = len(modules_to_process) + custom_count
                main_task = progress.add_task("🚀 Discovering functions", total=total_modules)
                
                # Pass progress context to discovery functions
                self._discover_builtin_functions(progress, main_task)
                self._discover_custom_functions(progress, main_task)
        else:
            # Fallback without progress bars
            self._discover_builtin_functions()
            self._discover_custom_functions()
        
        self._discovered = True
    
    def _discover_builtin_functions(self, progress=None, task_id=None) -> None:
        """Discover built-in CellineFunction implementations in the functions package."""
        import celline.functions as functions_package
        
        # Get the package path
        package_path = functions_package.__path__
        
        # Collect all module names first
        modules_to_process = []
        for importer, modname, ispkg in pkgutil.iter_modules(package_path, functions_package.__name__ + "."):
            if modname.endswith('._base') or modname.endswith('.vcount'):  # Skip base and deprecated modules
                continue
            modules_to_process.append(modname)
        
        # Process modules with progress updates
        for modname in modules_to_process:
            if progress and task_id is not None:
                # Update progress description with current module
                module_short_name = modname.split('.')[-1]
                progress.update(task_id, description=f"🔍 {module_short_name}")
            
            try:
                module = importlib.import_module(modname)
                
                # Find all classes in the module that inherit from CellineFunction
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, CellineFunction) and 
                        obj != CellineFunction and
                        obj.__module__ == modname):
                        
                        function_info = self._create_function_info(obj, name, modname, is_custom=False)
                        if function_info:
                            self._functions[function_info.name] = function_info
                            
            except Exception as e:
                # Silently skip modules with missing dependencies
                pass
            
            if progress and task_id is not None:
                progress.advance(task_id)
    
    def _discover_custom_functions(self, progress=None, task_id=None) -> None:
        """Discover custom CellineFunction implementations in the project directory."""
        try:
            from celline.config import Config, Setting
            
            # Check if custom functions are enabled
            if not getattr(Setting, 'enable_custom_functions', True):
                return
            
            # Skip custom function discovery if PROJ_ROOT is not set (CLI startup optimization)
            if not hasattr(Config, 'PROJ_ROOT') or not Config.PROJ_ROOT:
                return
            
            # Get custom functions directory
            custom_dir = getattr(Setting, 'custom_functions_dir', 'functions')
            
            custom_functions_path = Path(Config.PROJ_ROOT) / custom_dir
            
            if not custom_functions_path.exists() or not custom_functions_path.is_dir():
                return  # Custom functions directory doesn't exist
            
            # Add custom functions directory to Python path temporarily
            custom_functions_str = str(custom_functions_path)
            if custom_functions_str not in sys.path:
                sys.path.insert(0, custom_functions_str)
            
            try:
                # Scan all Python files in the custom functions directory
                py_files = [f for f in custom_functions_path.glob('*.py') if not f.name.startswith('_')]
                
                if not py_files:
                    return  # No custom functions to process
                
                # Process custom function files with progress updates
                for py_file in py_files:
                    module_name = py_file.stem
                    
                    if progress and task_id is not None:
                        # Update progress description with current file
                        progress.update(task_id, description=f"📂 {module_name}")
                    
                    try:
                        # Import the custom module
                        if module_name in sys.modules:
                            # Reload if already imported to pick up changes
                            module = importlib.reload(sys.modules[module_name])
                        else:
                            spec = importlib.util.spec_from_file_location(module_name, py_file)
                            if spec and spec.loader:
                                module = importlib.util.module_from_spec(spec)
                                sys.modules[module_name] = module
                                spec.loader.exec_module(module)
                        
                        # Find all classes in the module that inherit from CellineFunction
                        for name, obj in inspect.getmembers(module, inspect.isclass):
                            if (issubclass(obj, CellineFunction) and 
                                obj != CellineFunction and
                                hasattr(obj, '__module__') and
                                obj.__module__ == module_name):
                                
                                function_info = self._create_function_info(
                                    obj, name, f"custom.{module_name}", is_custom=True
                                )
                                if function_info:
                                    # Add custom prefix to avoid conflicts
                                    if not function_info.name.startswith('custom_'):
                                        custom_name = f"custom_{function_info.name}"
                                    else:
                                        custom_name = function_info.name
                                    
                                    # Update the name in function_info
                                    function_info.name = custom_name
                                    self._functions[custom_name] = function_info
                    
                    except Exception as e:
                        # Silently skip problematic custom modules
                        pass
                    
                    if progress and task_id is not None:
                        progress.advance(task_id)
            
            finally:
                # Remove custom functions directory from Python path
                if custom_functions_str in sys.path:
                    sys.path.remove(custom_functions_str)
        
        except Exception as e:
            print(f"Warning: Could not discover custom functions: {e}")
    
    def _create_function_info(self, cls: Type[CellineFunction], class_name: str, module_path: str, is_custom: bool = False) -> Optional[FunctionInfo]:
        """Create FunctionInfo from a class."""
        try:
            # Try to get the register name
            try:
                # For classes with custom register methods
                if hasattr(cls, 'register'):
                    # Try to create a minimal instance to call register
                    temp_instance = cls.__new__(cls)
                    name = temp_instance.register()
                else:
                    name = class_name.lower()
            except:
                # Fallback to class name
                name = class_name.lower()
            
            # Get description from docstring
            description = cls.__doc__ or f"{class_name} function"
            description = description.strip().split('\n')[0]  # First line only
            
            return FunctionInfo(
                name=name,
                class_name=class_name,
                module_path=module_path,
                description=description,
                class_ref=cls,
                is_custom=is_custom
            )
        except Exception as e:
            print(f"Warning: Could not process {class_name}: {e}")
            return None
    
    def get_function(self, name: str) -> Optional[FunctionInfo]:
        """Get function info by name."""
        if not self._discovered:
            # Only discover functions when actually needed
            self.discover_functions()
        return self._functions.get(name)
    
    def list_functions(self) -> List[FunctionInfo]:
        """Get list of all discovered functions."""
        if not self._discovered:
            self.discover_functions()
        return list(self._functions.values())
    
    def get_function_names(self) -> List[str]:
        """Get list of all function names."""
        if not self._discovered:
            self.discover_functions()
        return list(self._functions.keys())


# Global registry instance
_registry = FunctionRegistry()


def get_registry() -> FunctionRegistry:
    """Get the global function registry."""
    return _registry
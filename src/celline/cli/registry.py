"""
Function registry for discovering and managing CellineFunction classes.
"""

import inspect
import importlib
import pkgutil
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


class FunctionRegistry:
    """Registry for discovering and managing CellineFunction implementations."""
    
    def __init__(self):
        self._functions: Dict[str, FunctionInfo] = {}
        self._discovered = False
    
    def discover_functions(self) -> None:
        """Discover all CellineFunction implementations in the functions package."""
        if self._discovered:
            return
            
        import celline.functions as functions_package
        
        # Get the package path
        package_path = functions_package.__path__
        
        # Iterate through all modules in the functions package
        for importer, modname, ispkg in pkgutil.iter_modules(package_path, functions_package.__name__ + "."):
            if modname.endswith('._base') or modname.endswith('.vcount'):  # Skip base and deprecated modules
                continue
                
            try:
                module = importlib.import_module(modname)
                
                # Find all classes in the module that inherit from CellineFunction
                for name, obj in inspect.getmembers(module, inspect.isclass):
                    if (issubclass(obj, CellineFunction) and 
                        obj != CellineFunction and
                        obj.__module__ == modname):
                        
                        function_info = self._create_function_info(obj, name, modname)
                        if function_info:
                            self._functions[function_info.name] = function_info
                            
            except Exception as e:
                print(f"Warning: Could not import {modname}: {e}")
                continue
        
        self._discovered = True
    
    def _create_function_info(self, cls: Type[CellineFunction], class_name: str, module_path: str) -> Optional[FunctionInfo]:
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
                class_ref=cls
            )
        except Exception as e:
            print(f"Warning: Could not process {class_name}: {e}")
            return None
    
    def get_function(self, name: str) -> Optional[FunctionInfo]:
        """Get function info by name."""
        if not self._discovered:
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
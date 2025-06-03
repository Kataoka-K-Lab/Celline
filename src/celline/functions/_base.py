from __future__ import annotations

import argparse
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from celline import Project


class CellineFunction(ABC):
    """Abstract base class for celline functions"""

    def __init__(self, **kwargs) -> None:
        super().__init__()

    def register(self) -> str:
        """Register method - return method name for command"""
        return self.__class__.__name__.lower()

    @abstractmethod
    def call(self, project: "Project"):
        """Abstract method to be implemented by subclasses"""
        pass

    def cli(self, project: "Project", args: Optional[argparse.Namespace] = None) -> "Project":
        """
        CLI entry point for this function.
        Override this method to provide CLI-specific functionality.
        
        Args:
            project: The Project instance
            args: Parsed CLI arguments (if any)
            
        Returns:
            Project: The project instance (for chaining)
        """
        # Default implementation calls the regular call method
        return self.call(project)

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """
        Add CLI arguments specific to this function.
        Override this method to add custom arguments.
        
        Args:
            parser: The ArgumentParser to add arguments to
        """
        pass

    def get_description(self) -> str:
        """
        Get a description of this function for CLI help.
        Override this method to provide a better description.
        
        Returns:
            str: Description of the function
        """
        return self.__doc__ or f"{self.__class__.__name__} function"

    def get_usage_examples(self) -> list[str]:
        """
        Get usage examples for CLI help.
        Override this method to provide usage examples.
        
        Returns:
            list[str]: List of usage example strings
        """
        return []

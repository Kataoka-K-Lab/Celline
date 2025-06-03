import argparse
from typing import Optional
from rich.console import Console

from celline.functions._base import CellineFunction

console = Console()


class Info(CellineFunction):
    def register(self) -> str:
        return "info"

    def call(self, project):
        console.print("[cyan]Project information:[/cyan]")
        console.print(f"Project path: {project.PROJ_PATH}")
        console.print(f"Exec path: {project.EXEC_PATH}")
        return project

    def cli(self, project, args: Optional[argparse.Namespace] = None):
        """CLI entry point for Info function."""
        return self.call(project)

    def get_description(self) -> str:
        return "Display project information and status."

    def get_usage_examples(self) -> list[str]:
        return ["celline run info"]

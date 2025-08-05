def main() -> None:
    """Main entry point for the celline CLI."""
    from celline.cli.main import main as cli_main
    import sys
    sys.exit(cli_main())

# Lazy import Project only when needed
def get_project_class():
    """Get Project class with lazy import."""
    from celline.interfaces import Project
    return Project

# For backward compatibility
Project = None

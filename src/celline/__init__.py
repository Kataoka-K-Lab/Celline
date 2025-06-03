from celline.interfaces import Project


def main() -> None:
    """Main entry point for the celline CLI."""
    from celline.cli.main import main as cli_main
    import sys
    sys.exit(cli_main())

#!/usr/bin/env python3
"""
Main entry point when running celline as a module: python -m celline
"""

from celline.cli.main import main
import sys

if __name__ == '__main__':
    sys.exit(main())
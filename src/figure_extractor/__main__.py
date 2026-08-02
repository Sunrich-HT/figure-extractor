"""Entry point for `python -m figure_extractor`, so the tool runs uninstalled."""
import sys

from .cli import main

sys.exit(main())

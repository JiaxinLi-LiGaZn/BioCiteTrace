"""Run the package command-line interface with ``python -m``."""

# Package import delegates all command parsing and execution to the tested CLI module.
from .cli import main


raise SystemExit(main())

"""Shared import-path setup for repository-local command wrappers."""

# Standard-library imports locate the repository and forward command-line arguments.
from pathlib import Path
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPOSITORY_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))

# Local import occurs after the source tree is made importable without installation.
from citation_use_review.cli import main as workflow_main  # noqa: E402


def run_subcommand(subcommand: str) -> int:
    """Run one CLI subcommand from an uninstalled repository checkout.

    Args:
        subcommand: Citation-review CLI subcommand selected by the wrapper.

    Returns:
        Process exit code from the shared workflow CLI.
    """

    return workflow_main(["--project-root", str(REPOSITORY_ROOT), subcommand, *sys.argv[1:]])

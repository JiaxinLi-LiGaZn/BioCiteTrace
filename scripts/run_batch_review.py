"""Run an ordered manifest of independent one-study review pipelines."""

# Local wrapper import supplies repository path setup and shared CLI behavior.
from _entry import run_subcommand


if __name__ == "__main__":
    raise SystemExit(run_subcommand("run-batch"))

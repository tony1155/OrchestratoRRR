"""Minimal PyInstaller entrypoint that delegates to the formal Typer app."""

from autogame_orchestrator.cli import app

if __name__ == "__main__":
    app()

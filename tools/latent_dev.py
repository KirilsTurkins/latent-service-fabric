#!/usr/bin/env python3
"""Contributor entry point; installed users execute the frozen latent-dev binary."""
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

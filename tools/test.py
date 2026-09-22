#!/usr/bin/env python3
"""Plan, prepare, run, or reproduce one registered LSF test selection."""
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.local_tests import main


if __name__ == "__main__":
    raise SystemExit(main())

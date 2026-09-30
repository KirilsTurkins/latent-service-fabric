#!/usr/bin/env python3
"""Qualification owner for the maintained signed Java/HTTP regression."""
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_http_composition.qualify import main

if __name__ == "__main__":
    main()

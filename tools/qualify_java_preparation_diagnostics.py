#!/usr/bin/env python3
"""Explicit native #709 preparation/execution; never an installed-bundle claim."""
from pathlib import Path
import argparse
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.java_http_composition import diagnostic_program


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("prepare", "execute"))
    parser.add_argument("--native-directory", type=Path, required=True)
    parser.add_argument("--native-receipt", type=Path, required=True)
    parser.add_argument("--builds", type=Path, required=True, help="The four actual completed adapted Java build directories")
    parser.add_argument("--releases", type=Path, required=True, help="The original native-signed release set")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--approved-candidate-sha256", help="Only for execute: exact independently reviewed candidate.json hash")
    parser.add_argument("--without-former-child-case", action="store_true",
                        help="Explicit partial resource program; cannot establish the pre-guest child criterion")
    args = parser.parse_args()
    selected = tuple(path.resolve(strict=True) for path in (args.native_directory, args.native_receipt, args.builds, args.releases))
    output = args.output.resolve()
    if args.mode == "prepare":
        if args.approved_candidate_sha256 is not None:
            parser.error("prepare does not accept approval")
        diagnostic_program.prepare(*selected, output, former_child=not args.without_former_child_case)
    else:
        if args.approved_candidate_sha256 is None or args.without_former_child_case:
            parser.error("execute requires the approved original candidate hash and its unchanged case selection")
        diagnostic_program.execute(*selected, output, approved_sha256=args.approved_candidate_sha256)


if __name__ == "__main__":
    main()

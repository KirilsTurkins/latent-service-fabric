#!/usr/bin/env python3
"""Create and build independent, typed TypeScript capsules."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.rust_capsule_project import ROOT, TEMPLATES, fresh, read_file
from tools.rust_capsule_build import Commands
from tools.build_observation import build_environment
from tools.typescript_guest.project import create
from tools.typescript_guest.build import build


def install(directory: Path):
    directory = fresh(directory)
    for name in ("package.json", "package-lock.json"):
        (directory / name).write_bytes(read_file(ROOT / "sdk/typescript-guest/tools" / name))
    command = Commands(directory, directory, build_environment(directory))
    node = shutil.which("node")
    if not node or command.run("node-version", node, "--version").strip() != b"v24.19.0":
        raise ValueError("Node 24.19.0 is required")
    npm = shutil.which("npm")
    if not npm:
        raise ValueError("npm is required to install the reviewed compiler lock")
    invocation = [npm]
    if Path(npm).suffix.lower() == ".cmd":
        entrypoint = Path(npm).parent / "node_modules/npm/bin/npm-cli.js"
        if not entrypoint.is_file():
            raise ValueError("npm CLI entrypoint unavailable")
        invocation = [node, entrypoint]
    command.run("install-locked-compiler", *invocation, "ci", "--ignore-scripts", "--no-audit", "--no-fund")
    return directory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tools = commands.add_parser("install-tools", help="Install the exact compiler lock in a fresh directory")
    tools.add_argument("directory", type=Path)
    new = commands.add_parser("new", help="Create an independent editable project")
    new.add_argument("directory", type=Path)
    new.add_argument("--template", choices=TEMPLATES, default="greeting")
    new.add_argument("--name")
    compile_ = commands.add_parser("build", help="Typecheck, compile and package captured sources")
    compile_.add_argument("project", type=Path)
    compile_.add_argument("--tools", type=Path, required=True)
    compile_.add_argument("--output", type=Path, required=True)
    compile_.add_argument("--repository", required=True)
    compile_.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    compile_.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    args = parser.parse_args()
    try:
        if args.command == "install-tools":
            result = install(args.directory)
        elif args.command == "new":
            result = create(args.directory, args.template, args.name)
        else:
            result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository, tools=args.tools)
        print(result)
        return 0
    except (ValueError, OSError, RuntimeError) as error:
        print(f"TypeScript capsule authoring failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

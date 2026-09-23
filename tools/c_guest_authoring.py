#!/usr/bin/env python3
"""Create, lock and build real C capsule projects with generated WIT exports."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.c_guest.compiler import SDK, safe_output
from tools.c_guest.project import bindings, build, ProjectError
from tools.build_process import BuildProcessError

TEMPLATES = ('greeting', 'word-count', 'shipping')


def create(destination: Path, template: str) -> dict:
    if template not in TEMPLATES:
        raise ProjectError('unknown maintained C project template')
    destination = safe_output(destination)
    source = SDK / 'projects' / template
    # Copy only source/configuration, never a build artifact, key or grant.
    names = ('c-project.json', 'component.c', 'wit/world.wit')
    for name in names:
        path = source / name
        if path.is_symlink() or not path.is_file():
            raise ProjectError('invalid template inventory')
    destination.mkdir(parents=True)
    for name in names:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / name, target)
    return {'formatVersion': 1, 'template': template, 'project': str(destination),
            'bindingReviewRequired': True, 'executionAuthorized': False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    new = commands.add_parser('new', help='create source files in a new directory')
    new.add_argument('destination', type=Path)
    new.add_argument('--template', choices=TEMPLATES, default='greeting')
    lock = commands.add_parser('bindings', help='check generated binding identities; never silently bless drift')
    lock.add_argument('--project', type=Path, required=True)
    lock.add_argument('--output', type=Path, required=True)
    lock.add_argument('--update', action='store_true', help='explicitly accept/review generated bindings')
    compile_command = commands.add_parser('build', help='compile and prepare unsigned package inputs')
    compile_command.add_argument('--project', type=Path, required=True)
    compile_command.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == 'new':
            result = create(args.destination, args.template)
        elif args.command == 'bindings':
            result = bindings(args.project, args.output, update=args.update)
        else:
            result = build(args.project, args.output)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (ProjectError, BuildProcessError, ValueError, OSError, KeyError, TypeError) as error:
        print('C authoring failed: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

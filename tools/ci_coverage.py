#!/usr/bin/env python3
"""Validate the reviewed before/after inventory of required workflow commands.

This check runs in the existing documentation lane, after its pinned YAML setup.
It is deliberately not imported by the offline profile selector. No automatic
refresh can bless a changed command: edits to commands.json are review inputs.
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path
import sys

import yaml

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_suite_inventory as registry

INVENTORY = registry.ROOT / 'tools/ci/commands.json'
SCHEMA = 'latent.ci.commands.v1'


def workflow_commands(path: str, text: str) -> dict:
    document = yaml.safe_load(text)
    result = {}
    for job, config in document['jobs'].items():
        for step in config.get('steps', []):
            if 'run' not in step:
                continue
            name = step.get('id', step.get('name'))
            registry.require(isinstance(name, str) and name, 'unnamed-required-command')
            key = f'{path}:{job}:{name}'
            registry.require(key not in result, 'duplicate-required-command')
            result[key] = {'workflow': path, 'job': job, 'name': name,
                           'jobIf': config.get('if', 'success()'), 'stepIf': step.get('if', 'success()'),
                           'workingDirectory': step.get('working-directory', '.'),
                           'shell': step.get('shell', 'default'), 'run': step['run'].rstrip()}
    return result


def commands(root: Path) -> dict:
    result = {}
    for path in sorted((root / '.github/workflows').glob('*.yml')):
        result.update(workflow_commands(path.relative_to(root).as_posix(), path.read_text()))
    return result


def delegated_owners(root: Path, entries: dict) -> dict[str, str]:
    # Preserve the internal commands of the existing script owners, including
    # shell-to-shell delegation. Dynamic scenario selection stays in its owner.
    names = set()
    pending = [v['run'] for v in entries.values()]
    while pending:
        for name in re.findall(r'(?<![A-Za-z0-9_./-])(?:tools|sdk)/[A-Za-z0-9_./-]+\.(?:py|sh)\b', pending.pop()):
            if name in names:
                continue
            path = root / name
            registry.require(path.is_file() and not path.is_symlink(), 'missing-command-owner:' + name)
            names.add(name)
            # Shell scripts name further required owners literally. Python
            # implementation helpers do not define a second CI selection list.
            if path.suffix == '.sh':
                pending.append(path.read_text())
    return {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in sorted(names)}


def workflow_identities(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted((root/'.github/workflows').iterdir()) if p.suffix in {'.yml', '.yaml'}}


def python_cases(root: Path) -> dict[str, list[str]]:
    result = {}
    for path in sorted((root/'tools/tests').glob('test_*.py')):
        tree = ast.parse(path.read_text())
        result[path.relative_to(root).as_posix()] = sorted(
            f'{node.name}.{method.name}' for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
            for method in node.body if isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef))
            and method.name.startswith('test_'))
    return result


def validate(root: Path = registry.ROOT, inventory: Path = INVENTORY) -> dict:
    data = registry.read_json(inventory)
    registry.require(data.get('schemaVersion') == SCHEMA, 'command-inventory-version')
    registry.require(workflow_identities(root) == data['workflowIdentities'], 'changed-workflow-contract')
    actual = commands(root)
    registry.require(actual == data['after'], 'unregistered-or-changed-required-command')
    registry.require(delegated_owners(root, actual) == data['delegatedOwners'], 'changed-command-owner-needs-review')
    registry.require(set(data['before']) == set(data['coverage']), 'missing-before-after-coverage')
    for key, record in data['coverage'].items():
        registry.require(record['after'] in actual and record['disposition'] in {'unchanged', 'extended', 'conditional-host-replacement'},
                         'removed-required-command-without-replacement')
        registry.require(record['reason'], 'missing-coverage-review-reason')
        if record['disposition'] == 'unchanged':
            registry.require(data['before'][key] == actual[record['after']], 'unchanged-command-drift')
    # Protect aggregation topology independently of its run-block snapshot.
    workflow = yaml.safe_load((root/'.github/workflows/ci.yml').read_text())
    gate = workflow['jobs']['result']
    registry.require(gate['name'] == 'CI result' and gate['if'] == 'always()', 'conditional-ci-result')
    registry.require(set(gate['needs']) == registry.ALL_JOBS, 'incomplete-ci-result-needs')
    tests = sorted(p.relative_to(root).as_posix() for p in (root/'tools/tests').glob('test_*.py'))
    registry.require(tests == data['pythonTestModules'], 'missing-or-unregistered-python-test-module')
    registry.require(python_cases(root) == data['pythonCases'], 'missing-or-renamed-python-case')
    return data


def main() -> int:
    try:
        data = validate()
        print(f"Covered {len(data['before'])} baseline and {len(data['after'])} current required run blocks; "
              f"{len(data['delegatedOwners'])} delegated script owners")
        return 0
    except (ValueError, KeyError, TypeError, OSError, yaml.YAMLError) as error:
        print(f'CI command coverage failed: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

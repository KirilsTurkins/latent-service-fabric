"""Stage only the maintained .NET build recipe and its static Python support.

This qualification helper excludes optional reference data rather than inventing
an eligibility catalogue. It does not change application or compiler inputs.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import re
import stat
import sys

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dotnet_guest.build import RECIPE, build
from tools.phase2_operator_process import require
from tools.rust_capsule_project import ROOT, checked_path, digest, fresh, inventory, read_file, read_json

MAX_FILES = 256
MAX_FILE = 1024 * 1024
MAX_BYTES = 16 * 1024 * 1024
MANIFEST = 'BUILD-SOURCE-INVENTORY.json'
SELF = 'tools/dotnet_catalogue_free_build.py'
DATA = frozenset(('examples/echo-contract/capsule.json', 'examples/echo-contract/deployment.json',
    'wit/host-abi-phase3-v4.json', 'wit/host-abi-phase3-v5.json', 'wit/host-abi-phase4-v1.json', 'sdk/profile/transaction-requirements-v1.json'))


def allowed(name):
    return name in DATA or (name.startswith('tools/') and name.endswith('.py')
        and all(re.fullmatch(r'[A-Za-z0-9_.-]+', part) and part not in {'.', '..'} for part in name.split('/')))


def source_file(root, name):
    require(allowed(name), 'catalogue-free-source-path')
    path = checked_path(root / name)
    require(path.is_relative_to(root), 'catalogue-free-source-escape')
    metadata = path.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
            'catalogue-free-single-link-source')
    return read_file(path, MAX_FILE)


def module_path(root, module):
    require(re.fullmatch(r'tools(?:\.[A-Za-z_][A-Za-z0-9_]*)*', module) is not None,
            'catalogue-free-python-module')
    name = module.replace('.', '/')
    for candidate in (name + '/__init__.py', name + '.py'):
        if os.path.lexists(root / candidate):
            return candidate
    return None


def imports(root, name, raw):
    module = name.removesuffix('.py').replace('/', '.')
    package = module.removesuffix('.__init__') if module.endswith('.__init__') else module.rpartition('.')[0]
    found = set()
    for node in ast.walk(ast.parse(raw, filename=name)):
        names = []
        if isinstance(node, ast.Import):
            names = [row.name for row in node.names]
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ''
            if node.level:
                parts = package.split('.')
                require(node.level <= len(parts), 'catalogue-free-relative-import')
                base = '.'.join(parts[:len(parts) - node.level + 1] + ([base] if base else []))
            names = [base, *(base + '.' + row.name for row in node.names if row.name != '*')]
        for candidate in names:
            if candidate == 'tools' or candidate.startswith('tools.'):
                selected = module_path(root, candidate)
                if selected is not None:
                    found.add(selected)
    return found


def source_files(root):
    root = checked_path(root)
    pending, selected, total = set(RECIPE) | DATA | {SELF}, {}, 0
    while pending:
        name = min(pending)
        pending.remove(name)
        if name in selected:
            continue
        require(len(selected) < MAX_FILES, 'catalogue-free-source-count')
        raw = source_file(root, name)
        total += len(raw)
        require(total <= MAX_BYTES, 'catalogue-free-source-bytes')
        selected[name] = raw
        if name.endswith('.py'):
            pending.update(imports(root, name, raw))
            for parent in Path(name).parents:
                candidate = parent.as_posix() + '/__init__.py'
                if candidate.startswith('tools/') and os.path.lexists(root / candidate):
                    pending.add(candidate)
    require(set(RECIPE) <= selected.keys() and {name for name in selected if not name.endswith('.py')} == DATA,
            'catalogue-free-recipe-incomplete')
    require(all(source_file(root, name) == raw for name, raw in selected.items()),
            'catalogue-free-source-changed')
    return dict(sorted(selected.items()))


def stage(root, output):
    root, output = checked_path(root), checked_path(output)
    require(output != root and not root.is_relative_to(output), 'catalogue-free-stage-location')
    files = source_files(root)
    output = fresh(output)
    for name, raw in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with path.open('xb') as stream:
            stream.write(raw)
    receipt = {'schemaVersion': 'latent.dotnet.catalogue-free-build-source.v1',
        'files': json.loads(inventory(files)), 'fileCount': len(files), 'sourceBytes': sum(map(len, files.values())),
        'inventoryDigest': digest(inventory(files)), 'optionalReferenceDataPresent': False,
        'catalogueEligibilityCheck': False, 'actualComponentQualified': False}
    (output / MANIFEST).write_bytes(json.dumps(receipt, sort_keys=True, separators=(',', ':')).encode())
    verify(output)
    return receipt


def verify(root):
    root = checked_path(root)
    manifest = root / MANIFEST
    metadata = manifest.lstat()
    require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1 and not manifest.is_symlink(),
            'catalogue-free-single-link-manifest')
    receipt = read_json(manifest, MAX_FILE)
    require(receipt['schemaVersion'] == 'latent.dotnet.catalogue-free-build-source.v1'
            and type(receipt['fileCount']) is int and 0 < receipt['fileCount'] <= MAX_FILES
            and type(receipt['sourceBytes']) is int and 0 < receipt['sourceBytes'] <= MAX_BYTES
            and receipt['optionalReferenceDataPresent'] is False and receipt['catalogueEligibilityCheck'] is False
            and receipt['actualComponentQualified'] is False, 'catalogue-free-stage-schema')
    files, pending, visited = {}, [root], 0
    while pending:
        for path in sorted(pending.pop().iterdir()):
            visited += 1
            require(visited <= MAX_FILES * 4 and not path.is_symlink(), 'catalogue-free-stage-entry')
            name = path.relative_to(root).as_posix()
            metadata = path.lstat()
            require(not getattr(metadata, 'st_file_attributes', 0) & 0x400, 'catalogue-free-stage-reparse')
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            elif name != MANIFEST:
                files[name] = source_file(root, name)
    require(len(files) == receipt['fileCount'] and sum(map(len, files.values())) == receipt['sourceBytes']
            and json.loads(inventory(files)) == receipt['files']
            and digest(inventory(files)) == receipt['inventoryDigest']
            and set(RECIPE) <= files.keys(), 'catalogue-free-stage-mutated')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--tools', required=True, type=Path)
    parser.add_argument('--contracts-tool', required=True, type=Path)
    parser.add_argument('--packager', required=True, type=Path)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--expect-source-digest', required=True)
    args = parser.parse_args(argv)
    before = verify(ROOT)
    require(before['inventoryDigest'] == args.expect_source_digest, 'catalogue-free-unexpected-stage')
    result = build(args.project, args.output, args.contracts_tool, args.packager, args.repository,
                   tools=args.tools, offline=True)
    require(verify(ROOT) == before, 'catalogue-free-stage-changed-during-build')
    recipe = read_json(args.output / 'recipe-inputs.json')
    require(recipe and all(before['files'].get(name) == row for name, row in recipe.items()),
            'catalogue-free-actual-recipe-not-staged')
    print(json.dumps({'status': 'passed', 'stagedInventoryDigest': before['inventoryDigest'],
                      'actualRecipeDigest': digest(read_file(args.output / 'recipe-inputs.json'))}))
    return result


if __name__ == '__main__':
    main()

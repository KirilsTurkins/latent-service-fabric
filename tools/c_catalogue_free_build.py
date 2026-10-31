"""Run the unchanged normal C builder from an owned installed SDK source root."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import stat
import sys
import time

if __package__ in {None, ''}:
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_build, c_capsule_project
from tools.build_observation import file_identity
from tools.rust_capsule_project import ROOT, MAX_FILES, MAX_FILE, MAX_SOURCE, digest, fresh, inventory, read_file, read_json

SELF = 'tools/c_catalogue_free_build.py'
MANIFEST = 'C-BUILD-SOURCE-INVENTORY.json'
PROOF = 'catalogue-free-build.json'
V5 = 'wit/host-abi-phase3-v5.json'


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def source_files(root):
    """Include every staged file, including names ordinary project snapshots omit."""
    root = root.resolve(strict=True)
    require(root.is_dir() and not (root / 'docs').exists(), 'c-outside-source-docs-present')
    require(not (root / 'tools/compatibility_catalogue.py').exists(), 'c-outside-source-catalogue-reader-present')
    files, pending, visited, total = {}, [root], 0, 0
    while pending:
        parent = pending.pop()
        for path in sorted(parent.iterdir()):
            visited += 1
            require(visited <= MAX_FILES and not path.is_symlink(), 'c-outside-source-entry-bound-or-link')
            metadata = path.lstat()
            require(not getattr(metadata, 'st_file_attributes', 0) & 0x400, 'c-outside-source-reparse')
            name = path.relative_to(root).as_posix()
            require(not any(part in {'.git', 'target', '__pycache__', 'docs'} for part in path.relative_to(root).parts),
                    'c-outside-source-unselected-directory')
            if stat.S_ISDIR(metadata.st_mode):
                pending.append(path)
            else:
                require(stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
                        'c-outside-source-single-link-file')
                if name == MANIFEST:
                    continue
                raw = read_file(path, MAX_FILE)
                total += len(raw)
                require(total <= MAX_SOURCE, 'c-outside-source-byte-bound')
                files[name] = raw
    require(SELF in files and V5 in files and set(c_capsule_build.RECIPE) <= files.keys(),
            'c-outside-source-normal-recipe-incomplete')
    return files


def stage(repository, payload):
    """Reuse the installed C recipe; copy its exact source, never rewrite ROOT."""
    from tools import dev_tool_distribution as distribution
    require(repository.resolve(strict=True) == distribution.ROOT.resolve(strict=True) == ROOT.resolve(strict=True),
            'c-outside-source-original-authoring-root')
    payload = fresh(payload)
    distribution.recipe(payload, 'c')
    distribution.copy(repository / SELF, payload / 'recipe' / SELF)
    root = payload / 'recipe'
    files = source_files(root)
    for name, raw in files.items():
        require(name == 'tools/__init__.py' and raw == b'' or read_file(repository / name, MAX_FILE) == raw,
                'c-outside-source-staged-bytes-not-original')
    record = {'schemaVersion': 'latent.c.outside-build-source.v1',
              'files': json.loads(inventory(files)), 'inventoryDigest': digest(inventory(files)),
              'fileCount': len(files), 'sourceBytes': sum(map(len, files.values())),
              'docsPresent': False, 'catalogueReaderPresent': False, 'actualComponentQualified': False}
    (root / MANIFEST).write_bytes((json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode())
    require(verify(root, record['inventoryDigest']) == record, 'c-outside-source-staging-race')
    return root, record


def verify(root, expected):
    manifest = root / MANIFEST
    metadata = manifest.lstat()
    require(not manifest.is_symlink() and stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
            'c-outside-source-manifest-link')
    record = read_json(manifest)
    require(set(record) == {'schemaVersion', 'files', 'inventoryDigest', 'fileCount', 'sourceBytes',
                           'docsPresent', 'catalogueReaderPresent', 'actualComponentQualified'}
            and record.get('schemaVersion') == 'latent.c.outside-build-source.v1'
            and record.get('docsPresent') is False and record.get('catalogueReaderPresent') is False
            and record.get('actualComponentQualified') is False, 'c-outside-source-manifest')
    files = source_files(root)
    require(record.get('files') == json.loads(inventory(files))
            and record.get('inventoryDigest') == expected == digest(inventory(files))
            and record.get('fileCount') == len(files)
            and record.get('sourceBytes') == sum(map(len, files.values())), 'c-outside-source-mutated')
    return record


def imported_modules(root, staged):
    root = root.resolve(strict=True)
    observed = {}
    for name, module in sorted(tuple(sys.modules.items())):
        if name != 'tools' and not name.startswith('tools.'):
            continue
        source = getattr(module, '__file__', None)
        if source is not None:
            path = Path(source).resolve(strict=True)
            require(path.is_relative_to(root), 'c-outside-import-from-original-checkout')
            relative = path.relative_to(root).as_posix()
            require(relative in staged['files'], 'c-outside-import-not-in-staged-inventory')
            observed[name] = relative
        else:
            paths = list(getattr(module, '__path__', []))
            require(paths and all(Path(path).resolve(strict=True).is_relative_to(root) for path in paths),
                    'c-outside-namespace-import-escape')
            observed[name] = [Path(path).resolve().relative_to(root).as_posix() for path in paths]
        selected = getattr(module, 'ROOT', None)
        if isinstance(selected, Path):
            require(selected.resolve(strict=True).is_relative_to(root), 'c-outside-module-root-escape')
    require(c_capsule_build.ROOT.resolve(strict=True) == c_capsule_project.ROOT.resolve(strict=True) == root,
            'c-outside-normal-builder-root-not-relocated')
    return observed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('project', 'output', 'contracts-tool', 'packager', 'zig', 'wit-bindgen', 'wasm-tools'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--expect-source-digest', required=True)
    parser.add_argument('--deadline', required=True, type=float)
    args = parser.parse_args(argv)
    require(sys.flags.isolated == 1 and sys.dont_write_bytecode, 'c-outside-fresh-isolated-python-required')
    require(math.isfinite(args.deadline) and args.deadline > time.monotonic() + 5,
            'c-outside-original-deadline')
    os.chdir(ROOT)
    before = verify(ROOT, args.expect_source_digest)
    imported_modules(ROOT, before)
    paths = {name: getattr(args, name.replace('-', '_')) for name in
             ('zig', 'wit-bindgen', 'wasm-tools', 'contracts-tool', 'packager')}
    require(all(path.is_absolute() and not path.is_symlink() and path.is_file() for path in paths.values()),
            'c-outside-immutable-tool-paths-required')
    tools = {name: file_identity(path, name, 512 * 1024**2) for name, path in paths.items()}
    artifact = c_capsule_build.build(args.project, args.output, args.contracts_tool, args.packager,
        args.repository, installed={name: paths[name] for name in ('zig', 'wit-bindgen', 'wasm-tools')},
        _deadline=args.deadline)
    modules = imported_modules(ROOT, before)
    require(verify(ROOT, args.expect_source_digest) == before, 'c-outside-source-changed-during-build')
    require(tools == {name: file_identity(path, name, 512 * 1024**2) for name, path in paths.items()}, 'c-outside-build-tool-changed')
    actual_recipe = read_json(artifact / 'recipe-inputs.json')
    require(actual_recipe and all(before['files'].get(name) == row for name, row in actual_recipe.items()),
            'c-outside-normal-build-recipe-not-staged')
    record = {'schemaVersion': 'latent.c.catalogue-free-build.v1', 'status': 'passed',
        'sourceInventory': before, 'sourceInventoryBeforeAfterEqual': True,
        'normalBuilderRoot': str(ROOT), 'isolatedPython': True, 'bytecodeWritesDisabled': True,
        'importedToolsModules': modules, 'toolsBeforeAfter': tools,
        'recipeInputs': digest(read_file(artifact / 'recipe-inputs.json')),
        'sourceInputs': digest(read_file(artifact / 'source-inputs.json')),
        'component': digest(read_file(artifact / 'component.wasm', 64 * 1024**2)),
        'docsPresent': False, 'catalogueReaderPresent': False, 'oldExecutionBorrowed': False}
    (artifact / PROOF).write_bytes((json.dumps(record, sort_keys=True, separators=(',', ':')) + '\n').encode())
    print(json.dumps({'status': 'passed', 'sourceInventoryDigest': before['inventoryDigest']}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

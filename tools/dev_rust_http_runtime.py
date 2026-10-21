"""Stage and select the explicitly authenticated installed Rust HTTP profile."""
from __future__ import annotations

import os
from pathlib import Path

from tools.build_observation import build_environment
from tools.build_process import run_bounded
from tools.rust_capsule_project import checked_path, decode_json, read_file, snapshot
from tools.rust_wasi_http_inputs import FILES, RECEIPT, Prepared
from tools import rust_wasi_http_profile as profile

DIRECTORY = 'sdk/rust-http-runtime'
MEMBERS = (RECEIPT, 'source-inputs.json', *FILES, 'component-composer/wac')


def prepare(payload: Path, source: Path) -> set[str]:
    """Copy only verified public compiler inputs, preserving producer receipts."""
    sdk = checked_path(payload) / 'sdk'
    original = Prepared(source, sdk / 'rust/bin/rustc', sdk / 'bin/wasm-tools')
    original.check()
    before = {name: read_file(original.path / name, 64 * 1024 * 1024) for name in MEMBERS}
    target = payload / DIRECTORY
    if target.exists() or target.is_symlink():
        raise ValueError('rust-http-distribution-owned-fresh-output')
    target.mkdir(mode=0o700)
    for name, raw in before.items():
        destination = target / name
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with destination.open('xb') as stream:
            stream.write(raw)
    original.check()
    retained = Prepared(target, sdk / 'rust/bin/rustc', sdk / 'bin/wasm-tools')
    retained.check()
    if retained.material() != original.material() or any(
            read_file(original.path / name, 64 * 1024 * 1024) != raw
            or read_file(target / name, 64 * 1024 * 1024) != raw
            for name, raw in before.items()):
        raise ValueError('rust-http-distribution-inputs-changed')
    return {DIRECTORY + '/component-composer/wac'}


def declared_world(graph: dict, world: str) -> list[str]:
    """Resolve the exact package/version/world identity, never the first world."""
    base, separator, version = world.partition('@')
    package, slash, selected = base.rpartition('/')
    if not slash or not package or not selected or separator and not version:
        raise ValueError('rust-http-distribution-world-identity')
    package += separator + version
    worlds, packages = graph.get('worlds'), graph.get('packages')
    if not isinstance(worlds, list) or len(worlds) > 128 or not isinstance(packages, list):
        raise ValueError('rust-http-distribution-world-graph')
    chosen = []
    for row in worlds:
        index = row.get('package')
        if type(index) is not int or not 0 <= index < len(packages):
            raise ValueError('rust-http-distribution-world-package')
        if row.get('name') == selected and packages[index].get('name') == package:
            chosen.append(row)
    if len(chosen) != 1:
        raise ValueError('rust-http-distribution-exact-selected-world')
    return sorted(profile.names({**graph, 'worlds': chosen}, 'imports', selected))


def compiler_options(payload: Path, project: Path, check) -> dict:
    """A bundled adapter is selected only by all three source declarations.

    The normal builder independently validates emitted WASI imports, source
    declarations, the prepared runtime and final composition. No provider grant
    or application package name participates in this selection.
    """
    directory = checked_path(payload / DIRECTORY)
    if not os.path.lexists(directory):
        return {}
    sdk = payload / 'sdk'
    prepared = Prepared(directory, sdk / 'rust/bin/rustc', sdk / 'bin/wasm-tools')
    prepared.check()
    project = checked_path(project)
    descriptor = read_file(project / 'capsule-project.json', 1024 * 1024)
    owner = decode_json(descriptor)
    if not isinstance(owner, dict) or not isinstance(owner.get('world'), str):
        raise ValueError('rust-http-distribution-project-world')
    before = snapshot(project / 'wit')
    check()
    result = run_bounded([str(sdk / 'bin/wasm-tools'), 'component', 'wit',
        str(project / 'wit'), '--json'], cwd=project, env=build_environment(project),
        timeout_seconds=30, max_output_bytes=16 * 1024 * 1024)
    if result.returncode != 0:
        raise ValueError('rust-http-distribution-wit-reader-failed')
    declared = declared_world(decode_json(result.stdout), owner['world'])
    check()
    if descriptor != read_file(project / 'capsule-project.json', 1024 * 1024) or before != snapshot(project / 'wit'):
        raise ValueError('rust-http-distribution-source-changed-during-selection')
    prepared.check()
    return {'http_runtime': directory} if profile.AUTHORITY <= set(declared) else {}

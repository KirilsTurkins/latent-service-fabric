"""Closed compiler-owned diagnostic source selection; never a project option."""
from pathlib import Path
from tools.rust_capsule_project import ROOT, read_file
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

PROFILE = 'lsf-typescript-borrow-probe-v1'
WORLD = 'tests:typescript-import-borrow-probe/service@1.0.0'
GATE = 'tests:typescript-import-borrow-gate/streams@1.0.0'
DIAGNOSTIC = 'tests:typescript-import-borrow-gate/diagnostic@1.0.0'
ORIGINAL = 'latent:network/streams@0.1.0'
BUILTIN = 'lsf:typescript-borrow-probe'
PREFIX = 'sdk/typescript-guest/probes/borrow-release/'
INPUTS = {
    'src/main.ts': PREFIX + 'main.ts',
    'wit/world.wit': PREFIX + 'world.wit',
    'wit/deps/gate/package.wit': PREFIX + 'gate.wit',
    'wit/deps/network/package.wit': 'wit/platform/network/package.wit',
}
RECIPE = (PREFIX + 'outer.wit', PREFIX + 'main.ts', PREFIX + 'world.wit', PREFIX + 'gate.wit',
          PREFIX + 'private.d.ts', 'tools/typescript_guest/borrow_probe_profile.py',
          'tools/typescript_guest/borrow_probe.mjs')


def validate(selection: str | None, work: Path, world: str, runtime: str,
             application_modules: dict | None) -> bool:
    if selection is None:
        return False
    if (selection != PROFILE or runtime != IMPORT_PROFILE or world != WORLD or
            application_modules is not None):
        raise ValueError('compiler-owned-borrow-probe-profile-required')
    actual = {path.relative_to(work).as_posix() for name in ('src', 'wit')
              for path in (work / name).rglob('*') if path.is_file()}
    if actual != INPUTS.keys():
        raise ValueError('compiler-owned-borrow-probe-exact-source-graph-required')
    for name, owned in INPUTS.items():
        path = work / name
        if path.is_symlink() or read_file(path, 256 * 1024) != read_file(ROOT / owned, 256 * 1024):
            raise ValueError('compiler-owned-borrow-probe-source-changed')
    return True


def declarations(directory: Path) -> None:
    matches = [path for path in directory.rglob('*.d.ts')
               if ('@module Interface ' + GATE + ' ') in path.read_text(encoding='utf-8')]
    expected = ('export function read(source: Connection, maximumBytes: number, '
                'timeoutMillis: number | undefined): Promise<Chunk | undefined>;')
    if len(matches) != 1 or matches[0].read_text(encoding='utf-8').splitlines().count(expected) != 1:
        raise ValueError('compiler-owned-borrow-probe-generated-read-shape-drift')
    (directory / 'borrow-probe-private.d.ts').write_bytes(read_file(ROOT / (PREFIX + 'private.d.ts')))

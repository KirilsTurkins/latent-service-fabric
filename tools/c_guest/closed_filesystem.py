"""Authenticate the exact libc seam used by the compiler-owned closed file port."""
from dataclasses import dataclass
from pathlib import Path

from tools.build_observation import file_identity
from tools.rust_capsule_project import digest, read_file

PROFILE = 'c-closed-filesystem-stdio-v1'
UPSTREAM = 'https://codeberg.org/ziglang/zig/src/tag/0.16.0/'
SOURCES = {
    'lib/libc/include/wasm-wasi-musl/stdio.h':
        ('a7ce495ed82dc11ffb811bcdeec75b4abe743ee88dda78eee4cebfa78ab28244', 7034),
    'lib/libc/wasi/libc-top-half/musl/src/stdio/fopen.c':
        ('961aa0b0b3cf645d7170eafaa072fad00a5f8784bd68ae1db4b0c85f2aa15713', 1159),
}
OVERLAY = '60e5fe54f5c67c1026c39d5036c4393452b44e00b09e95362ed3f888bfcde74a'


@dataclass(frozen=True)
class Boundary:
    paths: dict
    materials: dict

    def check_unchanged(self):
        if {name: file_identity(path, name, 16384) for name, path in self.paths.items()} != self.materials:
            raise ValueError('c-closed-filesystem-input-changed')


def prepare(zig: Path, sdk: Path) -> Boundary:
    paths = {}
    for ordinal, (name, (expected, size)) in enumerate(SOURCES.items()):
        path = zig.parent/name
        raw = read_file(path, 16384)
        if len(raw) != size or digest(raw) != 'sha256:'+expected:
            raise ValueError('c-closed-filesystem-unreviewed-libc-preimage')
        paths['c-closed-filesystem-libc-'+str(ordinal)] = path
    overlay = sdk/'include/stdio.h'
    if digest(read_file(overlay, 16384)) != 'sha256:'+OVERLAY:
        raise ValueError('c-closed-filesystem-unreviewed-overlay')
    paths[PROFILE] = overlay
    materials = {name: file_identity(path, name, 16384) for name, path in paths.items()}
    # Recheck after reading identities as well as after the actual compilation.
    for ordinal, (_name, (expected, size)) in enumerate(SOURCES.items()):
        row = materials['c-closed-filesystem-libc-'+str(ordinal)]
        if row['digest'] != 'sha256:'+expected or row['size'] != size:
            raise ValueError('c-closed-filesystem-libc-input-raced')
    if materials[PROFILE]['digest'] != 'sha256:'+OVERLAY:
        raise ValueError('c-closed-filesystem-overlay-input-raced')
    return Boundary(paths, materials)

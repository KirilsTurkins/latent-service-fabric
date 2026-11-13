"""Opt-in C declarations for signal/jump headers without their operations."""
from dataclasses import dataclass, field
from pathlib import Path

from tools.build_observation import file_identity
from tools.rust_capsule_project import digest, read_file

PROFILE = 'c-closed-signal-jump-headers-v1'
DEFAULT = 'system'
RECIPE = ('tools/c_guest/closed_headers.py',)
GUARD = 'runtime/closed-signal-guard.c'
GUARD_DIGEST = 'ec0ac32a5543bbf7a025610a6f776479e65b3f6a259fefc947584c5b761f3e8c'
# Source and dependent declarations are exact Zig 0.16.0 inputs. Copies keep
# user include directories from intercepting the compiler-owned declarations.
LIBC = {
    'original/signal.h': ('lib/libc/include/wasm-wasi-musl/signal.h', 'ddf64d2de878c581a9eec8bcbcfa81e310b89d96389504f9de3a7d31b446eea5'),
    'original/setjmp.h': ('lib/libc/include/wasm-wasi-musl/setjmp.h', '28f24e8729f04e4498115586a60a58fdffddb60c8893bb095d6e004a0c60243f'),
    'bits/signal.h': ('lib/libc/include/wasm-wasi-musl/bits/signal.h', '80995925ff6b7c365ea4a2c5f01b0f2b4131f20450cfd1839f0dc46459255960'),
    'bits/setjmp.h': ('lib/libc/include/wasm-wasi-musl/bits/setjmp.h', 'e6a786d963fa17e3f14986b63860c07d3872061f4e964c3d899214888a1f70df'),
    'features.h': ('lib/libc/include/generic-musl/features.h', '2251ca4fa4ba92c741fcc89930c2a69aea70e6336fc7dca19ed347c8429c469f'),
}
WRAPPERS = {
    'signal.h': b'''#ifndef LSF_C_CLOSED_SIGNAL_HEADER
#define LSF_C_CLOSED_SIGNAL_HEADER
#if defined(_WASI_EMULATED_SIGNAL) || defined(__wasilibc_unmodified_upstream)
#error signal emulation is outside this closed header selection
#endif
#define _WASI_EMULATED_SIGNAL 1
#include "original/signal.h"
#undef _WASI_EMULATED_SIGNAL
#endif
''',
    'setjmp.h': b'''#ifndef LSF_C_CLOSED_SETJMP_HEADER
#define LSF_C_CLOSED_SETJMP_HEADER
#if defined(__wasm_exception_handling__) || defined(__wasilibc_unmodified_upstream)
#error exception handling is outside this closed header selection
#endif
#define __wasm_exception_handling__ 1
#include "original/setjmp.h"
#undef __wasm_exception_handling__
#endif
''',
}
RESERVED = frozenset((
    '_WASI_EMULATED_SIGNAL', '__wasm_exception_handling__', '__wasilibc_unmodified_upstream',
    '_SIGNAL_H', '_SETJMP_H', 'LSF_C_CLOSED_SIGNAL_HEADER', 'LSF_C_CLOSED_SETJMP_HEADER',
    'signal', 'raise', 'bsd_signal', '__sysv_signal', '__SIG_ERR', '__SIG_IGN',
    'setjmp', '_setjmp', 'longjmp', '_longjmp', 'sigsetjmp', 'siglongjmp',
    '__lsf_c_unsupported_signal_operation',
))


def selected(project):
    profile = project.get('headerProfile', DEFAULT)
    if type(profile) is not str or profile not in (DEFAULT, PROFILE):
        raise ValueError('unsupported-c-header-profile')
    if profile == PROFILE:
        from tools.c_guest.threading import PROFILE as THREAD_PROFILE
        if project.get('threadingProfile', 'single-threaded') != THREAD_PROFILE:
            raise ValueError('c-closed-headers-require-cooperative-threading')
        return True
    return False


def check_defines(defines):
    if any(value.split('=', 1)[0] in RESERVED for value in defines):
        raise ValueError('c-closed-headers-reserved-define')


@dataclass(frozen=True)
class Boundary:
    paths: dict
    materials: dict
    copies: dict

    def check_unchanged(self):
        for name, path in self.paths.items():
            if file_identity(path, name, 16384) != self.materials[name]:
                raise ValueError('c-closed-headers-original-input-changed')

    def stage(self, directory):
        self.check_unchanged()
        directory.mkdir()
        files = {**self.copies, **WRAPPERS}
        for name, data in files.items():
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as output:
                output.write(data)
        stage = Stage(directory, files)
        stage.check_unchanged()
        return stage


@dataclass
class Stage:
    directory: Path
    files: dict
    guard_object: dict | None = field(default=None)

    def check_unchanged(self):
        expected = set(self.files)
        if self.guard_object is not None:
            expected.add('guard.o')
        actual, directories = set(), set()
        for path in self.directory.rglob('*'):
            if path.is_symlink():
                raise ValueError('c-closed-headers-staged-input-changed')
            if path.is_file():
                actual.add(path.relative_to(self.directory).as_posix())
            elif path.is_dir():
                directories.add(path.relative_to(self.directory).as_posix())
            else:
                raise ValueError('c-closed-headers-staged-input-changed')
        if directories != {'bits', 'original'} or actual != expected or any(read_file(self.directory / name, 16384) != data
                                     for name, data in self.files.items()):
            raise ValueError('c-closed-headers-staged-input-changed')
        if self.guard_object is not None and file_identity(self.directory / 'guard.o',
                'c-closed-signal-guard-object', 4 * 1024 * 1024) != self.guard_object:
            raise ValueError('c-closed-headers-guard-object-changed')

    def accept_guard(self):
        if self.guard_object is not None:
            raise ValueError('c-closed-headers-guard-already-built')
        self.guard_object = file_identity(self.directory / 'guard.o', 'c-closed-signal-guard-object', 4 * 1024 * 1024)
        self.check_unchanged()


def prepare(zig, sdk):
    paths, copies, expected = {}, {}, {}
    for index, (target, (source, sha)) in enumerate(LIBC.items()):
        name = 'c-closed-headers-libc-' + str(index)
        paths[name] = zig.parent / source
        raw = read_file(paths[name], 16384)
        if digest(raw) != 'sha256:' + sha:
            raise ValueError('c-closed-headers-libc-preimage')
        copies[target], expected[name] = raw, 'sha256:' + sha
    guard = sdk / GUARD
    name = 'c-closed-signal-guard-source'
    paths[name] = guard
    if digest(read_file(guard, 16384)) != 'sha256:' + GUARD_DIGEST:
        raise ValueError('c-closed-headers-guard-preimage')
    expected[name] = 'sha256:' + GUARD_DIGEST
    materials = {name: file_identity(path, name, 16384) for name, path in paths.items()}
    if any(materials[name]['digest'] != value for name, value in expected.items()):
        raise ValueError('c-closed-headers-input-raced')
    return Boundary(paths, materials, copies)
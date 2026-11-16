"""Exercise captured C feature probes with an SDK-owned isolated CMake project."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_project, dev_tool_distribution
from tools.build_process import run_bounded_result
from tools.c_guest import feature_detection, standard_facilities, threading
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, snapshot, write_json


def configure(output: Path, project: Path, kit: Path, expected: str, zig: Path, cmake: Path,
              label: str, *, present: bool, wrong_compiler: bool = False,
              omit_socket: bool = False, sdk_root: Path = ROOT):
    sandbox = shutil.which('bwrap')
    if sys.platform != 'linux' or not sandbox or not cmake.is_relative_to('/usr'):
        raise ValueError('c-feature-control-requires-linux-system-cmake-and-bubblewrap')
    output.mkdir(mode=0o700)
    executable = Path(sys.executable).resolve(strict=True)
    python = str(executable)
    mounts = []
    if not executable.is_relative_to('/usr'):
        prefix = Path(sys.base_prefix).resolve(strict=True)
        if not executable.is_relative_to(prefix):
            raise ValueError('c-feature-control-python-outside-prefix')
        mounts = ['--ro-bind', str(prefix), '/python']
        python = '/python/' + executable.relative_to(prefix).as_posix()
    test_project = '/test/project with spaces'
    test_kit = '/test/kit with spaces'
    command = [sandbox, '--unshare-all', '--die-with-parent', '--new-session', '--clearenv',
               '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp', '--dir', '/home',
               '--setenv', 'HOME', '/home', '--setenv', 'PATH', '/usr/bin:/bin',
               '--setenv', 'LC_ALL', 'C', '--setenv', 'TZ', 'UTC',
               '--setenv', 'ZIG_GLOBAL_CACHE_DIR', '/test/build/zig-global',
               '--setenv', 'ZIG_LOCAL_CACHE_DIR', '/test/build/zig-local',
               '--dir', '/test', '--ro-bind', '/usr', '/usr']
    for name in ('/bin', '/lib', '/lib64'):
        if Path(name).exists():
            command += ['--ro-bind', str(Path(name).resolve()), name]
    command += [*mounts, '--bind', str(output), '/test/build', '--ro-bind', str(sdk_root), '/repo',
                '--ro-bind', str(ROOT / 'tools/tests/fixtures/c-feature-probe'), '/fixture',
                '--ro-bind', str(project), test_project, '--ro-bind', str(kit), test_kit,
                '--ro-bind', str(zig.parent), '/zig', '--chdir', '/test/build', '--', str(cmake),
                '-S', '/fixture', '-B', '/test/build',
                '-DCMAKE_SYSTEM_NAME=WASI', '-DCMAKE_C_COMPILER=' + ('/usr/bin/true' if wrong_compiler else '/zig/' + zig.name),
                '-DCMAKE_C_COMPILER_ARG1=cc', '-DCMAKE_C_COMPILER_TARGET=wasm32-wasi',
                '-DCMAKE_PROJECT_TOP_LEVEL_INCLUDES=/repo/tools/c_guest/feature_loader.cmake',
                '-DLSF_C_FEATURE_PROJECT=' + test_project, '-DLSF_C_FEATURE_KIT=' + test_kit,
                '-DLSF_C_FEATURE_EXPECT=' + expected, '-DLSF_C_FEATURE_PYTHON=' + python,
                '-DLSF_EXPECT_FEATURE=' + ('ON' if present else 'OFF'),
                '-DLSF_EXPECT_SOCKET=' + ('OFF' if omit_socket else 'ON'),
                '-DLSF_OMIT_SOCKET_SOURCE=' + ('ON' if omit_socket else 'OFF')]
    result = run_bounded_result(command, output, {'PATH': os.defpath}, 120, 4 * 1024 * 1024)
    (output / (label + '.stdout.txt')).write_bytes(result.stdout)
    (output / (label + '.stderr.txt')).write_bytes(result.stderr)
    return result


def run(output: Path, zig: Path, wit: Path, wasm: Path, cmake: Path) -> dict:
    output = fresh(output)
    zig, wit, wasm, cmake = (path.resolve(strict=True) for path in (zig, wit, wasm, cmake))
    installed = {'zig': zig, 'wit-bindgen': wit, 'wasm-tools': wasm}
    project = c_capsule_project.create(output / 'project with spaces', 'greeting',
        threading_profile=threading.PROFILE, runtime_profile=standard_facilities.STREAM_STDIO_PROFILE)
    before = snapshot(project)
    kit = feature_detection.prepare(project, output / 'kit with spaces', installed=installed)
    receipt = read_file(kit / 'feature-probes.json')
    expected = digest(receipt)
    value = json.loads(receipt)
    if (value['numericResolver'] != 'captured' or value['authority'] != 'none'
            or value['socketProbe']['link'] != 'actual-sdk-source'
            or value['configureExecuted'] is not False or value['componentBuilt'] is not False
            or feature_detection.verify(project, kit, expected, zig) != value['object']['digest']):
        raise ValueError('c-feature-control-selected-receipt')
    good = configure(output / 'new-configure', project, kit, expected, zig, cmake, 'new', present=True)
    if good.returncode or read_file(output / 'new-configure/feature-result.txt') != b'passed\n':
        raise ValueError('c-feature-control-selected-cmake')

    missing_socket = configure(output / 'missing-socket-configure', project, kit, expected,
                               zig, cmake, 'missing-socket', present=True, omit_socket=True)
    if missing_socket.returncode or read_file(output / 'missing-socket-configure/feature-result.txt') != b'passed\n':
        raise ValueError('c-feature-control-socket-missing-source')

    old = output / 'old-project'
    shutil.copytree(project, old)
    (old / standard_facilities.SDK_SOURCE_PREFIX / standard_facilities.RESOLVER_SOURCE).unlink()
    files = snapshot(old)
    sdk = json.loads(files['sdk-lock.json'])
    vendor = {name.removeprefix('vendor/lsf/'): raw for name, raw in files.items() if name.startswith('vendor/lsf/')}
    sdk['sdk'] = json.loads(inventory(vendor))
    (old / 'sdk-lock.json').write_text(json.dumps(sdk, indent=2) + '\n')
    old_before = snapshot(old)
    old_kit = feature_detection.prepare(old, output / 'old-kit', installed=installed)
    old_expect = digest(read_file(old_kit / 'feature-probes.json'))
    if feature_detection.verify(old, old_kit, old_expect, zig) != 'not-selected':
        raise ValueError('c-feature-control-old-selected')
    old_result = configure(output / 'old-configure', old, old_kit, old_expect, zig, cmake, 'old', present=False)
    if old_result.returncode or read_file(output / 'old-configure/feature-result.txt') != b'passed\n':
        raise ValueError('c-feature-control-old-cmake')
    wrong_old = configure(output / 'old-wrong-compiler-configure', old, old_kit, old_expect,
                          zig, cmake, 'old-wrong-compiler', present=False, wrong_compiler=True)
    if wrong_old.returncode == 0 or b'c-feature-probe-compiler-changed' not in wrong_old.stderr:
        raise ValueError('c-feature-control-old-compiler-tamper')

    changed_object = output / 'tampered-object-kit'
    shutil.copytree(kit, changed_object)
    obj = changed_object / 'numeric-resolver.o'
    raw = bytearray(read_file(obj)); raw[-1] ^= 1; obj.write_bytes(raw)
    bad_object = configure(output / 'tampered-object-configure', project, changed_object, expected,
                           zig, cmake, 'tampered-object', present=True)
    if bad_object.returncode == 0 or b'c-feature-probe-object-changed' not in bad_object.stderr:
        raise ValueError('c-feature-control-object-tamper')
    changed_binding = output / 'tampered-socket-binding-kit'
    shutil.copytree(kit, changed_binding)
    binding = changed_binding / 'socket-bindings/probe.h'
    binding.write_bytes(read_file(binding) + b'\n/* changed after preparation */\n')
    bad_binding = configure(output / 'tampered-socket-binding-configure', project, changed_binding,
                            expected, zig, cmake, 'tampered-socket-binding', present=True)
    if bad_binding.returncode == 0 or b'c-feature-probe-socket-bindings-changed' not in bad_binding.stderr:
        raise ValueError('c-feature-control-socket-binding-tamper')
    changed_declaration = output / 'tampered-socket-declaration-kit'
    shutil.copytree(kit, changed_declaration)
    declaration = changed_declaration / 'socket-probe.h'
    declaration.write_bytes(read_file(declaration) + b'\n/* changed after preparation */\n')
    bad_declaration = configure(output / 'tampered-socket-declaration-configure', project, changed_declaration,
                                expected, zig, cmake, 'tampered-socket-declaration', present=True)
    if bad_declaration.returncode == 0 or b'c-feature-probe-socket-bindings-changed' not in bad_declaration.stderr:
        raise ValueError('c-feature-control-socket-declaration-tamper')

    changed_project = output / 'tampered-project'
    shutil.copytree(project, changed_project)
    selected_source = changed_project / standard_facilities.SDK_SOURCE_PREFIX / standard_facilities.RESOLVER_SOURCE
    selected_source.write_bytes(read_file(selected_source) + b'\n/* changed after kit preparation */\n')
    bad_source = configure(output / 'tampered-source-configure', changed_project, kit, expected,
                           zig, cmake, 'tampered-source', present=True)
    if bad_source.returncode == 0 or b'vendored' not in bad_source.stderr or b'SDK changed' not in bad_source.stderr:
        raise ValueError('c-feature-control-source-tamper')
    for label, name in (('socket-source', feature_detection.SOCKET_SOURCE),
                        ('socket-wit', feature_detection.SOCKET_WIT)):
        changed = output / ('tampered-' + label + '-project')
        shutil.copytree(project, changed)
        target = changed / name
        target.write_bytes(read_file(target) + b'\n/* changed after preparation */\n')
        result = configure(output / ('tampered-' + label + '-configure'), changed, kit, expected,
                           zig, cmake, 'tampered-' + label, present=True)
        if result.returncode == 0 or b'vendored' not in result.stderr or b'SDK changed' not in result.stderr:
            raise ValueError('c-feature-control-' + label + '-tamper')

    changed_include = output / 'unexpected-include-kit'
    shutil.copytree(kit, changed_include)
    (changed_include / 'lsf-c-features.cmake').write_text('message(FATAL_ERROR "unexpected code executed")\n')
    bad_include = configure(output / 'unexpected-include-configure', project, changed_include, expected,
                            zig, cmake, 'unexpected-include', present=True)
    if (bad_include.returncode == 0 or b'c-feature-probe-unexpected-input' not in bad_include.stderr
            or b'unexpected code executed' in bad_include.stderr):
        raise ValueError('c-feature-control-include-tamper')
    altered_sdk = output / 'altered-sdk'
    altered_sdk.mkdir()
    dev_tool_distribution.recipe(altered_sdk, 'c')
    loader = altered_sdk / 'recipe/tools/c_guest/feature_loader.cmake'
    loader.write_bytes(read_file(loader) + b'\n# changed after kit preparation\n')
    bad_loader = configure(output / 'changed-loader-configure', project, kit, expected,
                           zig, cmake, 'changed-loader', present=True, sdk_root=altered_sdk / 'recipe')
    if bad_loader.returncode == 0 or b'c-feature-probe-captured-input-changed' not in bad_loader.stderr:
        raise ValueError('c-feature-control-loader-tamper')
    bad_compiler = configure(output / 'wrong-compiler-configure', project, kit, expected,
                             zig, cmake, 'wrong-compiler', present=True, wrong_compiler=True)
    if bad_compiler.returncode == 0 or b'c-feature-probe-compiler-changed' not in bad_compiler.stderr:
        raise ValueError('c-feature-control-compiler-tamper')
    for suffix in ('bad;path', 'bad\npath', 'bad\rpath', 'bad"path', "bad'path", 'bad\\path', 'bad$path', 'bad`path'):
        try:
            feature_detection.safe_path(output / suffix)
        except ValueError as error:
            if str(error) != 'c-feature-probe-path':
                raise
        else:
            raise ValueError('c-feature-control-path-not-refused')
    if snapshot(project) != before or snapshot(old) != old_before:
        raise ValueError('c-feature-control-project-mutated')
    result = {'status': 'passed', 'featureReceiptDigest': expected,
              'resolverDigest': value['source']['digest'], 'objectDigest': value['object']['digest'],
              'cases': ['paths-with-spaces', 'old-capture', 'old-compiler-tamper', 'object-tamper', 'source-tamper',
                        'socket-link', 'missing-socket-source', 'socket-binding-tamper', 'socket-declaration-tamper',
                        'socket-source-tamper', 'socket-wit-tamper',
                        'unexpected-include', 'changed-sdk-loader',
                        'wrong-compiler', 'unsafe-path-refusal'],
              'configureNetwork': 'denied', 'componentBuilt': False, 'realProvider': False}
    write_json(output / 'feature-controls.json', result)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'zig', 'wit-bindgen', 'wasm-tools', 'cmake'):
        parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    print(run(args.output, args.zig, args.wit_bindgen, args.wasm_tools, args.cmake)['status'])

#!/usr/bin/env python3
"""Compile the fixed StringAmplifier control on the pinned split TeaVM loader.

This exercises C frontend generation and fail-closed compiler controls only.
It neither builds a component nor executes a guest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import tomllib
from types import SimpleNamespace
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_guest.compiler import source_module
from tools.java_guest.coroutine_patch import ASYNC_CLASSES, corrected_async_source
from tools.phase2_operator_process import WorkflowError, require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_checkpoint_context import acquire, overlay, retain_compiler_inputs
from tools.qualify_java_fibers import locked_model_classpath
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

SDK = ROOT / 'sdk/java-guest'
CONTROL = SDK / 'fibers/conformance/compiler/CheckpointAmplifierProbe.java'
SPLIT = SDK / 'fibers/conformance/compiler/AmplifierSplitLauncher.java'
PLUGIN = SDK / 'fibers/conformance/compiler/AmplifierPluginControl.java'
WORKER = SDK / 'fibers/conformance/compiler/WorkerCompilerControl.java'
MATH = SDK / 'fibers/compiler/dev/latent/guest/runtime/compiler/BoundedMathInitialization.java'
MATH_REFERENCE = SDK / 'fibers/conformance/compiler/MathInitializationReference.java'
FINDER = SDK / 'fibers/compiler-patch/AsyncMethodFinder.java'
LOCK = SDK / 'feasibility/dependencies.lock.json'
VERIFICATION = SDK / 'feasibility/gradle/verification-metadata.xml'
PLATFORM_SHA256 = '999d369ab15aa83c17987d048ba59560759169891de7e13a5a1c2bd93dd060a8'
PLATFORM_BYTES = 101636
EMITTER = 'org/teavm/platform/plugin/PlatformPlugin$1.class'
MODES = ('pass', 'reorder', 'replace', 'late', 'array', 'declaration', 'parent',
    'generator-reorder', 'generator-replace', 'extra-intrinsic', 'extra-generator',
    'wrong-target', 'tampered', 'inclusive', 'inclusive-near-max', 'inclusive-overflow',
    'inclusive-dynamic', 'plugin-neutral', 'plugin-intrinsic', 'plugin-generator',
    'plugin-completion-intrinsic', 'plugin-completion-generator', 'plugin-declaration',
    'worker-descending', 'worker-descending-inclusive', 'worker-descending-zero',
    'worker-descending-overflow', 'worker-descending-dynamic', 'worker-descending-stalled',
    'worker-field', 'worker-field-alias', 'worker-field-call', 'worker-field-bypass',
    'worker-field-volatile', 'worker-resource', 'worker-resource-declaration', 'worker-resource-parent',
    'worker-locale', 'worker-locale-declaration', 'worker-locale-provider', 'worker-locale-late-provider',
    'worker-math', 'worker-math-mutated')
POSITIVE = frozenset(('pass', 'late', 'inclusive', 'inclusive-near-max', 'plugin-neutral',
    'worker-descending', 'worker-descending-inclusive', 'worker-descending-zero', 'worker-field',
    'worker-resource', 'worker-locale', 'worker-math'))


def alter_emitter(source: Path, destination: Path) -> dict:
    """Alter the emitter class in a valid, equal-size ZIP without touching the locked input."""
    raw = read_file(source, PLATFORM_BYTES + 1)
    require(len(raw) == PLATFORM_BYTES and hashlib.sha256(raw).hexdigest() == PLATFORM_SHA256,
        'java-amplifier-platform-identity')
    changed = 0
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, 'x',
            compression=zipfile.ZIP_DEFLATED, compresslevel=9) as altered:
        entries = original.infolist()
        require(len(entries) == 81 and len({entry.filename for entry in entries}) == len(entries)
            and sum(entry.file_size for entry in entries) <= 1024 * 1024,
            'java-amplifier-platform-entry-bound')
        for entry in entries:
            require(0 <= entry.file_size <= 131072, 'java-amplifier-platform-entry-size')
            data = original.read(entry)
            if entry.filename == EMITTER:
                require(data.count(b'PlatformPlugin.java') == 1, 'java-amplifier-emitter-source-marker')
                data = data.replace(b'PlatformPlugin.java', b'PlatformPlugiN.java')
                changed += 1
            altered.writestr(entry, data, compress_type=entry.compress_type, compresslevel=9)
    require(changed == 1, 'java-amplifier-emitter-mutation-count')
    padding = PLATFORM_BYTES - destination.stat().st_size
    require(0 <= padding <= 65535, 'java-amplifier-emitter-padding-bound')
    with zipfile.ZipFile(destination, 'a') as archive:
        archive.comment = b'\0' * padding
    require(destination.stat().st_size == PLATFORM_BYTES, 'java-amplifier-emitter-size')
    with zipfile.ZipFile(destination) as archive:
        require(archive.testzip() is None, 'java-amplifier-emitter-crc')
    require(file_identity(source)['sha256'] == 'sha256:' + PLATFORM_SHA256,
        'java-amplifier-platform-unchanged')
    return file_identity(destination)


def observed_sources() -> list[Path]:
    paths = (CONTROL, SPLIT, PLUGIN, WORKER, MATH, MATH_REFERENCE, FINDER, LOCK, VERIFICATION, ROOT / 'tools/toolchain.toml',
        ROOT / 'sdk/java-guest/tools/dependencies.py', ROOT / 'sdk/java-guest/tools/feasibility.py',
        ROOT / 'tools/java_guest/coroutine_patch.py', ROOT / 'tools/java_guest/compiler.py',
        ROOT / 'tools/qualify_java_checkpoint_context.py', ROOT / 'tools/qualify_java_fibers.py',
        ROOT / 'tools/rust_capsule_project.py', ROOT / 'tools/rust_capsule_build.py',
        ROOT / 'tools/phase2_operator_process.py', ROOT / 'tools/phase3_resource_identity.py',
        ROOT / 'tools/phase3_resource_profile.py', ROOT / 'tools/build_process.py',
        ROOT / 'tools/build_process_linux.py', ROOT / 'tools/build_process_windows.py',
        ROOT / 'tools/build_process_signals.py', ROOT / 'tools/build_snapshot.py',
        ROOT / 'tools/build_observation.py', ROOT / 'tools/stage_runtime_wit.py',
        ROOT / 'tools/dev_workflow/common.py', ROOT / 'tools/java_guest/bindings.py',
        ROOT / 'tools/java_guest/c.py', ROOT / 'tools/java_guest/java.py',
        ROOT / 'tools/java_guest/async_imports.py', ROOT / 'tools/java_guest/model.py',
        ROOT / 'tools/java_guest/surface.py', ROOT / 'tools/java_guest/sdk.py',
        ROOT / 'tools/java_guest/c_failure_context.py', ROOT / 'tools/java_guest/reachability.py',
        Path(__file__).resolve())
    require(len(paths) == len(set(paths)), 'java-amplifier-source-duplicates')
    return list(paths)


def check_result(mode: str, output: bytes) -> dict:
    require(mode in MODES, 'java-amplifier-control-mode')
    require(len(output) <= 512, 'java-amplifier-control-marker')
    try:
        text = output.decode('ascii')
    except UnicodeDecodeError:
        raise WorkflowError('java-amplifier-control-marker') from None
    expected = re.fullmatch(r'CHECKPOINT_AMPLIFIER_PROBE ' + re.escape(mode)
        + r' PASS generated=(true|false) outputFiles=(\d+) outputBytes=(\d+)\n'
        + r'CHECKPOINT_AMPLIFIER_SPLIT PASS ' + re.escape(mode) + r'\n', text)
    require(expected is not None, 'java-amplifier-control-marker')
    generated = expected.group(1) == 'true'
    files, size = int(expected.group(2)), int(expected.group(3))
    require(generated == (mode in POSITIVE), 'java-amplifier-control-verdict')
    require(0 < files < 100000 and 0 < size <= 64 * 1024 * 1024 if generated
        else files == 0 and size == 0, 'java-amplifier-control-output-bound')
    return {'mode': mode, 'generatedC': generated, 'files': files, 'bytes': size}


def prepare_plugin_model(model: Path, destination: Path) -> Path:
    """Enable the test plugin only in a fresh copy of the compiled control model."""
    shutil.copytree(model, destination)
    services = destination / 'META-INF/services'
    services.mkdir(parents=True)
    descriptor = services / 'org.teavm.vm.spi.TeaVMPlugin'
    descriptor.write_text('org.teavm.platform.plugin.AmplifierPluginControl\n', encoding='utf-8')
    return descriptor


def qualify(output: Path, read_only_cache: Path | None = None) -> dict:
    output = fresh(output)
    sources = observed_sources()
    before = {p.relative_to(ROOT).as_posix(): file_identity(p) for p in sources}
    report = {'schemaVersion': 'latent.java.amplifier-compiler-control.v1', 'status': 'started',
        'scope': 'pinned-split-loader-c-frontend', 'componentExecutionPerformed': False,
        'guestExecutionPerformed': False, 'compilerSources': before, 'controls': []}
    commands = None
    try:
        started = time.monotonic()
        lock = json.loads(read_file(LOCK))
        if read_only_cache is None:
            cache = output / 'model-cache'
            cache.mkdir()
            acquire(cache, lock, started + 180)
        else:
            cache = read_only_cache.resolve(strict=True)
        tooling, identities = locked_model_classpath(SimpleNamespace(sdk=SDK, directory=output,
            dependency_cache=cache), include_platform=True, include_dependency_analysis=True)
        java, javac = (Path(shutil.which(name)).resolve(strict=True) for name in ('java', 'javac'))
        require(java.parent == javac.parent, 'java-amplifier-one-jdk')
        commands = Commands(ROOT, fresh(output / 'commands'), os.environ.copy(),
            deadline_seconds=600, command_seconds=90)
        version = commands.run('jdk-version', java, '--version').decode()
        pins = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml').decode())
        source_module(SDK / 'tools/feasibility.py').verify_version('java-version', version, pins['sdk']['java'])
        model = output / 'model'
        model.mkdir()
        commands.run('compile-control', javac, '--release', '25', '-proc:none', '-encoding', 'UTF-8',
            '-cp', tooling, '-d', model, CONTROL, SPLIT, PLUGIN, WORKER, MATH, MATH_REFERENCE)
        reference = commands.run('math-initializer-reference', java, '-Xmx256m',
            '-cp', str(model) + os.pathsep + tooling,
            'dev.latent.guest.runtime.compiler.MathInitializationReference')
        require(reference == b'MATH_INITIALIZER_REFERENCE PASS 64\n', 'java-amplifier-math-reference')
        report['mathInitializerReference'] = {'scope': 'jvm-only-pinned-jcl-and-jdk-arithmetic',
            'valuesChecked': 64, 'passed': True}
        plugin_model = output / 'plugin-model'
        report['pluginServiceProvider'] = file_identity(prepare_plugin_model(model, plugin_model))
        corrected = output / 'corrected'
        corrected.mkdir()
        finder = output / 'AsyncMethodFinder.java'
        finder.write_bytes(corrected_async_source(read_file(FINDER)))
        commands.run('compile-finder', javac, '--release', '11', '-proc:none', '-g:none', '-encoding', 'UTF-8',
            '-cp', tooling, '-d', corrected, finder)
        compiled = {p.relative_to(corrected).as_posix() for p in corrected.rglob('*') if p.is_file()}
        require(compiled == ASYNC_CLASSES, 'java-amplifier-finder-class-closure')
        jars = tooling.split(os.pathsep)
        core = [Path(p) for p in jars if Path(p).name == 'teavm-core-0.15.0.jar']
        platform = [Path(p) for p in jars if Path(p).name == 'teavm-platform-0.15.0.jar']
        require(len(core) == len(platform) == 1, 'java-amplifier-exact-compiler-jars')
        patched = output / 'teavm-core-context-probe.jar'
        report['overlay'] = overlay(core[0], corrected, patched)
        report['compilerInputs'] = retain_compiler_inputs(output, tooling, sources, finder)
        altered = output / 'altered' / platform[0].name
        altered.parent.mkdir()
        report['tamperedEmitterArchive'] = alter_emitter(platform[0], altered)
        selected = [str(patched) if p == str(core[0]) else p for p in jars]
        for mode in MODES:
            inputs = [str(altered) if mode == 'tampered' and p == str(platform[0]) else p for p in selected]
            selected_model = plugin_model if mode.startswith('plugin-') else model
            result = commands.run('amplifier-' + mode, java, '-Xmx512m', '-cp', selected_model,
                'AmplifierSplitLauncher', mode, selected_model, os.pathsep.join(inputs))
            report['controls'].append(check_result(mode, result))
        after = {p.relative_to(ROOT).as_posix(): file_identity(p) for p in sources}
        require(after == before, 'java-amplifier-source-drift')
        _, final_identities = locked_model_classpath(SimpleNamespace(sdk=SDK, directory=output,
            dependency_cache=cache), include_platform=True, include_dependency_analysis=True)
        require(final_identities == identities, 'java-amplifier-tooling-drift')
        report.update(status='passed', compilerJars=identities, sourceUnchanged=True)
        return report
    finally:
        if report['status'] != 'passed':
            report['status'] = 'failed'
        if commands is not None:
            write_json(output / 'commands.json', commands.records)
        write_json(output / 'result.json', report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--read-only-cache', type=Path)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output, args.read_only_cache), sort_keys=True))


if __name__ == '__main__':
    main()

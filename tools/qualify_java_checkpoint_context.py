"""Bounded JVM compiler-context and real TeaVM C-frontend progress controls.

The real frontend stops after the owning finder. No C output, guest/component
compiler, native host, signing or runtime replay runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
import tomllib
from types import SimpleNamespace
import urllib.request
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_guest.compiler import source_module
from tools.java_guest.coroutine_patch import ASYNC_CLASSES, corrected_async_source, jar_entries, MAX_JAR_BYTES
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_fibers import locked_model_classpath
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

SDK = ROOT/'sdk/java-guest'
CONTROL = SDK/'fibers/conformance/compiler/CheckpointContextControl.java'
COMPILER_CONTROL = SDK/'fibers/conformance/compiler/CheckpointCompilerControl.java'
# Include the core POM's complete runtime closure for the real dependency analyzer,
# including extension-spi's API/util dependencies, not only javac's model surface.
NAMES = frozenset(('teavm-classlib', 'teavm-core', 'teavm-extension-apis',
    'teavm-extension-spi', 'teavm-extension-spi-util', 'teavm-interop', 'teavm-metaprogramming-api',
    'teavm-platform', 'teavm-relocated-libs-asm', 'teavm-relocated-libs-asm-analysis',
    'teavm-relocated-libs-asm-commons', 'teavm-relocated-libs-asm-tree', 'teavm-relocated-libs-asm-util',
    'teavm-relocated-libs-hppc', 'teavm-relocated-libs-rhino'))
EXPECTED = (';direct;multihop;shared;virtual;class-unmanaged;managed-cycle;pinned-managed-entry;altered-entry-negatives;'
    'unresolved;bound;real-late-completion')
COMPILER_EXPECTED = (';finite;initializer;unmanaged;managed;recursion;runtime-initializer;'
    'class-object-helper;string-copy-body')


def selected(lock):
    dependencies = source_module(SDK/'tools/dependencies.py')
    dependencies.verify_inventory({'artifacts': []}, lock, SDK/'feasibility/gradle/verification-metadata.xml')
    rows = [row for row in lock['artifacts']
        if row['path'].startswith('org/teavm/') and Path(row['path']).parts[-3] in NAMES]
    require(len(rows) == len(NAMES) and {Path(row['path']).parts[-3] for row in rows} == NAMES
        and sum(row['size'] for row in rows) <= 32*1024**2, 'java-checkpoint-model-closure')
    return rows


def acquire(cache, lock, deadline):
    """Fixed registry, one attempt per exact locked JAR, finite bytes and deadline."""
    for row in selected(lock):
        require(time.monotonic() < deadline, 'java-checkpoint-model-acquisition-deadline')
        parts = Path(row['path']).parts
        path = cache/'.'.join(parts[:-3])/parts[-3]/parts[-2]/row['sha256']/parts[-1]
        url = lock['maven']+row['path']
        with urllib.request.urlopen(url, timeout=min(20, deadline-time.monotonic())) as response:
            require(response.geturl() == url, 'java-checkpoint-model-registry-redirect')
            raw = response.read(row['size']+1)
        require(time.monotonic() < deadline and len(raw) == row['size']
            and hashlib.sha256(raw).hexdigest() == row['sha256'], 'java-checkpoint-model-jar-identity')
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open('xb') as stream:
            stream.write(raw)


def overlay(core, classes, target):
    """Keep the real pinned Fiber in the same measured JAR as the three changed classes."""
    original_identity = file_identity(core)
    before = jar_entries(core)
    replacements = {p.relative_to(classes).as_posix(): read_file(p, 1024**2)
        for p in classes.rglob('*') if p.is_file()}
    require(set(replacements) == ASYNC_CLASSES and all(raw.startswith(b'\xca\xfe\xba\xbe')
        for raw in replacements.values()), 'java-checkpoint-overlay-class-closure')
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as output:
        for name, raw in sorted(before.items()):
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            output.writestr(entry, replacements.get(name, raw))
    after = jar_entries(target)
    require(set(after) == set(before) and all(after[name] == raw
        for name, raw in before.items() if name not in ASYNC_CLASSES)
        and all(after[name] == raw for name, raw in replacements.items())
        and file_identity(core) == original_identity, 'java-checkpoint-overlay-nonreplacement-identity')
    fiber = before['org/teavm/runtime/Fiber.class']
    require(0 < len(fiber) <= 128*1024 and target.stat().st_size <= MAX_JAR_BYTES,
        'java-checkpoint-overlay-original-fiber-bound')
    return {'originalCore': original_identity, 'selectedCore': file_identity(target),
        'replacedClasses': sorted(ASYNC_CLASSES), 'unchangedEntries': len(before)-len(ASYNC_CLASSES),
        'unchangedFiberClass': {'bytes': len(fiber), 'sha256': hashlib.sha256(fiber).hexdigest()}}


def retain_compiler_inputs(output, tooling, observed, corrected_source):
    """Retain only fixed, public compiler inputs for an offline fixture replay."""
    entries = {str(p.relative_to(ROOT)): p for p in observed}
    entries['generated/AsyncMethodFinder.java'] = corrected_source
    for name in tooling.split(os.pathsep):
        path = Path(name)
        key = 'jars/' + path.name
        require(key not in entries, 'java-checkpoint-reproducer-duplicate')
        entries[key] = path
    require(len(entries) <= 64, 'java-checkpoint-reproducer-entry-bound')
    target = output/'commands/logs/compiler-inputs.zip'
    total = 0
    with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, path in sorted(entries.items()):
            raw = read_file(path, 32*1024**2)
            total += len(raw)
            require(total <= 34*1024**2, 'java-checkpoint-reproducer-byte-bound')
            entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            entry.compress_type = zipfile.ZIP_DEFLATED
            entry.external_attr = 0o100644 << 16
            archive.writestr(entry, raw)
    return file_identity(target)


def qualify(output):
    started = time.monotonic()
    output = fresh(output)
    cache = output/'model-cache';cache.mkdir()
    sources = sorted((SDK/'fibers/compiler/dev/latent/guest/runtime/compiler').glob('*.java'))
    raw_finder = SDK/'fibers/compiler-patch/AsyncMethodFinder.java'
    observed = [*sources, CONTROL, COMPILER_CONTROL, raw_finder, ROOT/'tools/java_guest/coroutine_patch.py',
        Path(__file__).resolve(), ROOT/'tools/tests/test_java_checkpoint_context.py',
        ROOT/'tools/tests/test_java_checkpoint_compiler.py', SDK/'feasibility/dependencies.lock.json',
        SDK/'feasibility/gradle/verification-metadata.xml']
    before = {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed}
    report = {'status': 'started', 'scope': 'jvm-only-compiler-control',
        'componentExecutionPerformed': False, 'nativeExecutionPerformed': False,
        'compilerSources': before}
    commands = None
    try:
        lock = json.loads(read_file(SDK/'feasibility/dependencies.lock.json'))
        acquire(cache, lock, started+180)
        tooling, identities = locked_model_classpath(SimpleNamespace(sdk=SDK, directory=output,
            dependency_cache=cache), include_platform=True, include_dependency_analysis=True)
        java, javac = (Path(shutil.which(name)).resolve(strict=True) for name in ('java', 'javac'))
        require(java.parent == javac.parent, 'java-checkpoint-one-jdk')
        remaining = int(started+300-time.monotonic())
        require(remaining >= 60, 'java-checkpoint-probe-deadline')
        commands = Commands(ROOT, fresh(output/'commands'), os.environ.copy(),
            deadline_seconds=remaining, command_seconds=60)
        commands.run('checkpoint-context-source-controls', sys.executable, '-B', '-m', 'unittest',
            'tools.tests.test_java_checkpoint_context', 'tools.tests.test_java_checkpoint_compiler')
        version = commands.run('checkpoint-context-jdk', java, '--version').decode()
        pins = tomllib.loads(read_file(ROOT/'tools/toolchain.toml').decode())
        source_module(SDK/'tools/feasibility.py').verify_version('java-version', version, pins['sdk']['java'])
        model = output/'model';model.mkdir()
        commands.run('checkpoint-context-control-compile', javac, '--release', '25', '-proc:none',
            '-encoding', 'UTF-8', '-cp', tooling, '-d', model, *sources, CONTROL, COMPILER_CONTROL)
        corrected = output/'corrected';corrected.mkdir()
        source = output/'AsyncMethodFinder.java'
        source.write_bytes(corrected_async_source(read_file(raw_finder)))
        commands.run('checkpoint-context-finder-compile', javac, '--release', '11', '-proc:none',
            '-g:none', '-encoding', 'UTF-8', '-cp', tooling, '-d', corrected, source)
        compiled = {p.relative_to(corrected).as_posix(): file_identity(p)
            for p in corrected.rglob('*') if p.is_file()}
        require(set(compiled) == ASYNC_CLASSES, 'java-checkpoint-unchanged-finder-class-closure')
        core = [p for p in tooling.split(os.pathsep) if Path(p).name == 'teavm-core-0.15.0.jar']
        require(len(core) == 1, 'java-checkpoint-exact-original-core')
        replacement = output/'teavm-core-context-probe.jar'
        replacement_identity = overlay(Path(core[0]), corrected, replacement)
        report['compilerInputs'] = retain_compiler_inputs(output, tooling, observed, source)
        results = []
        compiler_results = []
        # Retain partial observations if a later real compiler control refuses.
        report.update(controls=results, compilerControls=compiler_results)
        for mode, origin in (('original', core[0]), ('corrected', replacement)):
            selected_tooling = [str(origin), *[p for p in tooling.split(os.pathsep) if p != core[0]]]
            classpath = os.pathsep.join([str(model), *selected_tooling])
            result = commands.run('checkpoint-context-'+mode, java, '-Xmx256m', '-cp', classpath,
                'org.teavm.dependency.CheckpointContextControl', mode, origin).decode().strip()
            require(result == 'CHECKPOINT_CONTEXT_CONTROL PASS '+mode+EXPECTED, 'java-checkpoint-context-control')
            results.append({'mode': mode, 'result': result})
            compiler_result = commands.run('checkpoint-compiler-'+mode, java, '-Xmx256m', '-cp', classpath,
                'org.teavm.dependency.CheckpointCompilerControl', mode).decode().strip()
            require(compiler_result == 'CHECKPOINT_COMPILER_CONTROL PASS '+mode+COMPILER_EXPECTED,
                'java-checkpoint-real-compiler-control')
            compiler_results.append({'mode': mode, 'result': compiler_result})
        require(before == {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed},
            'java-checkpoint-source-unchanged')
        report.update(status='passed', lockedModelJars=identities,
            finderClasses=compiled, correctedSource=file_identity(source), compilerOverlay=replacement_identity,
            jdk={'java': file_identity(java), 'javac': file_identity(javac), 'version': version})
    except Exception:
        report['status'] = 'failed'
        raise
    finally:
        if commands is not None:
            write_json(output/'commands.json', commands.records)
        write_json(output/'result.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    qualify(parser.parse_args().output)

"""Focused, source-bound JVM control of the pinned Java event queue.

This does not build or run a component and cannot qualify the guest or the
historical intermittent timer trap. All model JARs use the existing lock.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
import tomllib
from types import SimpleNamespace

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.java_guest.compiler import source_module
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_checkpoint_context import acquire
from tools.qualify_java_fibers import locked_model_classpath
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

SDK = ROOT / 'sdk/java-guest'
HEAP = ('QUEUE_HEAP_CONTROL PASS actual-original-regression;actual-corrected-order;'
        'up;down;ties;root;single-child;signed-min;last;singleton;empty;missing;repeat;model;'
        'preimage-negative;repeat-negative;donor-body-negative;donor-layout-negative;donor-node-negative')
CLOCK = ('QUEUE_DEADLINE_MODEL_CONTROL PASS actual-locked-queue;first-sample-delays;'
         'second-sample-comparison;owned-clock-hooks=2;negative-shapes=4')


def loaded_repo_sources() -> set[Path]:
    """Capture every repository Python module already loaded by the owner."""
    files = set()
    for module in list(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if not isinstance(name, str):
            continue
        path = Path(name)
        if not path.is_file() or path.is_symlink():
            continue
        path = path.resolve(strict=True)
        if path.suffix == '.py' and path.is_relative_to(ROOT):
            files.add(path)
    return files


def qualify(output: Path) -> dict:
    started = time.monotonic()
    output = fresh(output)
    cache = output / 'model-cache'
    cache.mkdir()
    sources = sorted((SDK / 'fibers/compiler/dev/latent/guest/runtime/compiler').glob('*.java'))
    sources += [SDK / 'fibers/dev/latent/guest/runtime/EventQueueHeapDonor.java',
                SDK / 'fibers/conformance/compiler/QueueHeapControl.java',
                SDK / 'fibers/conformance/compiler/QueueDeadlineModelControl.java']
    # source_module executes these two SDK helpers outside sys.modules. The
    # process platform helpers may also be imported only when a command starts.
    helper_paths = ('tools/qualify_java_fibers.py', 'tools/qualify_java_checkpoint_context.py',
        'tools/java_guest/compiler.py', 'tools/java_guest/coroutine_patch.py',
        'tools/phase2_operator_process.py', 'tools/phase3_resource_identity.py',
        'tools/phase3_resource_profile.py', 'tools/rust_capsule_build.py',
        'tools/rust_capsule_project.py', 'tools/build_observation.py', 'tools/build_process.py',
        'tools/build_process_linux.py', 'tools/build_process_windows.py', 'tools/build_process_signals.py',
        'tools/requirements.lock', 'tools/toolchain.toml', '.github/workflows/java-guest-feasibility.yml',
        'sdk/java-guest/tools/dependencies.py', 'sdk/java-guest/tools/feasibility.py',
        'sdk/java-guest/feasibility/dependencies.lock.json',
        'sdk/java-guest/feasibility/gradle/verification-metadata.xml')
    observed = sorted({*sources, Path(__file__).resolve(), *(ROOT / name for name in helper_paths)}
                      | loaded_repo_sources())
    require(len(observed) <= 512, 'java-queue-heap-source-count')
    before = {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed}
    report = {'status': 'started', 'scope': 'pinned-jvm-queue-and-compiler-model-only',
              'componentExecutionPerformed': False, 'nativeExecutionPerformed': False,
              'guestQualificationPerformed': False, 'sourceInputs': before}
    commands = None
    try:
        lock = json.loads(read_file(SDK / 'feasibility/dependencies.lock.json'))
        acquire(cache, lock, started + 180)
        tooling, identities = locked_model_classpath(SimpleNamespace(sdk=SDK, directory=output,
            dependency_cache=cache), include_platform=True, include_dependency_analysis=True)
        java, javac = (Path(shutil.which(name)).resolve(strict=True) for name in ('java', 'javac'))
        require(java.parent == javac.parent, 'java-queue-heap-one-jdk')
        remaining = int(started + 300 - time.monotonic())
        require(remaining >= 60, 'java-queue-heap-deadline')
        commands = Commands(ROOT, fresh(output / 'commands'), os.environ.copy(),
                            deadline_seconds=remaining, command_seconds=60)
        version = commands.run('queue-heap-jdk', java, '--version').decode()
        pins = tomllib.loads(read_file(ROOT / 'tools/toolchain.toml').decode())
        source_module(SDK / 'tools/feasibility.py').verify_version('java-version', version, pins['sdk']['java'])
        model = output / 'model'
        model.mkdir()
        commands.run('queue-heap-compile', javac, '--release', '25', '-proc:none',
                     '-encoding', 'UTF-8', '-cp', tooling, '-d', model, *sources)
        cp = str(model) + os.pathsep + tooling
        heap = commands.run('queue-heap-control', java, '-Xmx256m', '-cp', cp,
                            'dev.latent.guest.runtime.compiler.QueueHeapControl').decode().strip()
        require(heap == HEAP, 'java-queue-heap-control')
        clock = commands.run('queue-clock-control', java, '-Xmx256m', '-cp', cp,
                             'dev.latent.guest.runtime.compiler.QueueDeadlineModelControl').decode().strip()
        require(clock == CLOCK, 'java-queue-clock-control')
        require(loaded_repo_sources() <= set(observed), 'java-queue-heap-unobserved-helper')
        after = {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed}
        require(after == before, 'java-queue-heap-inputs-changed')
        report.update(status='passed-jvm-only', jarDigests=identities,
                      heapControl=heap, clockControl=clock, checkedInputs=after)
        return report
    except BaseException as error:
        report.update(status='failed', errorType=type(error).__name__)
        raise
    finally:
        if commands is not None:
            write_json(output / 'commands.json', commands.records)
        write_json(output / 'result.json', report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    qualify(args.output)


if __name__ == '__main__':
    main()

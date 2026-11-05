"""Run the actual pinned TeaVM plugin on a reachable single-block loop.

This JVM-only model does not execute a guest, native host or signed component.
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

from tools import qualify_java_checkpoint_context as checkpoint
from tools.java_guest.compiler import source_module
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_fibers import locked_model_classpath
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

SDK = ROOT/'sdk/java-guest'
CONTROL = SDK/'fibers/conformance/compiler/SelfLoopCheckpointControl.java'


def loaded_project_sources():
    root = ROOT.resolve(strict=True)
    selected = set()
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if not name: continue
        path = Path(name).resolve()
        if path.suffix == '.py' and path.is_relative_to(root): selected.add(path)
    require(len(selected) <= 512, 'java-self-loop-loaded-module-bound')
    return selected


def qualify(output):
    started = time.monotonic()
    output = fresh(output)
    cache = output/'model-cache'; cache.mkdir()
    compiler = sorted((SDK/'fibers/compiler/dev/latent/guest/runtime/compiler').glob('*.java'))
    sdk_tools = sorted((SDK/'tools').glob('*.py'))
    generator = sorted((ROOT/'tools/java_guest').glob('*.py'))
    observed = [*compiler, *sdk_tools, *generator, CONTROL, Path(__file__).resolve(),
        SDK/'fibers/conformance/compiler/DependencyCheckpointControl.java',
        SDK/'feasibility/dependencies.lock.json', SDK/'feasibility/gradle/verification-metadata.xml',
        ROOT/'tools/toolchain.toml', ROOT/'tools/requirements.lock',
        ROOT/'tools/qualify_java_checkpoint_context.py', ROOT/'tools/qualify_java_fibers.py',
        ROOT/'tools/phase2_operator_process.py', ROOT/'tools/phase3_resource_identity.py',
        ROOT/'tools/rust_capsule_project.py', ROOT/'tools/rust_capsule_build.py',
        ROOT/'.github/workflows/java-network-integrated-control.yml']
    require(len(observed) == len(set(observed)), 'java-self-loop-unique-inputs')
    observed = sorted(set(observed) | loaded_project_sources())
    before = {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed}
    report = {'status': 'started', 'scope': 'jvm-pinned-plugin-model-only',
        'componentExecutionPerformed': False, 'nativeExecutionPerformed': False,
        'sourceInputs': before}
    commands = None
    try:
        lock = json.loads(read_file(SDK/'feasibility/dependencies.lock.json'))
        checkpoint.acquire(cache, lock, started+180)
        tooling, identities = locked_model_classpath(SimpleNamespace(sdk=SDK, directory=output,
            dependency_cache=cache), include_platform=True, include_dependency_analysis=True)
        java_name, javac_name = shutil.which('java'), shutil.which('javac')
        require(java_name is not None and javac_name is not None, 'java-self-loop-jdk')
        java, javac = Path(java_name).resolve(strict=True), Path(javac_name).resolve(strict=True)
        require(java.parent == javac.parent, 'java-self-loop-one-jdk')
        remaining = int(started+300-time.monotonic())
        require(remaining >= 60, 'java-self-loop-deadline')
        commands = Commands(ROOT, fresh(output/'commands'), os.environ.copy(),
            deadline_seconds=remaining, command_seconds=90)
        version = commands.run('self-loop-jdk', java, '--version').decode()
        pins = tomllib.loads(read_file(ROOT/'tools/toolchain.toml').decode())
        source_module(SDK/'tools/feasibility.py').verify_version('java-version', version, pins['sdk']['java'])
        model = output/'model'; model.mkdir()
        commands.run('self-loop-compile', javac, '--release', '25', '-proc:none', '-encoding', 'UTF-8',
            '-cp', tooling, '-d', model, *compiler, CONTROL)
        result = commands.run('self-loop-model', java, '-Xmx256m', '-cp', str(model)+os.pathsep+tooling,
            'dev.latent.guest.runtime.compiler.SelfLoopCheckpointControl').decode().strip()
        prefix = ('SELF_LOOP_CONTROL PASS synthetic-single;reachable-only;deduplicated;unselected;'
            'unmanaged;initializer;real-java-loop;real-java-self-edge=')
        require(result in {prefix+'0;GUEST_QUALIFICATION=pending', prefix+'1;GUEST_QUALIFICATION=pending'},
            'java-self-loop-model-verdict')
        require(loaded_project_sources().issubset(set(observed)), 'java-self-loop-late-project-import')
        require(before == {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed},
            'java-self-loop-source-unchanged')
        report.update(status='passed', lockedModelJars=identities, result=result,
            jdk={'java': file_identity(java), 'javac': file_identity(javac), 'version': version})
    except Exception:
        report['status'] = 'failed'
        raise
    finally:
        if commands is not None: write_json(output/'commands.json', commands.records)
        write_json(output/'result.json', report)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    qualify(parser.parse_args().output)

"""Capture the fixed SDK owned-input callback from the pinned TeaVM C frontend.

This emits bounded C text on the JVM only. It does not compile or execute C,
a component, a native host or network operations.
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
from tools.java_guest.coroutine_patch import ASYNC_CLASSES, corrected_async_source
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_fibers import locked_model_classpath
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

SDK = ROOT/'sdk/java-guest'
CONTROL = SDK/'tests/network/NetworkFrontendControl.java'


def loaded_project_sources():
    # Include the actual imported repository helper closure, not only the
    # top-level owner. SDK helpers loaded through source_module are listed
    # separately because that loader intentionally avoids sys.modules.
    root = ROOT.resolve(strict=True)
    selected = set()
    for module in tuple(sys.modules.values()):
        name = getattr(module, '__file__', None)
        if not name: continue
        path = Path(name).resolve()
        if path.suffix == '.py' and path.is_relative_to(root): selected.add(path)
    require(len(selected) <= 512, 'network-frontend-loaded-module-bound')
    return selected


def qualify(output):
    started = time.monotonic()
    output = fresh(output)
    cache = output/'model-cache'; cache.mkdir()
    compiler = sorted((SDK/'fibers/compiler/dev/latent/guest/runtime/compiler').glob('*.java'))
    generator = sorted((ROOT/'tools/java_guest').glob('*.py'))
    sdk_tools = sorted((SDK/'tools').glob('*.py'))
    raw_finder = SDK/'fibers/compiler-patch/AsyncMethodFinder.java'
    observed = [*compiler, *generator, *sdk_tools, CONTROL, raw_finder, Path(__file__).resolve(),
        SDK/'fibers/io/dev/latent/guest/runtime/HostCalls.java',
        SDK/'runtime/dev/latent/guest/Wire.java', SDK/'runtime/dev/latent/guest/Resource.java',
        SDK/'feasibility/dependencies.lock.json', SDK/'feasibility/gradle/verification-metadata.xml',
        ROOT/'tools/toolchain.toml', ROOT/'tools/requirements.lock',
        ROOT/'tools/qualify_java_checkpoint_context.py', ROOT/'tools/qualify_java_fibers.py',
        ROOT/'tools/phase2_operator_process.py', ROOT/'tools/phase3_resource_identity.py',
        ROOT/'tools/rust_capsule_project.py', ROOT/'tools/rust_capsule_build.py',
        ROOT/'.github/workflows/java-network-frontend-diagnostic.yml']
    require(len(observed) == len(set(observed)), 'network-frontend-unique-inputs')
    observed = sorted(set(observed) | loaded_project_sources())
    before = {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed}
    report = {'status': 'started', 'scope': 'fixed-sdk-callback-c-text-only',
        'componentExecutionPerformed': False, 'nativeExecutionPerformed': False,
        'socketExecutionPerformed': False, 'sourceInputs': before, 'captures': []}
    commands = None
    try:
        lock = json.loads(read_file(SDK/'feasibility/dependencies.lock.json'))
        checkpoint.acquire(cache, lock, started+180)
        tooling, identities = locked_model_classpath(SimpleNamespace(sdk=SDK, directory=output,
            dependency_cache=cache), include_platform=True, include_dependency_analysis=True)
        java_name, javac_name = shutil.which('java'), shutil.which('javac')
        require(java_name is not None and javac_name is not None, 'network-frontend-jdk')
        java, javac = Path(java_name).resolve(strict=True), Path(javac_name).resolve(strict=True)
        require(java.parent == javac.parent, 'network-frontend-one-jdk')
        remaining = int(started+300-time.monotonic())
        require(remaining >= 60, 'network-frontend-deadline')
        commands = Commands(ROOT, fresh(output/'commands'), os.environ.copy(),
            deadline_seconds=remaining, command_seconds=90)
        version = commands.run('network-frontend-jdk', java, '--version').decode()
        pins = tomllib.loads(read_file(ROOT/'tools/toolchain.toml').decode())
        source_module(SDK/'tools/feasibility.py').verify_version('java-version', version, pins['sdk']['java'])
        model = output/'model'; model.mkdir()
        stubs = output/'stubs'
        binding = stubs/'dev/latent/generated/Bindings.java'; binding.parent.mkdir(parents=True)
        binding.write_text('package dev.latent.generated; import dev.latent.guest.Wire; public final class Bindings {'
            ' public enum LatentRuntimeActivationOwnerKind { Wait } public static final class BorrowPermit {'
            ' public int direction() { return 0; } public boolean authorizes(Wire.HostFunction f, int n) { return false; } } }\n',
            encoding='utf-8')
        activation = stubs/'dev/latent/guest/runtime/Activation.java'; activation.parent.mkdir(parents=True)
        activation.write_text('package dev.latent.guest.runtime; import dev.latent.generated.Bindings;'
            ' public final class Activation { public static void checkpoint() { }'
            ' public static Lease owner(Bindings.LatentRuntimeActivationOwnerKind k) { return new Lease(); }'
            ' public static final class Lease { public void close() { } } }\n', encoding='utf-8')
        commands.run('network-frontend-model-compile', javac, '--release', '25', '-proc:none', '-encoding', 'UTF-8',
            '-cp', tooling, '-d', model, *compiler, CONTROL, SDK/'fibers/io/dev/latent/guest/runtime/HostCalls.java',
            SDK/'runtime/dev/latent/guest/Wire.java', SDK/'runtime/dev/latent/guest/Resource.java', binding, activation)
        corrected = output/'corrected'; corrected.mkdir()
        finder = output/'AsyncMethodFinder.java'; finder.write_bytes(corrected_async_source(read_file(raw_finder)))
        commands.run('network-frontend-finder-compile', javac, '--release', '11', '-proc:none', '-g:none',
            '-encoding', 'UTF-8', '-cp', tooling, '-d', corrected, finder)
        compiled = {p.relative_to(corrected).as_posix(): file_identity(p)
            for p in corrected.rglob('*') if p.is_file()}
        require(set(compiled) == ASYNC_CLASSES, 'network-frontend-finder-closure')
        core = [p for p in tooling.split(os.pathsep) if Path(p).name == 'teavm-core-0.15.0.jar']
        require(len(core) == 1, 'network-frontend-exact-original-core')
        replacement = output/'teavm-core-network-probe.jar'
        overlay = checkpoint.overlay(Path(core[0]), corrected, replacement)
        for mode, origin in (('original', core[0]), ('corrected', replacement)):
            selected = [str(origin), *[p for p in tooling.split(os.pathsep) if p != core[0]]]
            classpath = os.pathsep.join([str(model), *selected])
            captured = output/(mode+'-owned-callback.c')
            result = commands.run('network-frontend-'+mode, java, '-Xmx256m', '-cp', classpath,
                'dev.latent.guest.runtime.compiler.NetworkFrontendControl', mode, captured).decode().strip()
            require(result == 'NETWORK_FRONTEND_CAPTURE '+mode
                +';actual-sdk-callback;locked-ctarget;COMPONENT_QUALIFICATION=pending',
                'network-frontend-capture-marker')
            report['captures'].append({'mode': mode, 'file': file_identity(captured)})
        require(loaded_project_sources().issubset(set(observed)), 'network-frontend-late-project-import')
        require(before == {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed},
            'network-frontend-source-unchanged')
        report.update(status='captured', lockedModelJars=identities, compilerOverlay=overlay,
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

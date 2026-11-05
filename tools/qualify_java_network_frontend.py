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

from tools import qualify_java_checkpoint_context as checkpoint, stage_runtime_wit
from tools.java_guest import bindings
from tools.java_guest.model import Graph
from tools.java_guest.compiler import source_module
from tools.java_guest.coroutine_patch import ASYNC_CLASSES, corrected_async_source
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_fibers import locked_model_classpath
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, fresh, read_file, write_json

SDK = ROOT/'sdk/java-guest'
CONTROL = SDK/'tests/network/NetworkFrontendControl.java'
WORLD = SDK/'tests/network/frontend/world.wit'


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
    runtime = sorted((SDK/'runtime/dev/latent/guest').glob('*.java'))
    platform_wit = sorted((ROOT/'wit/platform').rglob('*.wit'))
    raw_finder = SDK/'fibers/compiler-patch/AsyncMethodFinder.java'
    observed = [*compiler, *generator, *sdk_tools, *runtime, *platform_wit, CONTROL, WORLD, raw_finder, Path(__file__).resolve(),
        SDK/'fibers/io/dev/latent/guest/runtime/HostCalls.java', ROOT/'tools/stage_runtime_wit.py',
        SDK/'feasibility/dependencies.lock.json', SDK/'feasibility/gradle/verification-metadata.xml',
        ROOT/'tools/toolchain.toml', ROOT/'tools/requirements.lock',
        ROOT/'tools/qualify_java_checkpoint_context.py', ROOT/'tools/qualify_java_fibers.py',
        ROOT/'tools/phase2_operator_process.py', ROOT/'tools/phase3_resource_identity.py',
        ROOT/'tools/rust_capsule_project.py', ROOT/'tools/rust_capsule_build.py',
        ROOT/'.github/workflows/java-network-frontend-diagnostic.yml']
    require(len(observed) == len(set(observed)), 'network-frontend-unique-inputs')
    observed = sorted(set(observed) | loaded_project_sources())
    before = {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed}
    report = {'status': 'started', 'scope': 'generated-network-wit-and-fixed-sdk-callback-c-text-only',
        'componentExecutionPerformed': False, 'hostRuntimeExecutionPerformed': False,
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
        versions = source_module(SDK/'tools/feasibility.py')
        versions.verify_version('java-version', version, pins['sdk']['java'])
        native_tools = {}
        for name, key in (('wasm-tools', 'wasm-tools'), ('wit-bindgen', 'wit-bindgen-cli')):
            executable = shutil.which(name)
            require(executable is not None, 'network-frontend-' + name)
            binary = Path(executable).resolve(strict=True)
            identity = file_identity(binary)
            selected = commands.run('network-frontend-' + name + '-version', binary, '--version').decode()
            versions.verify_version(name + '-version', selected, pins['contracts'][key])
            native_tools[name] = {'path': str(binary), 'identity': identity, 'version': selected}
        staged = output/'network-wit'
        stage_runtime_wit.stage(staged, WORLD.parent)
        graphs = []
        def bind_run(stage, tool, *arguments):
            text = commands.run('network-frontend-' + stage, tool, *arguments).decode()
            if stage == 'wit-graph': graphs.append(json.loads(text))
            return text
        generated = output/'network-abi'
        binding_inventory = bindings.generate(bind_run, staged, 'service', generated,
            activation_profile=True, fiber_io_profile=True)
        require(len(graphs) == 1, 'network-frontend-one-wit-graph')
        require('Wire.NETWORK_WRITE' in (generated/'Bindings.java').read_text(encoding='utf-8'),
            'network-frontend-generated-write-permit')
        graph = Graph(graphs[0], 'service', (generated/'probe.h').read_text(encoding='utf-8'), async_imports=True)
        matches = [index for index, value in enumerate(graph.data['interfaces'])
            if value.get('name') == 'streams'
            and graph.data['packages'][value['package']]['name'] == 'latent:network@0.1.0']
        require(len(matches) == 1, 'network-frontend-one-network-interface')
        writes = [f for f in graph.imports if f['interface'] == matches[0] and f['name'] == 'write']
        require(len(writes) == 1 and writes[0].get('asyncLowered'), 'network-frontend-async-write')
        bridge = (generated/'bridge.c').read_text(encoding='utf-8')
        begin = bridge.split('void *lsf_java_async_begin', 1)[1].split('int32_t lsf_java_async_state', 1)[0]
        start = begin.index('case ' + str(writes[0]['operation']) + ': {')
        end = begin.find('\ncase ', start + 1)
        write = begin[start:] if end < 0 else begin[start:end]
        dispatch = write.index('call->status = ' + writes[0]['symbol'])
        require(write.index('lsf_finish(&input)') < dispatch
            and write.index('.ptr = lsf_allocate(') < dispatch
            and write.index('lsf_get(&input, 1)') < dispatch,
            'network-frontend-generated-input-copy-before-import')
        generated_before = {p.name: file_identity(p) for p in sorted(generated.iterdir()) if p.is_file()}
        model = output/'model'; model.mkdir()
        stubs = output/'stubs'
        binding = generated/'Bindings.java'
        activation = stubs/'dev/latent/guest/runtime/Activation.java'; activation.parent.mkdir(parents=True)
        activation.write_text('package dev.latent.guest.runtime; import dev.latent.generated.Bindings;'
            ' import org.teavm.interop.Address; public final class Activation { public static void checkpoint() { }'
            ' public static Address invoke(int n, Address p, int l) { return Address.fromInt(0); }'
            ' public static Lease owner(Bindings.LatentRuntimeActivationOwnerKind k) { return new Lease(); }'
            ' public static final class Lease { public void close() { } } }\n', encoding='utf-8')
        capsule = stubs/'dev/latent/app/Capsule.java'; capsule.parent.mkdir(parents=True)
        capsule.write_text('package dev.latent.app; public final class Capsule implements dev.latent.generated.Bindings.Exports {'
            ' public dev.latent.guest.Unit run() { return dev.latent.guest.Unit.VALUE; } }\n', encoding='utf-8')
        commands.run('network-frontend-model-compile', javac, '--release', '25', '-proc:none', '-encoding', 'UTF-8',
            '-cp', tooling, '-d', model, *compiler, *runtime, CONTROL,
            SDK/'fibers/io/dev/latent/guest/runtime/HostCalls.java', binding, activation, capsule)
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
                +';actual-sdk-callback;generated-wit;writer-static-root-and-layout;locked-ctarget;COMPONENT_QUALIFICATION=pending',
                'network-frontend-capture-marker')
            report['captures'].append({'mode': mode, 'file': file_identity(captured)})
        require(loaded_project_sources().issubset(set(observed)), 'network-frontend-late-project-import')
        require(before == {p.relative_to(ROOT).as_posix(): file_identity(p) for p in observed},
            'network-frontend-source-unchanged')
        require(all(file_identity(Path(value['path'])) == value['identity'] for value in native_tools.values()),
            'network-frontend-tools-unchanged')
        require(generated_before == {p.name: file_identity(p) for p in sorted(generated.iterdir()) if p.is_file()},
            'network-frontend-generated-inputs-unchanged')
        report.update(status='captured', lockedModelJars=identities, compilerOverlay=overlay,
            nativeTools=native_tools, bindingInventory=binding_inventory,
            generatedNetworkInputCopyBeforeImport=True,
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

"""Pinned Java/TeaVM ownership and generated WIT controls; no component or host execution."""
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


def qualify(output):
    started = time.monotonic()
    output = fresh(output)
    cache = output/'model-cache'; cache.mkdir()
    compiler = sorted((SDK/'fibers/compiler/dev/latent/guest/runtime/compiler').glob('*.java'))
    generator = sorted((ROOT/'tools/java_guest').glob('*.py'))
    platform_wit = sorted((ROOT/'wit/platform').rglob('*.wit'))
    observed = [*compiler, *generator, *platform_wit, Path(__file__).resolve(),
        SDK/'runtime/dev/latent/guest/Resource.java', SDK/'runtime/dev/latent/guest/Wire.java',
        SDK/'fibers/io/dev/latent/guest/runtime/HostCalls.java',
        SDK/'tests/network/NetworkBorrowControl.java', SDK/'tests/network/NetworkBorrowModelControl.java',
        SDK/'tests/network/NetworkScratchControl.java',
        SDK/'tests/network/world.wit', ROOT/'tools/stage_runtime_wit.py', ROOT/'tools/install_guest_bindgen.py',
        SDK/'tests/test_network_borrow_profile.py', SDK/'tests/test_async_admission.py',
        SDK/'tests/test_wire.py', SDK/'tests/test_bindings.py', SDK/'tests/wire/WireUtf8Control.java',
        SDK/'feasibility/dependencies.lock.json', SDK/'feasibility/gradle/verification-metadata.xml',
        SDK/'tools/dependencies.py', SDK/'tools/feasibility.py', ROOT/'tools/toolchain.toml',
        ROOT/'tools/requirements.lock', ROOT/'.github/workflows/java-guest-feasibility.yml',
        ROOT/'tools/tests/fixtures/typescript_runtime_profile/borrow-void-function.json',
        ROOT/'tools/java_capsule_project.py', ROOT/'tools/qualify_java_checkpoint_context.py',
        ROOT/'tools/qualify_java_fibers.py', ROOT/'tools/phase2_operator_process.py',
        ROOT/'tools/phase3_resource_identity.py', ROOT/'tools/rust_capsule_project.py',
        ROOT/'tools/rust_capsule_build.py']
    require(len(observed) == len(set(observed)), 'java-network-model-unique-inputs')
    before = {path.relative_to(ROOT).as_posix(): file_identity(path) for path in observed}
    report = {'status': 'started', 'scope': 'jvm-locked-teavm-model-and-generated-wit-only',
        'componentExecutionPerformed': False, 'hostRuntimeExecutionPerformed': False,
        'socketExecutionPerformed': False, 'nativeToolExecutionPerformed': True, 'sourceInputs': before}
    commands = None
    try:
        lock = json.loads(read_file(SDK/'feasibility/dependencies.lock.json'))
        checkpoint.acquire(cache, lock, started+180)
        tooling, identities = locked_model_classpath(SimpleNamespace(sdk=SDK, directory=output,
            dependency_cache=cache), include_platform=True, include_dependency_analysis=True)
        java_name, javac_name = shutil.which('java'), shutil.which('javac')
        require(java_name is not None and javac_name is not None, 'java-network-model-jdk')
        java, javac = Path(java_name).resolve(strict=True), Path(javac_name).resolve(strict=True)
        require(java.parent == javac.parent, 'java-network-model-one-jdk')
        remaining = int(started+300-time.monotonic())
        require(remaining >= 60, 'java-network-model-deadline')
        env = os.environ.copy()
        env['LATENT_JAVA_MODEL_CLASSPATH'] = tooling
        env['LATENT_JAVA_NETWORK_BINDGEN'] = '1'
        env['LATENT_JAVA_NETWORK_CAPTURE'] = str(output/'network-abi')
        commands = Commands(ROOT, fresh(output/'commands'), env,
            deadline_seconds=remaining, command_seconds=90)
        version = commands.run('network-model-jdk', java, '--version').decode()
        pins = tomllib.loads(read_file(ROOT/'tools/toolchain.toml').decode())
        versions = source_module(SDK/'tools/feasibility.py')
        versions.verify_version('java-version', version, pins['sdk']['java'])
        native_tools = {}
        for name, key in (('wasm-tools', 'wasm-tools'), ('wit-bindgen', 'wit-bindgen-cli')):
            executable = shutil.which(name)
            require(executable is not None, 'java-network-model-' + name)
            binary = Path(executable).resolve(strict=True)
            identity = file_identity(binary)
            selected = commands.run('network-model-' + name + '-version', binary, '--version').decode()
            versions.verify_version(name + '-version', selected, pins['contracts'][key])
            native_tools[name] = {'path': str(binary), 'identity': identity, 'version': selected}
        for name in ('test_network_borrow_profile.py', 'test_async_admission.py', 'test_wire.py', 'test_bindings.py'):
            result = commands.run('network-model-'+name.removesuffix('.py'), sys.executable, '-B', '-m', 'unittest',
                'discover', '-s', SDK/'tests', '-p', name, '-v')
            if name == 'test_network_borrow_profile.py':
                require(b'NETWORK_BORROW_MODEL PASS actual-resource-and-writer;monitors;no-checkpoints;'
                    b'owned-native-copy-entry;selected-loop-positive;COMPONENT_QUALIFICATION=pending' in result
                    and b'NETWORK_BORROW_CONTROL PASS ' in result
                    and b'NETWORK_SCRATCH_CONTROL PASS exact-call-source;fake-boundaries;' in result
                    and b'NETWORK_BORROW_ABI_CONTROL PASS real-wit-bindgen;copied-handles-and-bytes;'
                        b'terminal-retention;COMPONENT_QUALIFICATION=pending' in result,
                    'java-network-model-actual-controls')
            elif name == 'test_async_admission.py':
                require(b'JAVA_ASYNC_BORROW PASS uncertain-wait-and-borrow-retained;'
                    b'rooted-input-bytes-and-resource;COMPONENT_QUALIFICATION=pending' in result,
                    'java-network-model-actual-generated-call')
            elif name == 'test_wire.py':
                require(b'WIRE_UTF8_SOURCE_CONTROL PASS ' in result, 'java-network-model-original-wire')
        require(before == {path.relative_to(ROOT).as_posix(): file_identity(path) for path in observed},
            'java-network-model-source-unchanged')
        require(all(file_identity(Path(value['path'])) == value['identity'] for value in native_tools.values()),
            'java-network-model-tools-unchanged')
        report.update(status='passed', lockedModelJars=identities, nativeTools=native_tools,
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

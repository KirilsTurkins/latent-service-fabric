"""One exact Fetch backend candidate using existing compiler/engine/native inputs.

The original ordinary host runs the full finite gate first. A failed candidate
may then replay once through an authenticated private observer, never passing
qualification on the observer's behalf. No Cargo or engine build occurs.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))

from tools import qualify_typescript_fetch_runtime as fetch
from tools.phase2_operator_process import require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, read_file

TESTED = '0754391a20027a539f1d5b7c0426719a4bd6c3c1'
BACKEND = 'tools/typescript_guest/fetch.mjs'
CANDIDATE = {'sha256': 'sha256:cfd5f8986e20312ec931dd5da912387c07da1bee3b3ca47415912aebca82dafe',
             'bytes': 19183}
ADAPTERS = {'async_waiters.mjs': {'sha256': 'sha256:2cfc286f2b3b90d46ea35c9904b7836504c6e3c8933f0fad9fcbc6a7c5aa08c3', 'bytes': 9767}, 'compiler.py': {'sha256': 'sha256:603478e39ad76dad677bbff9767aa48230c3963e9b28e9deeee853e7926c79af', 'bytes': 27677}, 'componentize.mjs': {'sha256': 'sha256:cc62cd3bb040a1cf4d7cb6c6041c7da2fe36c61b638f4f69ac8e686840bfb4b1', 'bytes': 6956}}
PRIVATE_IDENTITY = {'sha256': 'sha256:f38101edfefcc81a1e42e0f91e73ce16f5b82a6c30c915b8e133a7133a2335bd',
                    'bytes': 2109}


def candidate_bytes(path: Path) -> bytes:
    require(file_identity(path, 65536) == CANDIDATE, 'fetch-candidate-exact-backend')
    return read_file(path, 65536)


def candidate_adapters(directory: Path) -> dict[str, bytes]:
    require(directory.is_dir() and not directory.is_symlink()
            and sorted(p.name for p in directory.iterdir()) == sorted(ADAPTERS),
            'fetch-candidate-exact-adapter-set')
    result = {}
    for name, expected in ADAPTERS.items():
        source = directory/name
        require(not source.is_symlink() and file_identity(source, 131072) == expected,
                'fetch-candidate-exact-adapter')
        result['tools/typescript_guest/'+name] = read_file(source, 131072)
    return result


def observer_host(directory: Path, identity: dict) -> Path:
    record = directory/'private-host-identity.json'
    require(file_identity(record, 8192) == PRIVATE_IDENTITY, 'fetch-candidate-observer-identity')
    value = json.loads(read_file(record, 8192))
    require(value['qualification'] is False and value['sourceCommit'] == TESTED
            and value['originalNative'] == identity
            and value['markers'] == {'numericFrames': True, 'registrationFailures': True, 'ownerLifetimes': True},
            'fetch-candidate-observer-source')
    host = directory/'private-latentd'
    require(file_identity(host, 256*1024**2) == value['privateHost'], 'fetch-candidate-observer-binary')
    return host


def run(candidate: Path, adapters: Path, native: Path, engine: Path, splicer: Path, tools: Path,
        observer: Path, observer_helper: Path, output: Path) -> dict:
    output = fresh(output)
    require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip() == TESTED,
            'fetch-candidate-original-source')
    require(not subprocess.check_output(['git', 'status', '--porcelain']), 'fetch-candidate-clean-source')
    replacements = {BACKEND: candidate_bytes(candidate), **candidate_adapters(adapters)}
    originals, identity = fetch.prepared_native(native)
    private_host = observer_host(observer, identity)
    originals_source = {name: read_file(ROOT/name, 131072) for name in replacements}
    original = originals_source[BACKEND]
    record = {'schemaVersion': 'latent.typescript.fetch-backend-candidate.v1',
              'sdkTestedCommit': TESTED, 'candidateBackend': CANDIDATE, 'candidateCompilerAdapters': ADAPTERS,
              'originalBackend': {'sha256': digest(original), 'bytes': len(original)},
              'nativeTuple': identity, 'compilerOrEngineRebuilt': False,
              'currentPrHeadQualification': False, 'privateObserverQualification': False,
              'ordinaryFiniteGate': 'not-run'}
    try:
        for name, raw in replacements.items():
            (ROOT/name).write_bytes(raw)
        require(sorted(subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines()) == sorted(replacements),
                'fetch-candidate-only-reviewed-source-delta')
        try:
            result = fetch.qualify(output/'attempt', tools, engine, splicer, prepared=native)
            record['ordinaryFiniteGate'] = result['status']
            record['ordinaryCases'] = result['cases']
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
            record['ordinaryFailureClass'] = type(error).__name__
            record['ordinaryFiniteGate'] = 'failed'
        except Exception:
            record['ordinaryFiniteGate'] = 'failed'
            record['ordinaryFailureClass'] = 'Other'
        component = output/'attempt/build/component.wasm'
        if component.is_file():
            record['component'] = file_identity(component, 16*1024**2)
        bindings = output/'attempt/build/generated-bindings.js'
        if bindings.is_file():
            # Owned compiler output only; no application payload or environment.
            record['generatedBindings'] = file_identity(bindings, 1024**2)
        if record['ordinaryFiniteGate'] == 'failed' and (output/'attempt/node/FAILED.json').is_file():
            spec = importlib.util.spec_from_file_location('private_fetch_observer', observer_helper)
            require(spec is not None and spec.loader is not None, 'fetch-candidate-observer-module')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            require(module.TESTED == TESTED, 'fetch-candidate-observer-helper-source')
            # This explicitly identified new component is diagnostic only. The
            # normal finite gate above has already retained its genuine failure.
            private_host.chmod(0o700)
            with patch.object(module, 'COMPONENT', record['component']):
                record['privateReplay'] = module.replay(output/'attempt/build',
                    {**originals, 'latentd': private_host}, output/'private-replay')
    finally:
        unchanged = all(read_file(ROOT/name, 131072) == raw for name, raw in replacements.items())
        for name, raw in originals_source.items():
            (ROOT/name).write_bytes(raw)
        require(unchanged, 'fetch-candidate-source-drift')
        require(not subprocess.check_output(['git', 'status', '--porcelain']), 'fetch-candidate-source-not-restored')
        require(fetch.prepared_native(native)[1] == identity, 'fetch-candidate-native-drift')
        record['originalSourceRestored'] = True
        record['originalNativeUnchanged'] = True
        write_json(output/'observation.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('candidate', 'adapters', 'native', 'engine', 'splicer', 'tools', 'observer', 'observer-helper', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.candidate, args.adapters, args.native, args.engine, args.splicer, args.tools,
                         args.observer, args.observer_helper, args.output)))

"""One exact Fetch backend candidate using existing compiler/engine/native inputs.

The original ordinary host runs the full finite gate first. A failed candidate
may then replay once through an authenticated private observer, never passing
qualification on the observer's behalf. No Cargo or engine build occurs.
"""
from __future__ import annotations

from contextlib import contextmanager

import argparse
import importlib
import importlib.machinery
import importlib.util
import json
import re
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
CANDIDATE_SOURCE = '819791f66b2d2fcbe38f2f04259af249f98cfacb'
BACKEND = 'tools/typescript_guest/fetch.mjs'
CANDIDATE = {'sha256': 'sha256:cfd5f8986e20312ec931dd5da912387c07da1bee3b3ca47415912aebca82dafe',
             'bytes': 19183}
ADAPTERS = {'async_waiters.mjs': {'sha256': 'sha256:eeb942c30c3cb578d493a603e14aa0ab6b603ae607205736f3a69b9e4d344518', 'bytes': 18606}, 'compiler.py': {'sha256': 'sha256:603478e39ad76dad677bbff9767aa48230c3963e9b28e9deeee853e7926c79af', 'bytes': 27677}, 'componentize.mjs': {'sha256': 'sha256:36d9cc5075ecf28349200d634dfcb462c4a0092618ce3aa9c18af4585a3baee9', 'bytes': 7147}}
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


def failure_sites(error: BaseException) -> list[dict]:
    """Only public owned-source locations, never error text or local paths."""
    sites = []
    trace = error.__traceback__
    while trace is not None:
        frame = trace.tb_frame
        path = Path(frame.f_code.co_filename).resolve()
        if (ROOT in path.parents and path.suffix == '.py'
                and (ROOT/'tools') in path.parents
                and re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]{0,79}', frame.f_code.co_name)
                and 1 <= trace.tb_lineno <= 1000000):
            sites.append({'source': path.relative_to(ROOT).as_posix(),
                          'function': frame.f_code.co_name, 'line': trace.tb_lineno})
        trace = trace.tb_next
    return sites[-8:]


@contextmanager
def selected_candidate(native: Path, products: dict, identity: dict, replacements: dict):
    """Bind original products to a separately identified private source candidate.

    The unmodified full prepared-source guard runs before installing candidate
    bytes and after restoration. During the candidate, each use rehashes all
    five original products and all four reviewed source files. No production
    receipt validator is changed or given current-source qualification credit.
    """
    def verified_original(selected):
        require(Path(selected).resolve() == native.resolve(), 'fetch-candidate-original-native-path')
        require(all(read_file(ROOT/name, 131072) == raw for name, raw in replacements.items()),
                'fetch-candidate-reviewed-source-drift')
        require({name: file_identity(path, 512*1024**2) for name, path in products.items()}
                == identity['nativeProducts'], 'fetch-candidate-original-products-drift')
        return products, identity

    verified_original(native)
    compiler_source = ROOT/'tools/typescript_guest/compiler.py'
    # Compile the authenticated bytes directly: importing an already loaded
    # module (or a same-timestamp .pyc) would silently reuse the old adapter.
    class ReviewedSourceLoader(importlib.machinery.SourceFileLoader):
        def get_code(self, fullname):
            return self.source_to_code(read_file(Path(self.path), 131072), self.path)

    loader = ReviewedSourceLoader('private_fetch_candidate_compiler', str(compiler_source))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    require(spec is not None, 'fetch-candidate-compiler-loader')
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    build_module = importlib.import_module('tools.typescript_guest.build')
    original_compiler = build_module.Compiler
    require(module.Compiler is not original_compiler, 'fetch-candidate-fresh-compiler-required')
    with patch.object(fetch, 'prepared_native', side_effect=verified_original), \
            patch.object(build_module, 'Compiler', module.Compiler):
        try:
            yield
        finally:
            verified_original(native)
    require(build_module.Compiler is original_compiler, 'fetch-candidate-compiler-not-restored')


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
              'sdkTestedCommit': TESTED, 'candidateSourceCommit': CANDIDATE_SOURCE, 'candidateBackend': CANDIDATE, 'candidateCompilerAdapters': ADAPTERS,
              'originalBackend': {'sha256': digest(original), 'bytes': len(original)},
              'nativeTuple': identity, 'compilerOrEngineRebuilt': False,
              'currentPrHeadQualification': False, 'privateObserverQualification': False,
              'ordinaryFiniteGate': 'not-run',
              'preparedSourceValidatedBeforeAndAfterRestoration': True,
              'selectedSourceQualification': False}
    try:
        for name, raw in replacements.items():
            (ROOT/name).write_bytes(raw)
        changed = sorted(name for name, raw in replacements.items() if raw != originals_source[name])
        require(changed and sorted(subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines()) == changed,
                'fetch-candidate-only-reviewed-source-delta')
        record['candidateChangedSources'] = changed
        try:
            with selected_candidate(native, originals, identity, replacements):
                result = fetch.qualify(output/'attempt', tools, engine, splicer, prepared=native)
            record['ordinaryFiniteGate'] = result['status']
            record['ordinaryCases'] = result['cases']
        except (ValueError, OSError, KeyError, TypeError, RuntimeError) as error:
            record['ordinaryFailureClass'] = type(error).__name__
            record['ordinaryFailureSites'] = failure_sites(error)
            # Only the known fixed setup code is projected; no arbitrary error text.
            if str(error) == 'typescript-library-exact-prepared-source-required':
                record['ordinaryFailureCode'] = str(error)
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

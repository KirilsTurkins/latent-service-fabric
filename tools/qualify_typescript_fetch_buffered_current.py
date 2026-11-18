"""Run the original signed buffered Fetch vectors with same-workflow products.

This is a new current-source qualification; historical replay and receipts are
unchanged.  The source controls here do not themselves prove signed execution.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import platform
import shutil
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_typescript_fetch_conformance as conformance
from tools import qualify_typescript_fetch_runtime as base
from tools import typescript_fetch_buffered as buffered
from tools.phase2_operator_process import require, write_json
from tools.phase3_resource_identity import file_identity
from tools.qualify_typescript_published_fetch_current import selected_build, source_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, snapshot
from tools.typescript_guest.borrow_current_controls import source_products
from tools.typescript_guest.build import RECIPE as BUILD_RECIPE, build

RECIPE = tuple(dict.fromkeys((*BUILD_RECIPE, *conformance.SOURCES,
    buffered.SOURCE, 'tools/typescript_fetch_buffered.py',
    'tools/qualify_typescript_fetch_buffered_current.py',
    'tools/qualify_typescript_published_fetch_current.py',
    'tools/qualify_typescript_dependencies.py',
    'tools/typescript_guest/borrow_current_controls.py',
    'tools/tests/test_typescript_fetch_buffered.py',
    'tools/tests/test_typescript_fetch_buffered_current.py',
    'docs/testing/typescript-fetch-buffered.md',
    '.github/workflows/typescript-guest.yml',
    '.github/workflows/typescript-fetch-buffered.yml')))


def require_execution(value):
    expected = [{'name': name, 'outbound': outbound, 'result': result}
                for name, _mode, _vector, result, outbound in buffered.vectors()]
    expected.append({'name': 'fresh-after-lifecycle', 'outbound': 0,
                     'result': buffered.vectors()[0][3]})
    require(type(value) is dict and value.get('status') == 'passed'
            and value.get('fullTicketQualification') is False
            and value.get('networkStreamingQualified') is False
            and value.get('crossTenantQualified') is False
            and value.get('bufferedOnly') is True
            and value.get('signedExecution') == value.get('providerExecution') == 'passed'
            and value.get('cases') == expected,
            'buffered-fetch-current-original-cases-required')
    shutdown = value.get('shutdown')
    require(type(shutdown) is dict and shutdown.get('reaped') is True
            and type(shutdown.get('record')) is dict and shutdown['record'].get('clean') is True,
            'buffered-fetch-current-clean-shutdown-required')
    buffered.peer_evidence(value.get('peer'))
    return expected


def qualify(tools, engine, splicer, prepared, output):
    require(sys.platform == 'linux' and platform.machine() in ('x86_64', 'AMD64')
            and sys.version_info[:3] == (3, 13, 5), 'buffered-fetch-current-linux-pinned-python')
    tools, engine, splicer, prepared = (Path(p).resolve(strict=True)
                                        for p in (tools, engine, splicer, prepared))
    output = Path(output).resolve()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
            and all(output != path and output not in path.parents and path not in output.parents
                    for path in (tools, engine, splicer, prepared)),
            'buffered-fetch-current-separated-output')
    output = fresh(output)
    record = {'schemaVersion': 'latent.typescript.buffered-fetch-current.v1',
        'status': 'in-progress', 'scope': 'same-source-signed-buffered-fetch',
        'fullTicketQualification': False, 'networkStreamingQualified': False,
        'crossTenantQualified': False}
    stage = 'source'
    try:
        source = source_identity()
        recipe = {name: file_identity(ROOT/name) for name in RECIPE}
        stage = 'same-run-products'
        compiler = source_products(engine, splicer)
        originals, native_identity = base.prepared_native(prepared)
        record.update(source=source, recipe=recipe, compilerProducts=compiler,
                      nativeProducts=native_identity, ownerLimits=dict(base.OWNER_LIMITS))
        selected = fresh(output/'selected-native')
        native = {}
        for name, original in originals.items():
            native[name] = selected/name
            shutil.copyfile(original, native[name])
            native[name].chmod(0o700)
        copied = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
        require(copied == {name: file_identity(path, 512*1024**2) for name, path in originals.items()},
                'buffered-fetch-current-native-copy-changed')
        stage = 'application'
        app = buffered.project(output/'application')
        before = inventory(snapshot(app))
        stage = 'normal-build'
        artifact = build(app, output/'build', native['capsule_contracts'], native['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools,
            runtime_engine=engine/'engine.wasm', runtime_engine_receipt=engine/'engine-input.json',
            runtime_splicer=splicer/'splicer', runtime_splicer_receipt=splicer/'splicer-input.json')
        proof = selected_build(artifact, engine, splicer)
        stage = 'signed-provider-execution'
        observed = conformance.execute(artifact, native, output/'node', buffered_only=True)
        cases = require_execution(observed)
        require(before == inventory(snapshot(app)) and proof == selected_build(artifact, engine, splicer),
                'buffered-fetch-current-application-or-build-changed')
        stage = 'final-input-check'
        require(source == source_identity() and recipe == {name: file_identity(ROOT/name) for name in RECIPE}
                and compiler == source_products(engine, splicer)
                and native_identity == base.prepared_native(prepared)[1]
                and copied == {name: file_identity(path, 512*1024**2) for name, path in native.items()},
                'buffered-fetch-current-inputs-changed')
        record.update(status='passed', signedExecution='passed', providerExecution='passed',
                      sourceDigest=digest(before), build=proof, cases=cases,
                      execution=file_identity(output/'node/qualification.json'))
        write_json(output/'BUFFERED-FETCH-CURRENT.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        (output/'BUFFERED-FETCH-CURRENT.json').unlink(missing_ok=True)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('tools', 'engine', 'splicer', 'prepared', 'output'):
        parser.add_argument('--'+argument, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.tools, args.engine, args.splicer, args.prepared, args.output)))

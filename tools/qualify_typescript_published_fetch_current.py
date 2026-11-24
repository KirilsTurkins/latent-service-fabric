#!/usr/bin/env python3
"""Run the existing published Fetch programme with same-workflow source products.

This is a new qualification, not a replacement for the historical replay or
its receipts.  A successful run establishes only the selected client cases.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import qualify_typescript_fetch_runtime as base
from tools import qualify_typescript_published_fetch as published
from tools import typescript_published_fetch_fixture as fixture
from tools.phase2_operator_process import require, write_json
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_json, snapshot
from tools.typescript_guest.borrow_current_controls import source_products, workflow_origin
from tools.typescript_guest.build import RECIPE as BUILD_RECIPE, build
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

RECIPE = tuple(dict.fromkeys((*BUILD_RECIPE,
    'tools/qualify_typescript_published_fetch_current.py',
    'tools/qualify_typescript_published_fetch.py',
    'tools/typescript_published_fetch_fixture.py',
    'tools/qualify_typescript_fetch_runtime.py',
    'tools/qualify_typescript_dependencies.py',
    'tools/typescript_guest/borrow_current_controls.py',
    'tools/java_standard_http_peer.py',
    'tools/tests/test_typescript_published_fetch_current.py',
    '.github/workflows/typescript-guest.yml')))
UNSUPPORTED_CASE = 'ky-http404-unsupported'


def source_identity():
    def git(*arguments):
        result = subprocess.run(['git', *arguments], cwd=ROOT, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return result.stdout.decode('utf-8').strip()
    commit, tree = git('rev-parse', 'HEAD'), git('rev-parse', 'HEAD^{tree}')
    require(re.fullmatch(r'[0-9a-f]{40}', commit) is not None
            and re.fullmatch(r'[0-9a-f]{40}', tree) is not None
            and not git('status', '--porcelain', '--untracked-files=normal'),
            'published-fetch-current-clean-source-required')
    return {'commit': commit, 'tree': tree, 'workflowOrigin': workflow_origin(os.environ, commit)}


def selected_build(artifact, engine, splicer):
    """Bind the packaged component to both exact inputs, not merely a profile."""
    proof = base.build_evidence(artifact)
    selected = read_json(artifact/'typescript-runtime-selection.json')
    require(selected.get('profile') == IMPORT_PROFILE
            and selected.get('engineInput') == read_json(engine/'engine-input.json')
            and selected.get('compilerSplicerInput') == read_json(splicer/'splicer-input.json'),
            'published-fetch-current-actual-engine-and-splicer-required')
    return proof


def require_execution(value):
    expected = ['buffered-reader-probe', 'buffered-json-probe'] + [row[0] for row in published.VECTORS]
    require(type(value) is dict and value.get('status') == 'passed'
            and value.get('fullTicketQualification') is False
            and value.get('signedExecution') == value.get('providerExecution') == 'passed'
            and value.get('diagnosticOwnerProfile') is False
            and value.get('failedClientCases') == [] and value.get('cases') == expected,
            'published-fetch-current-original-cases-required')
    require(expected.count(UNSUPPORTED_CASE) == 1, 'published-fetch-current-unsupported-case-required')
    return {'passedCases': [name for name in expected if name != UNSUPPORTED_CASE],
            'expectedUnsupportedCases': [UNSUPPORTED_CASE]}


def qualify(tools, engine, splicer, prepared, output):
    require(sys.platform == 'linux' and platform.machine() in ('x86_64', 'AMD64')
            and sys.version_info[:3] == (3, 13, 5), 'published-fetch-current-linux-pinned-python')
    tools, engine, splicer, prepared = (Path(p).resolve(strict=True)
                                        for p in (tools, engine, splicer, prepared))
    output = Path(output).resolve()
    require(output != ROOT and ROOT not in output.parents and output not in ROOT.parents
            and all(output != path and output not in path.parents and path not in output.parents
                    for path in (tools, engine, splicer, prepared)),
            'published-fetch-current-separated-output')
    output = fresh(output)
    record = {'schemaVersion': 'latent.typescript.published-fetch-current.v1',
        'status': 'in-progress', 'fullTicketQualification': False,
        'scope': 'same-source-unchanged-published-fetch-and-outside-identities',
        'applicationFetchInjection': False, 'packageSourceChanges': False,
        'defaultClientHttpErrorQualified': False,
        'statusText': 'unsupported-by-original-typed-response', 'variants': []}
    stage = 'source'
    try:
        source = source_identity()
        recipe = {name: file_identity(ROOT/name) for name in RECIPE}
        stage = 'same-run-products'
        compiler = source_products(engine, splicer)
        originals, native_identity = base.prepared_native(prepared)
        record.update(source=source, recipe=recipe, compilerProducts=compiler, nativeProducts=native_identity,
            ownerProfile=published.CLIENT_OWNER_PROFILE, limits=dict(published.CLIENT_OWNER_LIMITS),
            originalOwnerLimits=dict(base.OWNER_LIMITS))
        selected = fresh(output/'selected-native')
        native = {}
        for name, original in originals.items():
            native[name] = selected/name
            shutil.copyfile(original, native[name])
            native[name].chmod(0o700)
        copied = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
        require(copied == {name: file_identity(path, 512*1024**2) for name, path in originals.items()},
                'published-fetch-current-native-copy-changed')
        for index, (name, version) in enumerate(published.IDENTITIES, 1):
            variant = fresh(output/f'variant-{index}')
            app = fixture.project(variant/'application', name)
            stage = f'capture-{index}'
            capture = fixture.capture(app, variant/'private-library', name, version)
            write_json(variant/'capture.json', capture)
            before = inventory(snapshot(app))
            stage = f'normal-build-{index}'
            artifact = build(app, variant/'build', native['capsule_contracts'], native['package'],
                'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools,
                runtime_engine=engine/'engine.wasm', runtime_engine_receipt=engine/'engine-input.json',
                runtime_splicer=splicer/'splicer', runtime_splicer_receipt=splicer/'splicer-input.json')
            proof = selected_build(artifact, engine, splicer)
            stage = f'signed-execution-{index}'
            observed = published.execute(artifact, native, variant/'node')
            cases = require_execution(observed)
            require(before == inventory(snapshot(app)) and proof == selected_build(artifact, engine, splicer),
                    'published-fetch-current-application-or-build-changed')
            record['variants'].append({'capture': capture, 'source': digest(before), 'build': proof,
                **cases, 'execution': file_identity(variant/'node/qualification.json')})
        stage = 'final-input-check'
        require(source == source_identity() and recipe == {name: file_identity(ROOT/name) for name in RECIPE}
                and compiler == source_products(engine, splicer)
                and native_identity == base.prepared_native(prepared)[1]
                and copied == {name: file_identity(path, 512*1024**2) for name, path in native.items()},
                'published-fetch-current-inputs-changed')
        record.update(status='passed', signedExecution='passed', providerExecution='passed')
        write_json(output/'PUBLISHED-FETCH-CURRENT.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        (output/'PUBLISHED-FETCH-CURRENT.json').unlink(missing_ok=True)
        write_json(output/'FAILED.json', record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for argument in ('tools', 'engine', 'splicer', 'prepared', 'output'):
        parser.add_argument('--'+argument, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.tools, args.engine, args.splicer, args.prepared, args.output)))

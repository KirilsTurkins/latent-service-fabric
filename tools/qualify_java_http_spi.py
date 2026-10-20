"""Build one optional public-SPI component normally; default evidence is separate."""
from __future__ import annotations

import argparse
import importlib
import os
from pathlib import Path
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.build_observation import build_environment
from tools.java_capsule_build import build, FIBER_IO_PROFILE
from tools.java_http_spi_fixture import project, SOURCE, WORLD
from tools.java_http_spi_node import run as node_controls
from tools.java_http_client import PHASE_PROFILE_ID
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity
from tools.qualify_java_http_phases import (MATERIALS as PHASE_MATERIALS, resolve_review,
    native_source)
from tools.java_standard_http_library import compiler_cache
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json

MAX_SECONDS = 1500
MATERIALS = tuple(dict.fromkeys((*PHASE_MATERIALS, SOURCE, WORLD,
    'tools/java_http_spi_fixture.py', 'tools/java_http_spi_node.py',
    'tools/qualify_java_http_spi.py', 'tools/http_tenant_native_products.py')))


def execute(commands, binaries, wasi_sdk, output, selected_cache=None):
    output = fresh(output)
    before = {name: file_identity(ROOT/name) for name in MATERIALS}
    products = {name: file_identity(path) for name, path in binaries.items()}
    stage = 'project'
    try:
        app = project(output/'application')
        stage = 'normal-resolve-review'
        captured = resolve_review(commands, app, output/'candidate.json')
        stage = 'compiler-cache'
        cache = compiler_cache(commands, wasi_sdk, output, selected_cache)
        stage = 'offline-optional-spi-component'
        remaining = min(900, commands.deadline-time.monotonic())
        require(remaining > 0, 'java-spi-original-build-deadline')
        artifact = build(app, output/'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', wasi_sdk,
            timeout=remaining, read_only_cache=cache, runtime_profile=FIBER_IO_PROFILE)
        actual = {row['id']: row['originalDigest']
            for row in read_json(artifact/'java-classpath.json')['artifacts']}
        require(set(actual) == set(captured['originalJars'])
            and all(actual[name] == identity['digest'] for name, identity in captured['originalJars'].items()),
            'java-spi-actual-classpath-drift')
        profile = read_json(artifact/'http-client-profile.json')
        require(profile['profile'] == PHASE_PROFILE_ID
            and profile['componentDigest'] == digest(read_file(artifact/'component.wasm')),
            'java-spi-selected-profile-drift')
        stage = 'signed-optional-spi-only'
        result = node_controls(artifact,
            {name: binaries[name] for name in ('latent', 'latentd', 'capsule_authoring')},
            output/'node', deadline=commands.deadline)
        require(result['status'] == 'passed' and len(result['cases']) == 6
            and result['defaultClientQualification'] is False
            and result['sameNodeCrossTenantHttpQualified'] is False,
            'java-spi-incomplete-or-overclaimed-node-programme')
        after = {name: file_identity(ROOT/name) for name in MATERIALS}
        product_after = {name: file_identity(path) for name, path in binaries.items()}
        require(before == after and products == product_after and time.monotonic() < commands.deadline,
            'java-spi-final-source-or-product-drift')
        record = {'schemaVersion': 'latent.java.http-public-spi-campaign.v1', 'status': 'passed',
            'materials': before, 'nativeProducts': products, 'libraries': captured,
            'artifact': {name: file_identity(artifact/name) for name in ('component.wasm', 'BUILD-COMPLETE.json',
                'source-inputs.json', 'recipe-inputs.json', 'compiler-inputs.json', 'build-observation.json',
                'http-client-profile.json', 'runtime-profile.json', 'java-classpath.json')},
            'nodeReceipt': file_identity(output/'node/qualification.json'),
            'invocations': 6, 'authorityDenials': 2, 'httpContacts': 4,
            'defaultClientQualification': False, 'sameNodeCrossTenantHttpQualified': False,
            'full688Qualified': False, 'full741Qualified': False}
        write_json(output/'final-materials.json', {'materials': after, 'nativeProducts': product_after})
        write_json(output/'qualification.json', record)
        return record
    except BaseException:
        try: write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage,
            'defaultClientQualification': False, 'sameNodeCrossTenantHttpQualified': False})
        except Exception: pass
        raise


def run(output, prepared, wasi_sdk, selected_cache=None):
    # This separate authenticator is supplied only after the nominal packaging
    # producer actually passes. Never silently substitute the historical77 tuple.
    require((ROOT/'tools/wait_runtime_native_products.py').is_file(),
        'java-spi-authenticated-nominal-products-helper-required')
    products = importlib.import_module('tools.wait_runtime_native_products')
    history = products.verify_prepared(prepared);source = native_source(prepared)
    output = fresh(output);environment = build_environment(output)
    if 'JAVA_HOME' in os.environ: environment['JAVA_HOME'] = os.environ['JAVA_HOME']
    commands = Commands(ROOT, fresh(output/'commands'), environment,
        deadline_seconds=MAX_SECONDS, command_seconds=300)
    result = execute(commands, products.native_products(prepared), wasi_sdk, output/'campaign', selected_cache)
    require(history == products.verify_prepared(prepared) and source == native_source(prepared),
        'java-spi-final-prepared-source-drift')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', type=Path, required=True)
    parser.add_argument('--wasi-sdk', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--compiler-cache', type=Path)
    arguments = parser.parse_args()
    run(arguments.output, arguments.prepared, arguments.wasi_sdk, arguments.compiler_cache)


if __name__ == '__main__':
    main()

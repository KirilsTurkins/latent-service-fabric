"""One normal captured C build and its signed finite threading programme."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import c_capsule_build as compiler
from tools import c_thread_runtime_fixture as fixture, c_timed_runtime_node as node
from tools import c_timed_runtime_fixture as timed
from tools import qualify_c_thread_runtime as original
from tools.java_replay_materials import git_source_identity
from tools.c_guest.threading import IMPORTS, PROFILE, RECIPE as THREAD_RECIPE
from tools.c_guest import threading_compatibility as compatibility
from tools.c_guest.threading_compatibility import RECIPE as COMPATIBILITY_RECIPE
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.qualify_sdk_scratch import package_identity
from tools.rust_capsule_project import ROOT, fresh, inventory, read_file, read_json, snapshot, write_json

MATERIALS = ('tools/qualify_c_timed_runtime.py', 'tools/c_timed_runtime_fixture.py',
    'tools/c_timed_runtime_node.py', 'tools/host_codec_session_native_products.py',
    'tools/guest_runtime_profiles.py', '.github/workflows/c-timed-runtime.yml',
    fixture.FIXTURE + 'timing.h', 'tools/c_timed_source_controls.py',
    'tools/tests/fixtures/c-timed-broadcast-source.c',
    'tools/tests/fixtures/c-timed-broadcast-source.cjs')


def materials():
    result = original.materials()
    result.update({name: file_identity(ROOT / name, 4 * 1024**2) for name in MATERIALS})
    require(len(result) <= 256 and sum(row['bytes'] for row in result.values()) <= 16 * 1024**2,
        'c-timed-helper-bounds')
    return result


def build_evidence(artifact, source):
    marker = read_json(artifact / 'BUILD-COMPLETE.json')
    observed = read_json(artifact / 'build-observation.json')
    component = file_identity(artifact / 'component.wasm', 8 * 1024**2)
    require(read_file(artifact / 'source-inputs.json') == source
            and marker['packageAssembled'] is True
            and marker['sourceDigest'] == file_identity(artifact / 'source-inputs.json')['sha256']
            and marker['observationDigest'] == file_identity(artifact / 'build-observation.json')['sha256']
            and marker['componentDigest'] == observed['componentDigest'] == component['sha256']
            and observed['componentSize'] == component['bytes'], 'c-thread-normal-build-identity')
    require(observed['parameters'] == {'compiler': 'zig-cc', 'fixture': 'application',
            'target': 'wasm32-wasi', 'optimization': 'O2'}
            and any(row['stage'] == 'zig' and row['exitCode'] == 0 for row in marker['commands'])
            and all(row['exitCode'] == 0 for row in marker['commands']),
            'c-thread-original-compiler-success')
    derivation = read_json(artifact / 'c-threading-derivation.json')
    require(set(derivation) == {'formatVersion', 'profile', 'originalCoreDigest',
            'derivedCoreDigest', 'publicExport', 'rootRecordBytes',
            'canonicalComponentAuthenticated', 'standardRuntimeQualified'}
            and type(derivation['formatVersion']) is int and derivation['formatVersion'] == 1
            and derivation['profile'] == PROFILE and derivation['publicExport'] == fixture.API + '#greet'
            and type(derivation['rootRecordBytes']) is int and derivation['rootRecordBytes'] == 144
            and derivation['canonicalComponentAuthenticated'] is False
            and derivation['standardRuntimeQualified'] is False
            and all(type(derivation[name]) is str
                    and re.fullmatch(r'sha256:[0-9a-f]{64}', derivation[name])
                    for name in ('originalCoreDigest', 'derivedCoreDigest')),
            'c-thread-compiler-mechanism-not-runtime-qualification')
    for name in ('compiler-inputs.json', 'c-threading-derivation.json',
                 'c-threading-compatibility.json', 'recipe-inputs.json'):
        identity = file_identity(artifact / name, 16 * 1024**2)
        material = {'compiler-inputs.json': 'c-compiler-sysroot-and-isolation',
                    'c-threading-derivation.json': 'c-threading-derivation',
                    'c-threading-compatibility.json': 'c-threading-compatibility',
                    'recipe-inputs.json': 'build-recipe'}[name]
        require([row for row in observed['materials'] if row['name'] == material] == [
            {'name': material, 'digest': identity['sha256'], 'size': identity['bytes']}],
            'c-thread-observed-compiler-material')
    capsule = read_json(artifact / 'capsule.json')
    require(capsule['execution']['threading'] == 'cooperative'
            and len(capsule['imports']) == 5
            and {row['contract'] for row in capsule['imports']} == set(timed.IMPORTS)
            and all(row['optional'] is False for row in capsule['imports'])
            and capsule['exports'] == [fixture.API], 'c-thread-selected-normal-component-contract')
    from tools.c_guest import threading
    for path, sha256 in threading.CLOCK_LIBC.items():
        name = threading.clock_libc_material_name(path)
        rows = [row for row in observed['materials'] if row['name'] == name]
        require(len(rows) == 1 and rows[0]['digest'] == 'sha256:' + sha256
                and type(rows[0]['size']) is int and 0 < rows[0]['size'] <= 32768,
                'c-timed-all-original-clock-material-pins')
    return {'component': component, 'marker': marker, 'derivation': derivation,
            'compatibilityAssets': original.supplement_evidence(artifact, component, derivation),
            'package': package_identity(artifact, marker)}


def qualify(prepared, output):
    require(sys.platform == 'linux' and sys.version_info >= (3, 13) and os.geteuid() != 0,
            'c-thread-unprivileged-linux-python313')
    from tools import host_codec_session_native_products as products
    output = output.absolute()
    require(output != ROOT and output not in ROOT.parents and ROOT not in output.parents,
            'c-thread-output-outside-checkout')
    output = fresh(output)
    stage = 'authenticate-current-frozen-native-products'
    record = {'schemaVersion': 'latent.c.thread-runtime.qualification.v1',
              'status': 'incomplete', 'profile': PROFILE, 'full744Qualified': False,
              'clockRuntimeProfile': timed.standard_facilities.PROFILE,
              'nativeProductsRebuilt': False, 'otherLanguageComponentsRebuilt': False}
    started = time.monotonic()
    try:
        before, source_proof, native = original.native_evidence(products, prepared)
        record.update(producer={'source': products.SOURCE, 'receipt': before},
                      consumerNativeSource=source_proof['consumerNativeSource'],
                      nativeSourceCompatibility=source_proof, materials=materials())
        stage = 'normal-selected-c-application'
        application = timed.prepare(output / 'application')
        source = inventory(snapshot(application))
        stage = 'one-normal-captured-selected-c-build'
        artifact = compiler.build(application, output / 'build', native['capsule_contracts'],
                                  native['package'], 'https://github.com/KirilsTurkins/latent-service-fabric')
        record['build'] = build_evidence(artifact, source)
        stage = 'signed-original-twenty-and-sixteen-timed-programme'
        record['node'] = node.run(artifact, native, output / 'node')
        require(record['node']['status'] == 'passed'
                and record['node']['programme']['status'] == 'passed'
                and record['node']['programme']['originalSeventeenOutcomePrefix'] == 17
                and record['node']['programme']['originalTwentyOutcomePrefix'] == 20
                and len(record['node']['programme']['outcomes']) == 36,
                'c-timed-all-original-twenty-and-sixteen-timed-outcomes')
        stage = 'unchanged-source-tools-products-and-original-build'
        require(time.monotonic() - started <= 1100
                and source_identity(ROOT) == source_proof['consumerNativeSource']
                and original.native_evidence(products, prepared) == (before, source_proof, native)
                and materials() == record['materials']
                and inventory(snapshot(application)) == source
                and build_evidence(artifact, source) == record['build'], 'c-thread-final-source-product-and-build-fence')
        record.update(status='passed', observedCases=36)
        write_json(output / 'qualification.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, qualification=False)
        try:
            write_json(output / 'FAILED.json', record)
        except BaseException:
            pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepared', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps({'status': qualify(args.prepared, args.output)['status']}))

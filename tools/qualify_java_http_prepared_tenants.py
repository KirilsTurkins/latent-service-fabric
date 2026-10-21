"""Twelve unchanged Java tenant outcomes after exact bounded publication preparation."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import java_http_retained_component as component
from tools import release_preparation_cli_native_products as native
from tools.java_http_tenant_node import run as tenant_controls
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, inventory, source_identity
from tools.qualify_java_http_phases import MATERIALS as ORIGINAL_MATERIALS
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.sdk_native_products_reader import MATERIALS as NATIVE_MATERIALS

MATERIALS = tuple(dict.fromkeys((*ORIGINAL_MATERIALS,
    'tools/qualify_java_http_prepared_tenants.py', 'tools/java_http_release_preparation.py',
    'tools/java_http_retained_component.py', component.PINS,
    'tools/release_preparation_cli_native_products.py',
    '.github/workflows/java-http-fiber-lifecycle.yml')))


def current_native(prepared):
    record = read_json(prepared/'native-products.json')
    current = source_identity(ROOT)
    require(record['sourceRevision'] == native.SOURCE and current == record['source'],
        'java-prepared-tenants-current-native-source-drift')
    actual = {name: file_identity(ROOT/name) for name in NATIVE_MATERIALS}
    for directory, maximum_files, maximum_bytes in (
            ('wit', 2048, 8*1024**2), ('schemas', 256, 4*1024**2),
            ('examples/echo-contract/wit', 128, 1024**2), ('api/proto', 128, 1024**2)):
        observed = inventory(ROOT/directory, maximum_files=maximum_files,
            maximum_bytes=maximum_bytes, deadline=time.monotonic()+30)
        actual.update({directory+'/'+row['path']: {key: row[key] for key in ('sha256', 'bytes')}
            for row in observed['files']})
    require(len(actual) == 134 and actual == record['materials'],
        'java-prepared-tenants-current-native-or-protocol-material-drift')
    return {'native': current, 'materials': actual, 'equalToCompiledProducer': True}


def run(output, prepared_native, prepared_component):
    history = native.verify_prepared(prepared_native)
    production = current_native(prepared_native)
    build = prepared_component/'build'
    compiled = component.validate(build)
    original_retrieval = read_json(prepared_component/'retrieval.json')
    require(original_retrieval['schemaVersion'] == 'latent.java.http.retained-component.v1'
        and original_retrieval['artifact'] == component.ARTIFACT
        and original_retrieval['run'] == component.RUN and original_retrieval['job'] == component.JOB
        and original_retrieval['originalOutcome'] == 'failed-before-publication'
        and original_retrieval['wholeArchiveSha256Verified'] is True
        and original_retrieval['historicalReceiptRewritten'] is False
        and original_retrieval['build'] == compiled, 'java-prepared-tenants-exact-component-retrieval')
    output = fresh(output)
    before = {name: file_identity(ROOT/name) for name in MATERIALS}
    binaries = native.native_products(prepared_native)
    stage = 'same-node-tenant-programme'
    try:
        result = tenant_controls(build,
            {name: binaries[name] for name in ('latent', 'latentd', 'capsule_authoring')},
            output/'tenants', deadline=time.monotonic()+350, prepare_publications=True)
        require(result['status'] == 'passed' and result['invocations'] == len(result['cases']) == 12
            and result['httpContacts'] == 10 and set(result['preparation']) == {'examples', 'foreign'},
            'java-prepared-tenants-original-twelve-case-programme')
        stage = 'final-source-and-product-fences'
        require(history == native.verify_prepared(prepared_native)
            and production == current_native(prepared_native)
            and compiled == component.validate(build)
            and original_retrieval == read_json(prepared_component/'retrieval.json')
            and before == {name: file_identity(ROOT/name) for name in before},
            'java-prepared-tenants-final-source-or-product-drift')
        final = {'schemaVersion': 'latent.java.http-prepared-tenants.v1', 'status': 'passed',
            'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'materials': before, 'nativeProducer': history, 'nativeProductionSourceProof': production,
            'compiledComponent': compiled, 'componentSource': component.SOURCE,
            'componentOriginalOutcome': 'failed-before-publication',
            'nativeRecompiledByConsumer': False, 'componentRecompiledByConsumer': False,
            'historicalReceiptRewritten': False,
            'tenantProgramme': {'receipt': file_identity(output/'tenants/qualification.json'),
                'invocations': 12, 'httpContacts': 10, 'sameNode': True, 'singleExecutionCell': True,
                'publicationPreparation': result['preparation']},
            'full688Qualified': False, 'full741Qualified': False,
            'limitations': ['Historical aa56 component and original compiler observations remain unchanged.',
                'Current native/API inputs are exactly the explicit protocol-attested 6fd CLI-dispatch producer.',
                'Finite plain-HTTP tenant programme only; whole Java/runtime and HTTPS remain separate.']}
        write_json(output/'qualification.json', final)
        return final
    except BaseException:
        try:write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage, 'full688Qualified': False})
        except Exception:pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--prepared-native', type=Path, required=True)
    parser.add_argument('--prepared-component', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    require(sys.platform == 'linux' and output != ROOT and ROOT not in output.parents,
        'java-prepared-tenants-owned-linux-output-required')
    run(output, args.prepared_native.resolve(strict=True), args.prepared_component.resolve(strict=True))

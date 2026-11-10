"""One fresh capacity component; frozen6fd native; no repeated HTTP baseline."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import dotnet_catalogue_free_build as staging
from tools import dotnet_managed_capacity_fixture as fixture, dotnet_managed_capacity_node as node
from tools import qualify_dotnet_http_mixed as shared
from tools import release_preparation_cli_native_products as products
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.dotnet_dependency_authoring import source_files
from tools.dotnet_guest.compiler import runtime_inputs
from tools.dotnet_guest import managed_work
from tools.phase2_operator_process import require
from tools.phase3_resource_identity import file_identity, source_identity
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json

MATERIALS = (fixture.SOURCE, 'tools/dotnet_managed_capacity_fixture.py',
    'tools/dotnet_managed_capacity_node.py', 'tools/qualify_dotnet_managed_capacity.py',
    'tools/dotnet_managed_work_controls.py', 'tools/fixtures/dotnet-timer-wait-control.rs',
    'tools/fixtures/timer-pump-source-control.rs',
    'tools/fixtures/timer-ready-source-control.rs',
    *shared.MATERIALS)


def qualify(native_directory, tools, output, *, rearm_diagnostic=False, ready_witness=False):
    require(type(rearm_diagnostic) is bool and type(ready_witness) is bool
        and not (rearm_diagnostic and ready_witness), 'capacity-timer-selection')
    output = fresh(output); deadline = time.monotonic()+1800
    native_record = products.verify_prepared(native_directory)
    native = products.native_products(native_directory)
    original_products = {name: file_identity(path, 512*1024**2) for name, path in native.items()}
    selected_materials = MATERIALS + ((fixture.REARM_SOURCE,) if rearm_diagnostic else ()) + (
        (fixture.READY_SOURCE,) if ready_witness else ())
    materials = {name: file_identity(ROOT/name) for name in selected_materials}
    sdk = inventory(snapshot(ROOT/'sdk/dotnet-guest')); native_source = source_identity(ROOT)
    runtime = runtime_inputs(ROOT)
    require(read_file(tools/'runtime-inputs.json') == runtime, 'capacity-current-runtime-installation')
    installation = {name: file_identity(tools/name, 16*1024**2)
        for name in ('INSTALL-COMPLETE.json', 'runtime-inputs.json', 'wasi-sdk.json')}
    record = {'schemaVersion': 'latent.dotnet.managed-capacity-campaign.v1', 'status': 'in-progress',
        'fixtureSource': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'compiledNativeSource': products.SOURCE, 'nativeProducer': native_record,
        'consumerNativeSourceObservation': native_source, 'consumerNativeCompiledByThisCampaign': False,
        'materials': materials, 'sdkSources': json.loads(sdk), 'runtimeInputsDigest': digest(runtime),
        'installation': installation, 'newNativeProductsBuilt': 0, 'newGuestComponentsCompiled': 0,
        'full693Qualified': False, 'full746Qualified': False}
    stage = 'normal-project-capture'
    try:
        app = fixture.project(output/'application', rearm_diagnostic=rearm_diagnostic, ready_witness=ready_witness)
        captured = inventory(source_files(app))
        stage = 'catalogue-free-normal-builder'
        staged = output/'staged-recipe'; selected = staging.stage(ROOT, staged)
        write_json(output/'catalogue-free-source.json', selected); artifact = output/'build'
        result = run_bounded_result([sys.executable, '-I', '-S', '-B', str(staged/staging.SELF),
            '--project', str(app), '--output', str(artifact), '--tools', str(tools),
            '--contracts-tool', str(native['capsule_contracts']), '--packager', str(native['package']),
            '--repository', 'https://github.com/KirilsTurkins/latent-service-fabric',
            '--expect-source-digest', selected['inventoryDigest']], staged, build_environment(output),
            timeout_seconds=min(900, deadline-time.monotonic()), max_output_bytes=4*1024**2)
        artifact.mkdir(exist_ok=True)
        for name in ('stdout', 'stderr'):(artifact/('compiler.'+name+'.txt')).write_bytes(getattr(result, name))
        require(result.returncode == 0, 'capacity-normal-native-aot-build')
        record['newGuestComponentsCompiled'] = 1
        require(read_file(artifact/'source-inputs.json') == captured and inventory(source_files(app)) == captured
            and staging.verify(staged) == selected, 'capacity-real-capture-and-builder-inputs')
        record['build'] = shared.build_evidence(artifact)
        require(record['build']['taskPort']['managedAcceptedWork'] == managed_work.TIMER_REWRITE_RECEIPT,
            'capacity-current-individual-timer-port-required')
        stage = 'signed-capacity-refusal-retirement-and-fresh'
        execution = node.run(artifact, native, output/'node', deadline=deadline,
            rearm_diagnostic=rearm_diagnostic, ready_witness=ready_witness)
        require(execution['status'] == 'passed' and execution['invocations'] == (19 if rearm_diagnostic or ready_witness else 17)
            and execution['httpContacts'] == 1 and len(execution['cases']) == 17,
            'capacity-all-mandatory-outcomes')
        if rearm_diagnostic:
            diagnostic = execution['timerRearmDiagnostic']
            require(diagnostic['diagnosticOnly'] is True and diagnostic['timerRearmFixQualified'] is False
                and diagnostic['postRetirementPhysicalCustodyQualified'] is False
                and len(diagnostic['cases']) == 2, 'capacity-timer-rearm-diagnostic-not-qualification')
        if ready_witness:
            witness = execution['readyTimerRetirementWitness']
            require(witness['ordinaryTimerDriverQualified'] is False
                and witness['postRetirementPhysicalCustodyQualified'] is False
                and len(witness['cases']) == 2, 'capacity-ready-witness-and-fresh-required')
        require(time.monotonic() < deadline and products.verify_prepared(native_directory) == native_record
            and original_products == {name: file_identity(path, 512*1024**2) for name, path in native.items()}
            and materials == {name: file_identity(ROOT/name) for name in selected_materials}
            and inventory(snapshot(ROOT/'sdk/dotnet-guest')) == sdk and runtime_inputs(ROOT) == runtime
            and read_file(tools/'runtime-inputs.json') == runtime and source_identity(ROOT) == native_source
            and installation == {name: file_identity(tools/name, 16*1024**2) for name in installation}
            and inventory(source_files(app)) == captured and staging.verify(staged) == selected,
            'capacity-final-source-native-runtime-and-deadline-fences')
        record.update(status='passed', invocations=19 if rearm_diagnostic or ready_witness else 17, signedComponents=1, httpContacts=1,
            nodeReceipt=file_identity(output/'node/qualification.json'),
            limitations=['Exact historical6fd native compilation is authenticated separately from current SDK/fixture compilation.',
                'NativeMemory allocation failure is not claimed: raw native-ledger admission and real managed-table installation are distinct controls.',
                'The zero-native installation terminal is generic guest-trap; no original exception transport or post-retired callback is claimed.',
                'Existing HTTP/private-client and30-case lifecycle evidence retains its original source and is not rerun here.'])
        if rearm_diagnostic:
            record['timerRearmDiagnostic'] = {'diagnosticOnly': True, 'timerRearmFixQualified': False,
                'postRetirementPhysicalCustodyQualified': False,
                'nodeReceipt': file_identity(output/'node/qualification.json')}
        if ready_witness:
            record['readyTimerRetirementWitness'] = {'ordinaryTimerDriverQualified': False,
                'postRetirementPhysicalCustodyQualified': False,
                'nodeReceipt': file_identity(output/'node/qualification.json')}
        write_json(output/'qualification.json', record); return record
    except BaseException:
        try:write_json(output/'FAILED.json', {**record, 'status': 'failed', 'stage': stage})
        except BaseException:pass
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'tools', 'output'):parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--timer-rearm-diagnostic', action='store_true',
        help='also run the separately recorded one-timer rearm observation and fresh activation')
    parser.add_argument('--ready-retirement-witness', action='store_true',
        help='also run the separately recorded ready-pollable retirement and fresh activation')
    args = parser.parse_args()
    print(qualify(args.native, args.tools, args.output, rearm_diagnostic=args.timer_rearm_diagnostic,
        ready_witness=args.ready_retirement_witness)['status'])

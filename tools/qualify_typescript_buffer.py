"""Compile, admit and invoke eight finite Buffer cases through the normal node.

Compiler inputs may come from a completed engine stage of a failed diagnostic
producer. That producer remains failed; no native case or Buffer runtime credit
is inferred. This programme must itself typecheck, bundle, compile and execute.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import java_phase_native_products as host
from tools import typescript_buffer_fixture as fixture
from tools import typescript_standard_clock_probe as clocks
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import configure_node, connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_typescript_fetch_runtime import build_evidence as runtime_build_evidence, require_result, retire
from tools.rust_capsule_node import RecordingClient, call, delete_all, deploy, sample
from tools.rust_capsule_project import ROOT, digest, fresh, inventory, read_file, read_json, snapshot, write_json
from tools.static_api.node import policy
from tools.typescript_guest import buffer_profile
from tools.typescript_guest.build import build
from tools.typescript_guest.runtime_profile import IMPORT_PROFILE

SERVICE = 'examples/my-greeting'
PRODUCTS = ('latent', 'latentd', 'capsule_contracts', 'package', 'capsule_authoring')


def build_evidence(artifact):
    result = runtime_build_evidence(artifact)
    selected = read_json(artifact/'typescript-buffer-selection.json')
    buffer_profile.validate_selection(selected, digest(read_file(ROOT/buffer_profile.BACKEND)))
    identity = file_identity(artifact/'typescript-buffer-selection.json', 65536)
    observation = read_json(artifact/'build-observation.json')
    require([row for row in observation['materials'] if row['name'] == 'typescript-standard-buffer'] == [
        {'name': 'typescript-standard-buffer', 'digest': identity['sha256'], 'size': identity['bytes']}],
        'buffer-normal-build-material')
    package = read_json(artifact/'package-source.json')
    require([row for row in package['layers'] if row['source'] == 'typescript-buffer-selection.json'] == [{
        'path': 'typescript-buffer-selection.json', 'source': 'typescript-buffer-selection.json',
        'role': 'asset', 'mediaType': 'application/vnd.latent.typescript.buffer-selection.v1+json'}],
        'buffer-normal-package-selection-asset')
    complete = read_json(artifact/'BUILD-COMPLETE.json')
    for stage in ('typecheck', 'bundle', 'componentize'):
        rows = [row for row in complete['commands'] if row['stage'] == stage]
        require(len(rows) == 1 and rows[0]['exitCode'] == 0, 'buffer-actual-'+stage)
    result['bufferSelection'] = identity
    return result


def configuration(directory, signed):
    path = configure_node(directory, signed, 'examples')
    value = read_json(path)
    value['cells'][0]['maximumMemoryBytes'] = 134217728
    value['execution']['maximumWallTimeMillis'] = 120000
    value['cache'].update(entries=2, preparations=1)
    value['shutdownGraceMillis'] = 5000
    value['audit'].update(records=4096, diskBytes=67108864)
    value['budgetProfile'] = {'mode': 'phase3', 'maximumOutboundRequests': 0,
        'maximumBlobReadBytes': 0, 'maximumBlobWriteBytes': 0}
    value['capabilityPolicies'] = {'formatVersion': 1, 'maximumControlJobs': 2,
        'store': {'maximumRecords': 64, 'maximumOutcomes': 128, 'maximumCatalogBytes': 4194304,
                  'maximumReadOwners': 64, 'maximumPageRecords': 16}}
    value['providers'] = {'formatVersion': 1, 'bindings': []}
    clocks.configure(value)
    path.write_bytes((json.dumps(value, indent=2)+'\n').encode())
    return path


def grants(client, node, publication):
    profiles = [(identity, capability, profile, [operation])
        for identity, capability, profile, operation in clocks.PROFILES.values()]
    profiles.append((clocks.ACTIVATION_ID, clocks.ACTIVATION, 'activation-owned-v1', clocks.ACTIVATION_OPS))
    result = []
    for identity, capability, profile, operations in profiles:
        rows = [row for row in node.startup_record['providers'] if row['id'] == identity]
        require(len(rows) == 1 and rows[0]['capability'] == capability and rows[0]['profile'] == profile
            and rows[0]['tenant'] == 'examples', 'buffer-normal-runtime-provider')
        descriptor = rows[0]
        policy(client, 'provider-binding', identity+'-installed', {'formatVersion': 1, 'tenant': 'examples',
            'capability': capability, 'providerProfile': profile,
            'configurationDigest': descriptor['configurationDigest'], 'configurationEpoch': 1,
            'restriction': {'operations': list(operations)}})
        policy(client, 'policy', identity+'-allow', {'formatVersion': 1, 'tenant': 'examples', 'rules': [{
            'id': 'runtime', 'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
            'services': [SERVICE], 'publications': [publication], 'capability': capability,
            'operations': list(operations), 'resources': {'kind': 'clock'},
            'ceiling': {'operations': 4096, 'inputBytes': 0, 'outputBytes': 32768, 'wallTimeMillis': 5000}}]})
        result.append({'capability': capability, 'policy': identity+'-allow'})
    return result


def execute(artifact, native, output, *, cases=fixture.CASES, scope=None):
    if cases != fixture.CASES or scope is not None:
        from tools.typescript_buffer_commonjs_fixture import CASES, SCOPE
        require(cases == CASES and scope == SCOPE, 'buffer-closed-qualification-programme')
    output = fresh(output)
    result = {'schemaVersion': 'latent.typescript.buffer-runtime.v1', 'status': 'in-progress',
        'fullTicketQualification': False, 'unchangedPublishedDependency': 'not-run',
        'relativeDependency': 'repository-fixture-only', 'cases': []}
    if scope is not None:
        result.update(unchangedPublishedDependency='selected-captured-commonjs',
            relativeDependency='not-used', publishedCommonJsQualification='pending')
    stage = 'normal-package-evidence'
    try:
        original = build_evidence(artifact)
        signed = output/'signed'
        stage = 'normal-signing'
        signed_result = run_bounded_result([str(native['capsule_authoring']), 'demo-sign', str(signed), str(artifact)],
            output, build_environment(output), timeout_seconds=30, max_output_bytes=65536)
        require(signed_result.returncode == 0, 'buffer-normal-signing')
        with tempfile.TemporaryDirectory(prefix='lsf-typescript-buffer-') as private, \
                owned_cancellation() as cancellation, ExitStack() as cleanup:
            work = Path(private)
            for name in ('client', 'node'):
                (work/name).mkdir(mode=0o700)
            client = RecordingClient(native['latent'], work/'client', cancellation, time.monotonic()+300,
                evidence=output/'controls', invocation_timeout_millis=120000, control_timeout_millis=125000)
            config = configuration(work/'node', signed)
            result['configuration'] = file_identity(config)
            stage = 'normal-node-startup'
            node = connect(client, native['latentd'], work/'node', config, 'examples', 0)
            cleanup.callback(lambda: (output/'node-stderr.txt').write_bytes(bytes(node.buffers[1])))
            cleanup.callback(node.close)
            result['startup'] = node.startup_record
            probe = Probe(node, file_identity(native['latentd']))
            source = signed/'my-greeting'
            stage = 'normal-publication-and-admission'
            published = client.call('release', 'publish-package', source/'package',
                '--evidence', source/'evidence/index.json', '--operation-id', 'buffer-publish', '--expected-generation', '0')
            require(published['outcomeKnown'] is True, 'buffer-publication-known')
            publication = published['data']['operation']['publication']['id']
            target = deploy(client, source/'deployment.json', publication, grants=grants(client, node, publication))
            require(target['service'] == SERVICE and target['budget']['outboundRequests'] == 0,
                'buffer-original-service-and-zero-outbound-budget')
            for mode, name in enumerate(cases):
                stage = name
                row = call(client, target, 'typescript-buffer', 'run', [mode], 'buffer-'+name)
                require_result(row, 'buffer:'+str(mode)+':pass|fresh=1', 0)
                used = row['response']['data']['consumption']
                require(0 < int(used['cpuFuel']) <= int(target['budget']['cpuFuel'])
                    and 0 < int(used['peakMemoryBytes']) <= int(target['budget']['memoryBytes'])
                    and int(used['logBytes']) == 0, 'buffer-original-activation-budgets')
                result['cases'].append({'case': name, 'invocation': row})
                retire(client, probe, target, output, name)
            delete_all(client, [target['name']])
            result['afterDelete'] = sample(client, probe, 'buffer-after-delete', 0)
            stop(client, node)
            result['shutdown'] = stopped_record(node)
            require(result['shutdown']['reaped'] and result['shutdown']['record']['clean'], 'buffer-node-clean-shutdown')
        require(build_evidence(artifact) == original, 'buffer-built-inputs-unchanged')
        result.update(status='passed', build=original, runtimeProfile=IMPORT_PROFILE, bufferProfile=buffer_profile.PROFILE)
        if scope is not None:
            result['publishedCommonJsQualification'] = 'six-case-subset-passed'
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        write_json(output/'FAILED.json', dict(result, status='failed', stage=stage))
        raise


def qualify(output, tools, engine, splicer, prepared_native):
    output, tools, engine, splicer, prepared_native = (
        Path(path).resolve() for path in (output, tools, engine, splicer, prepared_native))
    require(output != ROOT and ROOT not in output.parents, 'buffer-output-outside-checkout')
    require(all(output != path and output not in path.parents and path not in output.parents
        for path in (tools, engine, splicer, prepared_native)), 'buffer-input-output-separation')
    original_native = host.verify_prepared(prepared_native)
    originals = host.native_products(prepared_native)
    require(set(originals) == set(PRODUCTS), 'buffer-normal-five-host-products')
    output = fresh(output)
    stage = 'normal-project-capture'
    try:
        app = fixture.project(output/'application')
        source = inventory(snapshot(app))
        write_json(output/'native-inputs.json', original_native)
        selected = fresh(output/'selected-native')
        binaries = {name: selected/name for name in PRODUCTS}
        for name, original in originals.items():
            shutil.copyfile(original, binaries[name])
            binaries[name].chmod(0o700)
        identities = {name: file_identity(path, 512*1024**2) for name, path in originals.items()}
        require(identities == {name: file_identity(path, 512*1024**2) for name, path in binaries.items()},
            'buffer-host-copy-byte-identity')
        stage = 'normal-typecheck-bundle-component-package'
        artifact = build(app, output/'build', binaries['capsule_contracts'], binaries['package'],
            'https://github.com/KirilsTurkins/latent-service-fabric', tools=tools,
            runtime_engine=engine/'engine.wasm', runtime_engine_receipt=engine/'engine-input.json',
            runtime_splicer=splicer/'splicer', runtime_splicer_receipt=splicer/'splicer-input.json')
        stage = 'eight-signed-standalone-invocations'
        observed = execute(artifact, binaries, output/'node')
        require(host.verify_prepared(prepared_native) == original_native
            and identities == {name: file_identity(path, 512*1024**2) for name, path in binaries.items()}
            and source == inventory(snapshot(app)), 'buffer-original-inputs-unchanged')
        result = {'schemaVersion': 'latent.typescript.signed-buffer-subset.v1', 'status': 'passed',
            'fullTicketQualification': False, 'sourceIdentityDigest': digest(source),
            'runtimeProfile': IMPORT_PROFILE, 'bufferProfile': buffer_profile.PROFILE,
            'nativeTuple': original_native, 'build': file_identity(artifact/'BUILD-COMPLETE.json'),
            'component': file_identity(artifact/'component.wasm'),
            'execution': file_identity(output/'node/qualification.json'),
            'cases': [row['case'] for row in observed['cases']],
            'remainingAcceptance': ['unchanged-published-dependency', 'node-net-Socket', 'Duplex-backpressure',
                'borrow-and-typed-own-result-disposal', 'destroy-cancel-unref-root-lifecycle']}
        write_json(output/'qualification.json', result)
        return result
    except BaseException:
        write_json(output/'FAILED.json', {'status': 'failed', 'stage': stage, 'fullTicketQualification': False})
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('output', 'tools', 'engine', 'splicer', 'prepared-native'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(qualify(args.output, args.tools, args.engine, args.splicer, args.prepared_native)))

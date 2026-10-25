"""Six finite signed initializer/constructor/callback observations.

Compiler method observations stay separate from these actual CLI outcomes.
Neither graph membership nor a generic guest trap identifies an API cause.
"""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import time

from tools import compiler_compatibility_fixture as fixture
from tools import resource_tenant_node as resources
from tools import guest_compatibility, guest_compatibility_context, guest_compatibility_outcomes
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.java_resource_runtime_node import LIMITS, OPERATIONS, _grant
from tools.java_http_release_preparation import prepare
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import (RecordingClient, call, configure, delete_all,
    deploy, finish_call, sample, selected_revision, start_call)
from tools.rust_capsule_project import ROOT, digest, fresh, read_file, read_json, write_json
from tools.run_rust_capsule_workflow import write_workflow_receipt
from tools.sdk_provider_scenario import close_failed_provider, start_provider
from tools.resource_runtime_node import integer

CASES = (('init', 'init'), ('callback', 'callback'), ('init-trap', 'init-trap'),
    ('fresh', 'after-init-trap'), ('callback-trap', 'callback-trap'), ('fresh', 'after-callback-trap'))
ZERO = ('outboundRequests', 'childCalls', 'logBytes', 'effectCount', 'stateReadBytes',
    'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes')


def configure_runtime(settings, capsule, language):
    rows = capsule.get('imports')
    require(type(rows) is list and len(rows) == len(fixture.DECLARATIONS[language])
        and all(type(row) is dict and set(row) == {'contract', 'optional'}
            and row['optional'] is False for row in rows)
        and {row['contract'] for row in rows} == set(fixture.DECLARATIONS[language]),
        'compiler-diagnostics-exact-declared-runtime')
    resources.configure(settings, {**capsule, 'imports': [row for row in rows
        if row['contract'] != fixture.ACTIVATION]}, language)
    providers = settings['providers']
    providers['activationRuntime'] = {'identity': {'id': 'activation', 'tenant': 'examples',
        'service': 'activation-host', 'epoch': 1}, 'limits': dict(LIMITS)}
    providers['bindings'].append({'name': 'activation-examples', 'tenant': 'examples',
        'consumerService': 'my-greeting', 'providerService': 'activation-host',
        'contract': fixture.ACTIVATION, 'providerBinding': 'activation-examples-installed'})
    scalars = set(fixture.DECLARATIONS[language]) - {fixture.ACTIVATION}
    names = {resources.PROFILES[name][0] for name in scalars}
    require(set(providers) == {'formatVersion', 'http', 'bindings', 'scalarAliases', 'activationRuntime', *names}
        and len(providers['bindings']) == 2+2*len(scalars) <= 16
        and len(providers['scalarAliases']) == len(scalars) and 2+2*len(scalars) <= 14,
        'compiler-diagnostics-original-configuration-bounds')


def idle(client, target):
    value = client.call('capability', 'list', '--deployment', target['name'], '--include-node-usage')['data']
    usage = value['nodeUsage']
    require(value['nextPageToken'] is None and type(usage) is dict and usage['scope'] == 'node'
        and type(usage['unavailable']) is list and usage['unavailable'] == []
        and type(usage['counters']) is dict and all(name in usage['counters'] for name in ACTIVE_COUNTERS)
        and all(integer(usage['counters'][name]) == 0 for name in ACTIVE_COUNTERS),
        'compiler-diagnostics-eighteen-provider-owners-zero')
    return usage


def invocation(row, revision, component, language, mode):
    require(mode in {mode for mode, _ in CASES}, 'compiler-diagnostics-finite-mode')
    response = row['response']; data = response['data']; usage = data['consumption']
    require(row['processReaped'] is True and response['outcomeKnown'] is True
        and data['resolvedRevision'] == revision and revision['releaseDigest'] == component,
        'compiler-diagnostics-exact-signed-revision')
    maximum = 67108864 if language == 'java' else 134217728
    require(0 < integer(usage['cpuFuel']) <= 1000000000
        and 0 < integer(usage['peakMemoryBytes']) <= maximum
        and all(integer(usage[key]) == 0 for key in ZERO),
        'compiler-diagnostics-original-budget-and-no-ambient-effects')
    if mode.endswith('-trap'):
        require(row['exitCode'] == 4 and response['error']['code'] == 'guest-trap'
            and row['decoded'] is None, 'compiler-diagnostics-original-uncaught-terminal')
    else:
        suffix = ('|finally=1' if language == 'java' else '|joined=1') if mode == 'callback' else ''
        expected = 'diagnostics|'+mode+'|init=1|ctor=1|denied='+('3' if mode == 'callback' else '2') \
            +'|fallback=42'+suffix+'|fresh=1'
        require(row['exitCode'] == 0 and row['decoded'] == [{'ok': expected}],
            'compiler-diagnostics-original-catch-fallback-and-fresh-state')


def programme(client, target, probe, output, component, language, *, capture=None):
    result = {'status': 'incomplete', 'cases': [], 'attempts': [],
        'graphIsRuntimeProof': False, 'genericTrapApiCause': 'unknown',
        'postRetiredStoreCallbackQualified': False, 'workerDrainQualified': False}
    def checkpoint():
        encoded = (json.dumps(result, sort_keys=True, separators=(',', ':'))+'\n').encode()
        require(len(encoded) <= 1024*1024, 'compiler-diagnostics-progress-retention-bound')
        (output/'programme-progress.json').write_bytes(encoded)
        if capture is not None:
            observed = capture.snapshot()
            guest_compatibility_outcomes.validate(observed, selected_context=capture.context)
            (output/'compatibility-outcomes.json').write_bytes(
                (json.dumps(observed, sort_keys=True, separators=(',', ':'))+'\n').encode())
    for mode, label in CASES:
        name = 'diagnostics-'+language+'-'+label
        revision = selected_revision(client, target)
        try:
            pending = start_call(client, target, 'greeting', 'greet', [mode], name)
            try:
                row = finish_call(client, pending)
            finally:
                pending.close()
                # Preserve a closed partial process record even if completion
                # or JSON parsing failed before the ordinary raw case writer.
                # No exception strings, backtraces or arbitrary stderr upload.
                write_json(output/('process-'+name+'.json'), {'label': label,
                    'processReaped': pending.owner.finished,
                    'stdout': {'digest': digest(bytes(pending.buffers[0])), 'bytes': len(pending.buffers[0])},
                    'stderr': {'digest': digest(bytes(pending.buffers[1])), 'bytes': len(pending.buffers[1])}})
            result['attempts'].append({'mode': mode, 'label': label, 'invocation': row})
            if capture is not None:
                capture.observe(label, row['response'], row['processReaped'], expected_revision=revision)
            checkpoint()
            invocation(row, revision, component, language, mode)
            retired = {'provider': idle(client, target), 'physical': sample(client, probe, name, 1)}
            write_json(output/('retired-'+name+'.json'), retired)
            result['cases'].append({'mode': mode, 'label': label, 'invocation': row, 'retirement': retired})
            checkpoint()
        except BaseException as error:
            result.update(status='failed', failureLabel=label, errorCategory=type(error).__name__)
            checkpoint(); raise
    require(len(result['cases']) == 6, 'compiler-diagnostics-six-actual-results')
    result['status'] = 'passed'; write_json(output/'programme.json', result); return result


def execute(artifact, native, output, deadline, language, before):
    output = fresh(output); capsule = read_json(artifact/'capsule.json')
    remaining = int(min(900, deadline-time.monotonic()))
    require(remaining >= 180, 'compiler-diagnostics-original-node-deadline')
    commands = Commands(ROOT, fresh(output/'commands'), build_environment(output),
        deadline_seconds=remaining, command_seconds=120)
    commands.deadline = min(commands.deadline, deadline - 5)
    record = {'schemaVersion': 'latent.compiler-diagnostics.node.v1', 'language': language,
        'status': 'incomplete', 'build': before, 'crossTenantQualification': False}
    node = peer = client = None; stage = 'normal-neutral-signing'
    try:
        signed = output/'signed'
        commands.run(stage, native['capsule_authoring'], 'demo-sign-neutral-resources', signed, artifact)
        signature = read_json(signed/'release-set.json'); release = signature['releases'][0]
        require(signature['schemaVersion'] == 'latent.capsule.demo.v1' and signature.get('tenant') is None
            and signature['tenants'] == ['examples', 'foreign'] and signature['packagingOnly'] is True
            and signature['componentCompilationPerformed'] is False
            and signature['trust'] == 'isolated-neutral-resource-two-tenant-test-only'
            and signature['expiresAtUnixSeconds'] > time.time()+180 and len(signature['releases']) == 1
            and capsule['metadata'] == {'name': 'examples/my-greeting', 'tenant': 'examples'}
            and capsule['exports'] == ['examples:greeting/api@1.0.0']
            and capsule['component']['world'] == release['world'] == 'examples:greeting/service@1.0.0'
            and release['name'] == release['service'] == 'my-greeting'
            and release['componentDigest'] == capsule['component']['digest'] == before['component']['sha256'],
            'compiler-diagnostics-normal-signed-world-and-component')
        record['signedRelease'] = release
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-compiler-diagnostics-') as tmp:
            work = Path(tmp)
            for name in ('examples', 'node', 'peer'): (work/name).mkdir(mode=0o700)
            client = RecordingClient(native['latent'], work/'examples', cancellation, commands.deadline,
                evidence=output/'controls', invocation_timeout_millis=120000, control_timeout_millis=15000)
            peer, port = start_provider(client, work/'peer', maximum_seconds=remaining)
            try:
                config, settings = configure(work/'node', signed, port, language=language)
                configure_runtime(settings, capsule, language)
                config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':'))+'\n').encode())
                stage = 'ordinary-enforced-node-startup'
                node = connect(client, native['latentd'], work/'node', config, 'examples', 0)
                record['startup'] = node.startup_record; probe = Probe(node, file_identity(native['latentd']))
                published = client.call('release', 'publish-package', signed/'my-greeting/package', '--evidence',
                    signed/'my-greeting/evidence/index.json', '--operation-id', 'compiler-diagnostics-publish',
                    '--expected-generation', '0')
                require(published['outcomeKnown'] is True and published['category'] == 'success'
                    and published['data']['release']['digest'] == before['component']['sha256'],
                    'compiler-diagnostics-normal-admission')
                publication = published['data']['operation']['publication']['id']
                record['preparation'] = prepare(client, publication, 'examples', before['component']['sha256'], output)
                manifest = client.directory/'deployment.json'
                write_json(manifest, resources.scoped_deployment(read_json(signed/'my-greeting/deployment.json'), 'examples'))
                target = deploy(client, manifest, publication)
                scalars = [name for name in fixture.DECLARATIONS[language] if name != fixture.ACTIVATION]
                target = resources.install_grants(client, node, manifest, publication, target, scalars, language, 'examples')
                denied = call(client, target, 'greeting', 'greet', ['init'], 'diagnostics-without-activation')
                resources.require_denied_before_guest(denied)
                record['missingActivationGrant'] = {'invocation': denied, 'provider': idle(client, target),
                    'physical': sample(client, probe, 'diagnostics-without-activation', 1)}
                target = _grant(client, node, manifest, publication, target, 'examples', capability=fixture.ACTIVATION,
                    name='activation', profile='activation-owned-v1', kind='clock', operations=OPERATIONS,
                    service='activation-host')
                require({row['capability'] for row in target['grants']} == set(fixture.DECLARATIONS[language]),
                    'compiler-diagnostics-only-explicit-profile-grants')
                stage = 'six-ordinary-signed-constructor-initializer-and-callback-cases'
                report = guest_compatibility.read(read_file(artifact/'compatibility-report.json', 65536))
                context = guest_compatibility_context.read(read_file(artifact/'compatibility-context.json', 65536),
                    report=report, source=before['documents']['source-inputs.json']['sha256'],
                    component=before['component']['sha256'])
                capture = guest_compatibility_outcomes.Capture(before['documents']['source-inputs.json']['sha256'],
                    before['component']['sha256'], context)
                record['programme'] = programme(client, target, probe, output, before['component']['sha256'], language,
                    capture=capture)
                record['compatibilityOutcomes'] = file_identity(output/'compatibility-outcomes.json', 65536)
                delete_all(client, [target['name']]); record['afterDeletes'] = sample(client, probe, 'after-deletes', 0)
                stop(client, node); record['nodeShutdown'] = stopped_record(node)
                record['peerShutdown'] = stop_observation_peer(peer)
            finally:
                client.node = None
                if node is not None: node.close(); (output/'node-stderr.txt').write_bytes(bytes(node.buffers[1]))
                if peer is not None:
                    if 'peerShutdown' not in record: record['peerFailure'] = close_failed_provider(peer)
                    else: peer.close()
            cancellation.check()
        require(record['nodeShutdown']['reaped'] is True and record['nodeShutdown']['record']['clean'] is True
            and client.calls <= 192 and time.monotonic() < commands.deadline,
            'compiler-diagnostics-clean-final-ownership-and-original-deadline')
        record.update(status='passed', commands=commands.records, cliCalls=client.calls)
        write_workflow_receipt(output/'qualified.json', record); return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_workflow_receipt(output/'FAILED.json', record); raise

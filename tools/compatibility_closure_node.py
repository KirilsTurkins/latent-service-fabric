"""Finite actual-component oracles on the original signing/node/process owners.

Management operation facts remain explicitly unbound to implementation and
never replace an invocation's original terminal error. No new failure ledger,
retry right, observer hook or accounting authority is introduced here.
"""
from __future__ import annotations

import time

from tools import guest_compatibility_outcomes as outcomes
from tools import resource_tenant_node as providers
from tools.dev_workflow.node_scenarios import _collect_node_observations
from tools.dev_workflow.common import encode, require
from tools.resource_runtime_node import integer
from tools.rust_capsule_node import call, sample, selected_revision
from tools.rust_capsule_project import write_json

ZERO_EFFECTS = ('outboundRequests', 'childCalls', 'effectCount', 'stateReadBytes',
                'stateWriteBytes', 'blobReadBytes', 'blobWriteBytes')
RESOURCE_EXPECTED = {'task-limit': (17, 'tasks', 16, 17), 'timer-limit': (19, 'timers', 8, 9),
    'queue-8': (18, 'queues', 8, 9), 'queue-9': (18, 'queues', 9, 10)}


def original_invocation(row, revision, component, budget):
    response = row['response']
    require(row['processReaped'] is True and response['outcomeKnown'] is True
        and response['data']['resolvedRevision'] == revision and revision['releaseDigest'] == component,
        'compatibility-closure-original-reaped-revision')
    usage = response['data']['consumption']
    # A no-memory pure engine component can legitimately peak at zero linear
    # memory. No page/stack count is invented for it.
    require(0 < integer(usage['cpuFuel']) <= budget['cpuFuel']
        and 0 <= integer(usage['peakMemoryBytes']) <= budget['memoryBytes']
        and all(integer(usage[name]) == 0 for name in ZERO_EFFECTS)
        and integer(usage['logBytes']) <= budget['logBytes'], 'compatibility-closure-original-budgets')
    return outcomes.original(response)


def operation_refusal(row, mode, captured):
    """One original failed operation, explicitly NOT a terminal-cause claim."""
    require(mode in RESOURCE_EXPECTED, 'compatibility-closure-fixed-resource-mode')
    reason, dimension, bound, requested = RESOURCE_EXPECTED[mode]
    require(row['exitCode'] == 4 and row['response']['category'] == 'platform-failure'
        and row['response']['error']['code'] in {'guest-trap', 'guest-runtime-error'},
        'compatibility-closure-original-resource-terminal')
    outcomes.validate(captured)
    matches = [value for value in captured['cases'] if value['case'] == row['activation']]
    require(len(matches) == 1 and matches[0]['targetMatches'] is True,
        'compatibility-closure-original-resource-case')
    original = outcomes.original(row['response'])
    require(all(matches[0][key] == original[key] for key in
        ('cause', 'activationDiagnostic', 'resourceDimension', 'physicalRetirement')),
        'compatibility-closure-management-does-not-replace-terminal-cause')
    fact = matches[0].get('nodeDiagnostic')
    outcomes.validate_node_observation(fact)
    require(fact['state'] == 'observed' and fact['scope'] == 'activation-id-service-only'
        and fact['implementationBinding'] == 'unavailable' and fact['resourceDimension'] == dimension
        and fact['fields']['reason'] == str(reason) and fact['fields'].get('configured_bound') == str(bound)
        and fact['fields'].get('calculated_requirement') == str(requested),
        'compatibility-closure-actual-original-resource-operation')
    return {'observedOperationResource': dimension, 'operationFact': fact,
        'terminalCause': original['cause'], 'implementationBinding': 'unavailable',
        'apiAttributionFromManagementFact': False}


def stack_refusal(row):
    original = outcomes.original(row['response'])
    require(row['exitCode'] == 4 and row['response']['error']['code'] == 'guest-trap'
        and original['activationDiagnostic']['state'] == 'observed'
        and original['activationDiagnostic']['fields']['reason'] == '26'
        and original['cause'] == 'resource-exhausted' and original['resourceDimension'] == 'guest-stack',
        'compatibility-closure-original-engine-StackOverflow-only')
    return original


def programme(client, target, probe, output, component, *, kind, expected=None, capture=None, queue_ceiling=None):
    require(kind in {'api-pair', 'typescript-resources', 'go-queues'}, 'compatibility-closure-fixed-node-kind')
    require(kind != 'api-pair' or type(expected) is list and len(expected) == 1, 'compatibility-closure-fixed-api-result')
    require(queue_ceiling is None if kind != 'go-queues' else type(queue_ceiling) is int and queue_ceiling in (8, 9),
        'compatibility-closure-fixed-original-queue-ceiling')
    cases = ([('probe', 'probe'), ('probe', 'fresh-after-probe')] if kind == 'api-pair' else
        [('task-limit', 'task-limit'), ('fresh', 'fresh-after-task'), ('timer-limit', 'timer-limit'), ('fresh', 'fresh-after-timer')]
        if kind == 'typescript-resources' else [('fresh', 'queue-8')]
        if queue_ceiling == 8 else [('fresh', 'fresh-before-queue'), ('parallel', 'queue-9'), ('fresh', 'fresh-after-queue')])
    result = {'status': 'incomplete', 'kind': kind, 'cases': [], 'attempts': [],
        'managementImplementationBinding': 'unavailable', 'arbitraryApiSafety': 'unknown'}
    def checkpoint():
        raw = encode(result)
        require(len(raw) <= 1024 * 1024, 'compatibility-closure-progress-bound')
        (output / 'programme-progress.json').write_bytes(raw)
    for mode, label in cases:
        require(time.monotonic() < client.deadline, 'compatibility-closure-original-node-deadline')
        revision = selected_revision(client, target)
        interface, function = ('resource-runtime', 'run') if kind == 'typescript-resources' else \
            ('greeting', 'greet')
        activation = 'compatibility-' + label
        argument = 'resource-runtime:' + mode if kind == 'go-queues' else mode
        row = call(client, target, interface, function, [argument], activation)
        result['attempts'].append(row); checkpoint()
        original = original_invocation(row, revision, component, target['budget'])
        fact = None
        refusal = mode if kind == 'typescript-resources' and mode in RESOURCE_EXPECTED else \
            label if kind == 'go-queues' and label in RESOURCE_EXPECTED else None
        if refusal is not None:
            require(capture is not None, 'compatibility-closure-original-diagnostic-capture')
            capture.observe(activation, row['response'], row['processReaped'], expected_revision=revision)
            _collect_node_observations(capture, client, [(activation, row['activation'], target['service'])], client.deadline)
            fact = operation_refusal(row, refusal, capture.snapshot())
            (output / 'compatibility-outcomes.json').write_bytes(encode(capture.snapshot()))
        else:
            if kind == 'go-queues':
                from tools.go_resource_runtime_fixture import EXPECTED
                answer = [{'ok': EXPECTED[mode]}]
            else:
                answer = ['compatibility-resource|fresh=1'] if kind == 'typescript-resources' else expected
            require(row['exitCode'] == 0 and row['decoded'] == answer,
                'compatibility-closure-original-success-or-fresh-result')
        retired = {'provider': providers.provider_idle(client, target),
            'physical': sample(client, probe, activation + '-retired', 1)}
        result['cases'].append({'label': label, 'mode': mode, 'invocation': row,
            'originalDiagnostic': original, 'operationObservation': fact, 'retirement': retired})
        checkpoint()
    result['status'] = 'passed'; write_json(output / 'programme.json', result)
    return result


def execute(artifact, native, output, deadline, language, *, kind, expected=None, queue_ceiling=None):
    """Use the existing neutral signer, one node/peer, grants and teardown.

    The pure engine Stack cell is not routed through this signer: it has no
    language-compiler build provenance and must not impersonate a Rust build.
    """
    import json
    from pathlib import Path
    import tempfile
    from tools import guest_compatibility, guest_compatibility_context
    from tools import resource_runtime_node
    from tools.build_observation import build_environment
    from tools.build_process_signals import owned_cancellation
    from tools.phase2_operator_process import stopped_record
    from tools.phase2_operator_scenario import connect, stop
    from tools.phase3_resource_identity import file_identity
    from tools.phase3_resource_os import Probe
    from tools.qualify_resource_tenants import stop_observation_peer
    from tools.rust_capsule_build import Commands
    from tools.rust_capsule_node import RecordingClient, configure, delete_all, deploy
    from tools.rust_capsule_project import ROOT, fresh, read_file, read_json
    from tools.run_rust_capsule_workflow import write_workflow_receipt
    from tools.sdk_provider_scenario import close_failed_provider, start_provider
    require(language in {'c', 'rust', 'go', 'dotnet', 'typescript'}
        and kind in {'api-pair', 'typescript-resources', 'go-queues'}
        and (kind != 'typescript-resources' or language == 'typescript')
        and (kind != 'go-queues' or language == 'go' and type(queue_ceiling) is int and queue_ceiling in (8, 9))
        and (kind == 'go-queues' or queue_ceiling is None), 'compatibility-closure-real-language-signing-route')
    remaining = int(min(600, deadline - time.monotonic()))
    require(remaining >= 180, 'compatibility-closure-existing-node-budget')
    output = fresh(output)
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
        deadline_seconds=remaining, command_seconds=120)
    commands.deadline = min(commands.deadline, deadline - 5)
    capsule = read_json(artifact / 'capsule.json')
    component = file_identity(artifact / 'component.wasm', 64 * 1024 * 1024)
    require(capsule['metadata'] == {'name': 'examples/my-greeting', 'tenant': 'examples'}
        and capsule['component']['digest'] == component['sha256'], 'compatibility-closure-normal-greeting-signing-input')
    record = {'status': 'incomplete', 'language': language, 'kind': kind, 'component': component,
        'arbitraryApiSafety': 'unknown', 'managementImplementationBinding': 'unavailable'}
    node = peer = client = None
    stage = 'normal-neutral-signing'
    try:
        signed = output / 'signed'
        commands.run(stage, native['capsule_authoring'], 'demo-sign-neutral-resources', signed, artifact)
        signature = read_json(signed / 'release-set.json')
        require(signature['schemaVersion'] == 'latent.capsule.demo.v1' and signature.get('tenant') is None
            and signature['tenants'] == ['examples', 'foreign'] and signature['packagingOnly'] is True
            and signature['componentCompilationPerformed'] is False
            and signature['trust'] == 'isolated-neutral-resource-two-tenant-test-only'
            and signature['expiresAtUnixSeconds'] > time.time() + 180 and len(signature['releases']) == 1,
            'compatibility-closure-original-neutral-signature')
        release = signature['releases'][0]
        require(release['componentDigest'] == component['sha256']
            and release['name'] == release['service'] == 'my-greeting'
            and release['world'] == capsule['component']['world'], 'compatibility-closure-exact-signed-component')
        record['signedRelease'] = release
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-compatibility-closure-') as temporary:
            work = Path(temporary)
            for name in ('examples', 'node', 'peer'): (work / name).mkdir(mode=0o700)
            # Retain the original deadline's cleanup reserve. The constructor
            # cannot renew elapsed setup into a fresh node execution budget.
            client = RecordingClient(native['latent'], work / 'examples', cancellation, commands.deadline,
                evidence=output / 'controls', invocation_timeout_millis=120000, control_timeout_millis=15000)
            peer, port = start_provider(client, work / 'peer', maximum_seconds=remaining)
            try:
                config, settings = configure(work / 'node', signed, port, language=language)
                if kind in {'typescript-resources', 'go-queues'}:
                    resource_runtime_node.configure(settings, capsule, language=language, go_queue_ceiling=queue_ceiling)
                else: providers.configure(settings, capsule, language)
                config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
                stage = 'normal-enforced-node'
                node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)
                record['startup'] = node.startup_record
                probe = Probe(node, file_identity(native['latentd']))
                published = client.call('release', 'publish-package', signed / 'my-greeting/package', '--evidence',
                    signed / 'my-greeting/evidence/index.json', '--operation-id', 'compatibility-publish', '--expected-generation', '0')
                require(published['outcomeKnown'] is True and published['data']['release']['digest'] == component['sha256'],
                    'compatibility-closure-real-package-admission')
                publication = published['data']['operation']['publication']['id']
                manifest = client.directory / 'deployment.json'
                write_json(manifest, providers.scoped_deployment(read_json(signed / 'my-greeting/deployment.json'), 'examples'))
                target = deploy(client, manifest, publication)
                if kind in {'typescript-resources', 'go-queues'}:
                    target, denied = resource_runtime_node.grant(client, node, manifest, publication, target, 'examples', language=language)
                    record['originalMissingGrant'] = denied
                else:
                    imports = providers.required_imports(capsule)
                    if imports:
                        target = providers.install_grants(client, node, manifest, publication, target, imports, language, 'examples')
                report = guest_compatibility.read(read_file(artifact / 'compatibility-report.json', 65536))
                selected = guest_compatibility_context.read(read_file(artifact / 'compatibility-context.json', 65536),
                    report=report, component=component['sha256'])
                record['targetBudget'] = dict(target['budget'])
                record['targetService'] = target['service']
                capture = outcomes.Capture(report['sourceDigest'], component['sha256'], selected)
                stage = 'actual-fixed-components-and-fresh-invocations'
                record['programme'] = programme(client, target, probe, output, component['sha256'],
                    kind=kind, expected=expected, capture=capture, queue_ceiling=queue_ceiling)
                delete_all(client, [target['name']]); record['afterDeletes'] = sample(client, probe, 'after-deletes', 0)
                stop(client, node); record['nodeShutdown'] = stopped_record(node)
                record['peerShutdown'] = stop_observation_peer(peer)
            finally:
                client.node = None
                if node is not None: node.close()
                if peer is not None:
                    if 'peerShutdown' not in record: record['peerFailure'] = close_failed_provider(peer)
                    else: peer.close()
            cancellation.check()
        require(record['nodeShutdown']['reaped'] is True and record['nodeShutdown']['record']['clean'] is True
            and client.calls <= 192 and time.monotonic() < commands.deadline,
            'compatibility-closure-original-deadline-and-physical-shutdown')
        record.update(status='passed', commands=commands.records, cliCalls=client.calls)
        write_workflow_receipt(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__, commands=commands.records)
        write_workflow_receipt(output / 'FAILED.json', record)
        raise

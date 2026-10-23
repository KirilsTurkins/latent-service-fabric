"""Three signed Audit ownership observations using exact separately frozen inputs.

No host, compiler, standard library or guest source is rebuilt. The277 CLI/node,
three193 helpers and original C36 guest retain their distinct original origins.
"""
from pathlib import Path
import argparse
import copy
import json
import re
import subprocess
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import audit_memory_native_products as hosts, audit_c36_component as guest
from tools import c_thread_runtime_node as original, c_timed_runtime_node as timed
from tools.build_observation import build_environment
from tools.build_process_signals import owned_cancellation
from tools.java_replay_materials import git_source_identity
from tools.phase2_operator_process import require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity, inventory
from tools.phase3_resource_os import Probe
from tools.phase3_resource_profile import integer
from tools.qualify_c_timed_runtime import materials as original_materials
from tools.qualify_resource_tenants import stop_observation_peer
from tools.rust_capsule_build import Commands
from tools.rust_capsule_node import RecordingClient, configure as configure_base, delete_all, deploy, sample
from tools.rust_capsule_project import ROOT, fresh, read_json, write_json
from tools.sdk_provider_scenario import start_provider

RANDOM = 'latent:random/random@0.1.0'
SERVICE = original.SERVICE
BANK = ('maximum_bytes', 'reserved_bytes', 'fixed_reserved_bytes',
        'transient_reserved_bytes', 'quarantined_reserved_bytes')
EXTRA_MATERIALS = ('.github/workflows/audit-signed-runtime.yml',
    'tools/qualify_audit_signed_runtime.py', 'tools/audit_memory_native_products.py',
    'tools/audit_c36_component.py', guest.MANIFEST, 'tools/rust_thread_native_products.py',
    'tools/tests/test_audit_signed_runtime.py', 'tools/tests/test_audit_c36_component.py',
    'tools/tests/test_audit_memory_native_products.py')


def inputs():
    result = original_materials()
    result.update({name: file_identity(ROOT / name, 4 * 1024**2) for name in EXTRA_MATERIALS})
    require(len(result) <= 256 and sum(row['bytes'] for row in result.values()) <= 16 * 1024**2,
            'audit-signed-helper-material-bound')
    return dict(sorted(result.items()))


def bank_observation(value):
    counters = value['nodeUsage']['counters']
    bank = {name: integer(counters['audit_node_metadata_' + name]) for name in BANK}
    bank['broker_metadata_bytes'] = integer(counters['broker_metadata_bytes'])
    require(bank['maximum_bytes'] == 8 * 1024**2 and bank['fixed_reserved_bytes'] > 0
        and bank['reserved_bytes'] == bank['fixed_reserved_bytes'] + bank['transient_reserved_bytes']
        and bank['reserved_bytes'] <= bank['maximum_bytes']
        and bank['quarantined_reserved_bytes'] == 0
        and bank['broker_metadata_bytes'] <= bank['transient_reserved_bytes'],
        'audit-signed-original-bank-conservation')
    # Installed providers and compiled plans retain their original broker
    # metadata. At the existing nine-counter audit idle boundary, the separate
    # original-bank transient remainder must actually retire to zero.
    bank['non_broker_transient_bytes'] = bank['transient_reserved_bytes'] - bank['broker_metadata_bytes']
    require(bank['non_broker_transient_bytes'] == 0, 'audit-signed-actual-audit-transient-retirement')
    return bank


def required_random_policy(value):
    require(type(value) is dict and len(value.get('rules', [])) == 1, 'audit-signed-original-random-policy')
    rule = value['rules'][0]
    require(rule.get('capability') == RANDOM and rule.get('operations') == ['bytes']
            and rule.get('resources') == {'kind': 'random'}
            and rule.get('ceiling', {}).get('inputBytes') == 8
            and rule.get('requireAudit', False) is False, 'audit-signed-original-random-authority')
    selected = copy.deepcopy(value)
    selected['rules'][0]['requireAudit'] = True
    return selected


def policy_record(value, identity, kind, document):
    current = value.get('data', {}).get('policy', {})
    generation = current.get('generation')
    require(value.get('category') == 'success' and value.get('outcomeKnown') is True
        and value.get('requestDispatched') is True and current.get('tenant') == 'examples'
        and current.get('id') == identity and current.get('recordKind') == kind
        and current.get('revoked') is False and current.get('document') == document
        and type(generation) is str and re.fullmatch('[1-9][0-9]{0,19}', generation)
        and int(generation) < 2**64, 'audit-signed-observed-original-policy-generation')
    return {'id': identity, 'revision': generation}


def critical_pair(pages, activation, revision, provider, authority):
    coverage = original.positive_audit_coverage(pages)
    attempts, outcomes = [], []
    for page in pages:
        for row in page['data']['records']:
            data = row['data']
            for kind, selected in (('attempt', attempts), ('outcome', outcomes)):
                event = data.get(kind)
                if not isinstance(event, dict):
                    continue
                identities = event.get('identities', {})
                context = identities.get('capability', {})
                if context.get('activation') != activation or context.get('capability') != RANDOM:
                    continue
                require(context.get('required') is True and context.get('rootActivation') == activation
                    and context.get('service') == 'examples/' + SERVICE
                    and context.get('providerProfile') == 'system-random-v1'
                    and context.get('operation') == 'bytes'
                    and context.get('providerConfigurationDigest') == provider['configurationDigest']
                    and integer(context['providerConfigurationEpoch']) == integer(provider['configurationEpoch'])
                    and context.get('binding', {}).get('id') == authority['binding']['id']
                    and context['binding']['revision'] == authority['binding']['revision']
                    and any(policy['id'] == authority['policy']['id']
                            and policy['revision'] == authority['policy']['revision']
                            for policy in context.get('policies', [])), 'audit-signed-required-original-policy-and-provider')
                require(identities.get('publicationId') == revision['publicationId']
                    and identities.get('componentDigest') == revision['releaseDigest']
                    and identities.get('revision') == revision['revisionId']
                    and integer(identities['routeGeneration']) == integer(revision['routeGeneration']),
                    'audit-signed-current-published-revision')
                selected.append((row, event))
    require(len(attempts) == len(outcomes) == 1, 'audit-signed-one-real-required-random-pair')
    attempt_row, attempt = attempts[0]
    outcome_row, outcome = outcomes[0]
    require(attempt['action'] == 'AUDIT_CONTROL_ACTION_CAPABILITY_CALL'
        and attempt.get('replay') is False and outcome.get('replay') is False
        and outcome['result'] == 'AUDIT_OPERATION_RESULT_COMMITTED'
        and outcome['identities']['capability']['providerOutcome'] == 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED'
        and outcome['attemptSequence'] == attempt_row['sequence']
        and attempt_row['epoch'] == outcome_row['epoch']
        and 0 < integer(attempt_row['sequence']) < integer(outcome_row['sequence']),
        'audit-signed-durable-attempt-and-host-completed-outcome')
    expected = copy.deepcopy(attempt['identities'])
    expected['capability']['providerOutcome'] = 'AUDIT_PROVIDER_OUTCOME_HOST_COMPLETED'
    require(outcome['identities'] == expected, 'audit-signed-same-original-attempt-authority')
    return {'activation': activation, 'epoch': attempt_row['epoch'], 'attemptSequence': attempt_row['sequence'],
        'outcomeSequence': outcome_row['sequence'], 'attempt': attempt, 'outcome': outcome,
        'coverage': coverage, 'requiredAudit': True, 'optionalCaptureLosslessnessClaimed': False}


def pair_pages(client, output, activation):
    pages, tokens, token = [], set(), None
    for index in range(4):
        command = ('audit', 'query', '--scope', 'tenant', '--page-size', '64')
        if token is not None:
            command += ('--page-token', token)
        page = client.call(*command)
        pages.append(page)
        write_json(output / f'audit-required-{activation}-{index}.json', page)
        token = page['data']['page']['nextPageToken']
        if token is None:
            return pages
        require(token not in tokens, 'audit-signed-no-cursor-cycle')
        tokens.add(token)
    raise ValueError('audit-signed-required-audit-page-bound')


def retain_required_failure(client, target, output):
    """Two existing read-only controls; never retry or replace the failed call."""
    evidence = {'diagnosticOnly': True, 'successClaimed': False, 'reads': []}
    deadline = min(client.deadline, time.monotonic() + 10)
    invocation = read_json(output / 'invocation-audit-required-random.json')
    started = integer(invocation['startedAtUnixMillis'])
    require(started > 0, 'audit-signed-failure-original-invocation-time')
    commands = (
        ('audit', ('audit', 'query', '--scope', 'tenant', '--page-size', '64',
                   '--from-unix-millis', str(started - 1))),
        ('usage', ('capability', 'list', '--deployment', target['name'], '--include-node-usage')))
    for label, command in commands:
        try:
            remaining = deadline - time.monotonic()
            require(remaining > 0, 'audit-signed-failure-observation-deadline')
            value = client.call(*command, codes=(0, 2, 3, 4, 5, 6, 130), timeout=min(5, remaining))
            require(len(json.dumps(value).encode()) <= 262144, 'audit-signed-failure-observation-size')
            write_json(output / ('required-failure-' + label + '.json'), value)
            evidence['reads'].append({'kind': label, 'captured': True})
        except Exception as error:
            evidence['reads'].append({'kind': label, 'captured': False, 'errorType': type(error).__name__})
    write_json(output / 'required-failure-observation.json', evidence)


def programme(client, node, probe, source, target, output):
    grants = timed.install(client, node, target)
    target = deploy(client, source / 'deployment.json', target['publication'],
                    generation=str(target['generation']), grants=grants)
    baseline = original.wait_audit_idle(client, target, output, 'audit-original-baseline')
    baseline_bank = bank_observation(baseline)
    first = original.invoke(client, probe, target, output, 'pthread', 'audit-optional-baseline')
    first_bank = bank_observation(original.wait_audit_idle(client, target, output, 'audit-after-baseline'))
    require(first_bank['fixed_reserved_bytes'] == baseline_bank['fixed_reserved_bytes'],
            'audit-signed-baseline-original-bank-fixed-owner')
    original_policy = read_json(client.directory / 'random-policy.json')
    binding = policy_record(client.call('policy', '--kind', 'provider-binding', 'get', '--id', 'random-installed'),
        'random-installed', 'provider-binding', read_json(client.directory / 'random-binding.json'))
    previous = policy_record(client.call('policy', 'get', '--id', 'random-allow'),
        'random-allow', 'policy', original_policy)
    selected = required_random_policy(original_policy)
    path = client.directory / 'random-required-policy.json'
    write_json(path, selected)
    update = client.call('policy', 'apply', '--id', 'random-allow', '--file', path,
        '--operation-id', 'require-random-audit', '--expected-generation', previous['revision'])
    current = policy_record(update, 'random-allow', 'policy', selected)
    require(integer(current['revision']) > integer(previous['revision'])
        and update['data']['receipt']['generation'] == current['revision'], 'audit-signed-known-stricter-policy')
    authority = {'binding': binding, 'policy': current}
    target = deploy(client, source / 'deployment.json', target['publication'],
                    generation=str(target['generation']), grants=grants)
    before_required = bank_observation(original.wait_audit_idle(client, target, output, 'audit-before-required'))
    revision = original.selected_revision(client, target)
    try:
        second = timed.invoke_timed(client, probe, target, output, 'timed-sleep', 'audit-required-random')
    except BaseException:
        try:
            retain_required_failure(client, target, output)
        except BaseException:
            pass
        raise
    providers = [row for row in node.startup_record['providers'] if row['capability'] == RANDOM]
    require(len(providers) == 1, 'audit-signed-one-actual-random-provider')
    pair = critical_pair(pair_pages(client, output, 'audit-required-random'),
                         'audit-required-random', revision, providers[0], authority)
    after_required = bank_observation(original.wait_audit_idle(client, target, output, 'audit-after-required'))
    require(after_required['fixed_reserved_bytes'] == before_required['fixed_reserved_bytes'],
            'audit-signed-required-call-and-query-original-bank-fixed-owner')
    third = original.invoke(client, probe, target, output, 'pthread', 'audit-fresh-after-required')
    after_fresh = bank_observation(original.wait_audit_idle(client, target, output, 'audit-after-fresh'))
    require(after_fresh['fixed_reserved_bytes'] == before_required['fixed_reserved_bytes'],
            'audit-signed-fresh-original-bank-fixed-owner')
    return target, {'outcomes': [first, second, third], 'requiredPolicy': selected,
        'requiredPolicyUpdate': update, 'requiredAuthority': authority, 'requiredPair': pair, 'originalBank': baseline_bank,
        'afterBaselineBank': first_bank, 'beforeRequiredBank': before_required,
        'afterRequiredBank': after_required, 'afterFreshBank': after_fresh,
        'originalProviderAndPhysicalRetirementAssertionsPreserved': True,
        'whole736Or745Qualified': False, 'waitForPollPendingClaimed': False}


def runtime(artifact, native, output):
    output = fresh(output)
    before = {name: file_identity(path) for name, path in native.items()}
    commands = Commands(ROOT, fresh(output / 'commands'), build_environment(output),
                        deadline_seconds=300, command_seconds=60)
    record = {'schemaVersion': 'latent.audit.signed-runtime-node.v1', 'status': 'incomplete',
              'native': before, 'component': file_identity(artifact / 'component.wasm', 4 * 1024**2)}
    stage = 'sign-the-exact-captured-component'
    try:
        signed = output / 'signed'
        commands.run(stage, native['capsule_authoring'], 'demo-sign', signed, artifact)
        releases = read_json(signed / 'release-set.json')['releases']
        require(len(releases) == 1 and releases[0]['componentDigest'] == record['component']['sha256'],
                'audit-signed-one-original-component-signature')
        with owned_cancellation() as cancellation, tempfile.TemporaryDirectory(prefix='lsf-audit-signed-') as temporary, \
                original.owned_cleanup(record) as cleanup:
            work = Path(temporary)
            for name in ('client', 'node', 'peer'):
                (work / name).mkdir(mode=0o700)
            client = RecordingClient(native['latent'], work / 'client', cancellation,
                min(commands.deadline, time.monotonic() + 240), evidence=output / 'controls')
            peer, port = start_provider(client, work / 'peer', maximum_seconds=240)
            cleanup.callback(peer.close)
            config, settings = configure_base(work / 'node', signed, port, language='c')
            timed.configure(settings, read_json(artifact / 'capsule.json'))
            config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
            record['configuration'] = settings
            stage = 'actual-current-audit-node'
            node = connect(client, native['latentd'], work / 'node', config, 'examples', 0)
            cleanup.callback(node.close)
            record['startup'] = node.startup_record
            probe = Probe(node, before['latentd'])
            source = signed / SERVICE
            published = client.call('release', 'publish-package', source / 'package',
                '--evidence', source / 'evidence/index.json', '--operation-id', 'audit-captured-publish',
                '--expected-generation', '0')
            require(published['outcomeKnown'] is True and published['data']['release']['digest'] == record['component']['sha256'],
                    'audit-signed-captured-component-admission')
            target = deploy(client, source / 'deployment.json', published['data']['operation']['publication']['id'])
            stage = 'three-signed-original-audit-controls'
            target, record['programme'] = programme(client, node, probe, source, target, output)
            delete_all(client, [target['name']])
            record['afterDeletes'] = sample(client, probe, 'audit-after-deletes', 0)
            stop(client, node)
            record['nodeShutdown'] = stopped_record(node)
            record['peerShutdown'] = stop_observation_peer(peer)
            cancellation.check()
        require(before == {name: file_identity(path) for name, path in native.items()}
                and client.calls <= 384 and time.monotonic() < commands.deadline, 'audit-signed-final-host-and-deadline')
        record.update(status='passed', cliCalls=client.calls, commands=commands.records)
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', failedStage=stage, commands=commands.records)
        if hasattr(error, 'startup_failure'):
            record['startupFailure'] = error.startup_failure
        write_json(output / 'FAILED.json', record)
        raise


def qualify(output, revision):
    require(sys.platform == 'linux' and re.fullmatch('[0-9a-f]{40}', revision), 'audit-signed-real-linux-source')
    output = fresh(output)
    record = {'schemaVersion': 'latent.audit.signed-runtime.v1', 'status': 'incomplete',
        'consumerSource': revision, 'nativeRebuilt': False, 'guestSourceRecompiled': False,
        'historical193ProgrammeReplayed': False, 'whole736Or745Qualified': False}
    stage, primary = 'bind-current-consumer-source-and-recipe', False
    try:
        require(subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, timeout=30)
                .decode().strip() == revision, 'audit-signed-current-consumer-revision')
        before = inputs()
        record['consumerGitSource'] = git_source_identity(revision)
        record['materials'] = before
        stage = 'authenticate-two-original-audit-hosts'
        record['auditHosts'] = hosts.prepare(output / 'audit-hosts')
        stage = 'authenticate-three-immutable-193-helpers'
        record['helpers193'] = hosts.prepare_historical_helpers(output / 'helpers193')
        stage = 'authenticate-original-captured-c36-component'
        record['capturedGuest'] = guest.prepare(output / 'captured-guest')
        native = hosts.native_products(output / 'audit-hosts') | {
            name: output / 'helpers193/native' / name for name in hosts.HELPERS}
        stage = 'actual-three-signed-retirement-controls'
        record['node'] = runtime(output / 'captured-guest/build', native, output / 'node')
        require(inputs() == before, 'audit-signed-consumer-recipe-drift')
        hosts.verify_prepared(output / 'audit-hosts')
        hosts.verify_historical_helpers(output / 'helpers193')
        guest.verify_prepared(output / 'captured-guest')
        record['status'] = 'passed'
        write_json(output / 'qualification.json', record)
        return record
    except BaseException:
        primary = True
        record.update(status='failed', failedStage=stage)
        raise
    finally:
        try:
            write_json(output / 'result.json', record)
            inventory(output, maximum_files=512, maximum_bytes=400 * 1024**2,
                      deadline=time.monotonic() + 60)
        except BaseException:
            if not primary:
                raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--source-commit', required=True)
    args = parser.parse_args()
    qualify(args.output, args.source_commit)

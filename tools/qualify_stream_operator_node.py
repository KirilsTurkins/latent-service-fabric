"""Actual frozen operator and native277 configuration refusals, without startup.

No Cargo, kernel, guest, compiler or node build; no serve/listener/provider call.
The two completed binary origins and this consumer head remain distinct.
"""
from pathlib import Path
import argparse
import copy
import hashlib
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
import time

if __package__ in {None, ''}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import audit_memory_native_products as native
from tools.stream_operator_frontend_products import READER as FRONTEND
from tools.dev_workflow import paths, process
from tools.dev_workflow.common import DevError, decode, encode, require
from tools.phase3_resource_identity import file_identity
from tools.qualify_audit_node_startup import configuration
from tools.rust_capsule_project import ROOT, fresh, write_json

SOURCE = native.SOURCE
GATE_FILES = ('apps/latentd/Cargo.toml', 'apps/latentd/src/command.rs',
              'apps/latentd/src/config/derive.rs', 'apps/latentd/src/config/providers.rs',
              'apps/latentd/src/config/providers/streams.rs', 'tools/qualify_audit_node_startup.py')
RECIPE = ('.github/workflows/stream-operator-node-check.yml',
          'tools/qualify_stream_operator_node.py', 'tools/stream_operator_frontend_products.py',
          'tools/audit_memory_native_products.py', 'tools/tests/test_stream_operator_node.py',
          'tools/tests/fixtures/stream-operator-frontend-380-build.json',
          'tools/qualify_audit_node_startup.py', 'tools/dev_workflow/process.py',
          'tools/dev_workflow/paths.py', 'tools/dev_workflow/common.py',
          'tools/build_process.py', 'tools/build_process_linux.py', 'tools/build_process_signals.py')


def source_contract():
    # Whole immutable source identities, not a claim of a new native build.
    frozen = {}
    for name in GATE_FILES:
        raw = subprocess.check_output(['git', 'show', SOURCE + ':' + name], cwd=ROOT, timeout=15)
        require(len(raw) <= 1024**2, 'stream-operator-frozen-source-byte-bound')
        import hashlib
        frozen[name] = {'sha256': 'sha256:' + hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}
        if name == 'tools/qualify_audit_node_startup.py':
            require((ROOT / name).read_bytes() == raw, 'stream-operator-original-complete-base-fixture')
    return {'compiledNodeSource': SOURCE, 'files': frozen,
            'deriveChecksDevelopmentStreamFeature': True,
            'publicFailure': {'exitCode': 2, 'stage': 'configuration', 'code': 'invalid-argument'},
            'privateFieldDiagnosticDisclosed': False,
            'attribution': 'frozen-source gate plus successful complete baseline and isolated stream addition'}


def installation():
    return {'installation': {
        'identity': {'id': 'streams', 'tenant': 'tests', 'service': 'stream-host', 'epoch': 1},
        'configuration': {'formatVersion': 1, 'profile': 'lsf-outbound-streams-v1',
            'destinations': [{'endpoint': {'host': '127.0.0.1', 'port': 32123, 'transport': 'tcp'},
                'addresses': {'networks': ['127.0.0.1/32'], 'specialAddresses': ['127.0.0.1']},
                'resolution': {'kind': 'static', 'addresses': ['127.0.0.1']}}],
            'limits': {'maximumTransferBytes': 65536, 'idleTimeoutMillis': 1000, 'absoluteTimeoutMillis': 5000}}},
        'bindings': [{'name': 'stream-binding', 'tenant': 'tests', 'consumerService': 'guest-stream',
            'providerService': 'stream-host', 'contract': 'latent:network/streams@0.1.0',
            'providerBinding': 'stream-installed'}]}


def expected_configuration(settings, record):
    value = copy.deepcopy(settings)
    value['providers']['outboundStreams'] = copy.deepcopy(record['installation'])
    value['providers']['bindings'].extend(copy.deepcopy(record['bindings']))
    return value


def operator_refusal(result, code):
    require(result.returncode == 1 and result.stdout == b'', 'stream-operator-refusal-exit-and-channel')
    value = decode(result.stderr, 65536)
    require(value == {'schemaVersion': 'latent.outbound-stream.operator.result.v1', 'command': 'prepare',
                     'status': 'failed', 'code': code, 'uncertain': False},
            'stream-operator-exact-redacted-refusal')
    return {'exitCode': 1, 'code': code, 'uncertain': False}


def clean_output(result, token, work):
    require(token.encode() not in result.stdout + result.stderr
            and str(work).encode() not in result.stdout + result.stderr,
            'stream-operator-private-input-or-path-disclosed')


def qualify(native_input, frontend_input, output):
    require(sys.platform == 'linux', 'stream-operator-actual-node-linux-required')
    output = fresh(output)
    record = {'schemaVersion': 'latent.stream-operator.actual-node-check.v1', 'status': 'incomplete',
        'consumerSourceRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        'configurationChecksOnly': True, 'nodeStarted': False, 'providerInstalled': False,
        'providerReadiness': 'not-observed', 'executionPermission': False,
        'socketInvocationAttempted': False, 'nativeRebuilt': False, 'guestCompiled': False,
        'wholeIssue739Acceptance': False, 'outcomes': []}
    started = time.monotonic()
    deadline = started + 240
    stage = 'verify-inputs'
    try:
        if native_input is None:
            native_input = output / 'native-origin'
            native.prepare(native_input)
        if frontend_input is None:
            frontend_input = output / 'frontend-origin'
            record['frontendAcquisition'] = FRONTEND.prepare(frontend_input)['retrieval']
        record['nodeOrigin'] = native.verify_prepared(native_input)
        record['frontendOrigin'] = FRONTEND.verify_prepared(frontend_input)
        record['productAcquisitionAndVerificationMillis'] = int((time.monotonic() - started) * 1000)
        record['sourceContract'] = source_contract()
        record['consumerRecipe'] = {name: file_identity(ROOT / name) for name in RECIPE}
        node = native.native_products(native_input)['latentd']
        frontend = FRONTEND.frontend(frontend_input)
        before_node, before_frontend = file_identity(node, 256 * 1024**2), file_identity(frontend, 64 * 1024**2)
        with tempfile.TemporaryDirectory(prefix='lsf-actual-stream-config-') as temporary:
            work = Path(temporary).absolute()
            work.chmod(0o700)
            base, selected, candidate = (work / name for name in ('base.json', 'installation.json', 'candidate.json'))
            settings, selection = configuration(4096, True), installation()
            token = secrets.token_hex(32)
            settings['credentials'][0]['token'] = token
            paths.write_new(base, encode(settings))
            paths.write_new(selected, encode(selection))
            original_base, original_record = base.read_bytes(), selected.read_bytes()

            def command(arguments):
                remaining = deadline - time.monotonic()
                require(remaining > 0, 'stream-operator-overall-deadline')
                result = process.run(list(map(str, arguments)), work, timeout=min(45, remaining), maximum=65536)
                clean_output(result, token, work)
                return result

            stage = 'complete-original-baseline'
            result = command([node, 'check-config', '--config', base])
            require(result.returncode == 0 and not result.stderr, 'stream-operator-valid-baseline-must-pass')
            baseline = decode(result.stdout, 65536)
            require(baseline.get('schemaVersion') == 'latent.standalone.config-check.v1'
                    and baseline.get('protectedCredentialFile') is True,
                    'stream-operator-complete-protected-baseline-report')
            record['outcomes'].append({'case': stage, 'exitCode': 0,
                'schemaVersion': baseline['schemaVersion'], 'protectedCredentialFile': True})

            def prepare(output_path, *, base_path=base):
                return command([frontend, 'stream-operator', 'prepare', '--node', node,
                    '--base-config', base_path, '--installation-record', selected,
                    '--output', output_path, '--development-profile'])

            stage = 'actual-packaged-compiled-profile-refusal'
            result = prepare(candidate)
            observed = operator_refusal(result, 'stream-operator-node-check-rejected-prepared-file-retained')
            prepared = candidate.read_bytes()
            require(decode(prepared, 65536) == expected_configuration(settings, selection)
                    and candidate.stat().st_mode & 0o777 == 0o600,
                    'stream-operator-real-refusal-preserves-exact-private-candidate')
            record['outcomes'].append({'case': stage, **observed, 'privateCandidateRetained': True,
                                      'existingProviderAndCredentialsPreserved': True})

            stage = 'direct-same-candidate-public-node-refusal'
            result = command([node, 'check-config', '--config', candidate])
            require(result.returncode == 2 and result.stdout == b''
                    and result.stderr == b'latentd: configuration: invalid-argument\n',
                    'stream-operator-source-bound-actual-node-profile-refusal')
            record['outcomes'].append({'case': stage, 'exitCode': 2,
                'publicFailure': {'stage': 'configuration', 'code': 'invalid-argument'},
                'privateFieldDiagnosticDisclosed': False})

            stage = 'existing-private-candidate-no-overwrite'
            observed = operator_refusal(prepare(candidate), 'stream-operator-output-not-new-or-unavailable')
            require(candidate.read_bytes() == prepared, 'stream-operator-existing-candidate-changed')
            record['outcomes'].append({'case': stage, **observed, 'privateCandidateUnchanged': True})

            for stage, code in (('missing-base', 'stream-operator-file-unavailable-or-unsafe'),
                                ('hardlinked-base', 'single-link-regular-file-required'),
                                ('group-readable-base', 'stream-operator-file-protection'),
                                ('malformed-installation', 'invalid-json')):
                target = work / (stage + '.json')
                alias = work / 'linked-base.json'
                if stage == 'hardlinked-base':
                    os.link(base, alias)
                if stage == 'group-readable-base':
                    base.chmod(0o640)
                if stage == 'malformed-installation':
                    selected.write_bytes(b'{')
                try:
                    result = prepare(target, base_path=work / 'absent.json' if stage == 'missing-base' else base)
                    observed = operator_refusal(result, code)
                    require(not target.exists(), 'stream-operator-unsafe-input-created-candidate')
                    record['outcomes'].append({'case': stage, **observed, 'outputCreated': False})
                finally:
                    if stage == 'hardlinked-base':
                        alias.unlink()
                    if stage == 'group-readable-base':
                        base.chmod(0o600)
                    if stage == 'malformed-installation':
                        selected.write_bytes(original_record)
            require(base.read_bytes() == original_base and selected.read_bytes() == original_record
                    and candidate.read_bytes() == prepared and not (work / 'data').exists(),
                    'stream-operator-input-preservation-or-unexpected-node-storage')
            record['privateCandidatePreservedUntilOwnerTeardown'] = True
            record['privateInputsPublished'] = False
            record['nodeStorageCreated'] = False
        require(file_identity(node, 256 * 1024**2) == before_node
                and file_identity(frontend, 64 * 1024**2) == before_frontend,
                'stream-operator-original-products-changed')
        record['originalProductBytesUnchanged'] = True
        record['status'] = 'passed'
        return record
    except BaseException as error:
        record['status'] = 'failed'
        record['failedStage'] = stage
        record['failureCode'] = error.code if isinstance(error, DevError) else 'bounded-programme-failed'
        raise
    finally:
        record['elapsedMillis'] = int((time.monotonic() - started) * 1000)
        write_json(output / 'result.json', record)


INSPECT_CASES = (
    'ordinary-signed-publication-and-deployment', 'unfiltered-ordinary-clock',
    'provider-filter-excludes-clock', 'contract-filter-excludes-clock',
    'packaged-unavailable-stream-inspection', 'different-publication-refused',
    'authenticated-tenant-admin-node-scope-refused', 'unchanged-inputs-and-clean-shutdown')
CLOCK = 'latent:clock/monotonic@0.1.0'
CLOCK_PROFILE = 'activation-monotonic-v1'
FIXTURE_CONTROL = 'supply_chain::tests::support::operator_fixture::export_publication_workflow_fixture'
INSPECT_RECIPE = (*RECIPE, 'tools/build_dev_frontend.py', 'tools/dev_frontend_linux.py',
    'tools/dev_distribution.py', 'tools/dev-frontend-linux.lock',
    'tools/phase2_operator_scenario.py', 'tools/dev_workflow/client.py',
    'tools/dev_workflow/policy_operations.py', 'tools/guest_runtime_profiles.py',
    'tools/outbound_stream_operator.py', 'tools/dev_workflow/cli.py', 'tools/dev_workflow/journal.py',
    'examples/echo-contract/capsule.json', 'examples/echo-contract/deployment.json',
    'contracts/dev/composition-support-v1.json', 'contracts/http/browser-response-ownership-v1.json',
    'LICENSE', 'NOTICE')


def inspection_view(value, publication, *, clock=False, node_usage=True):
    """Validate real public data; unavailable stream counters are never invented."""
    require(isinstance(value, dict) and value.get('executionPermission') is False
            and value.get('state') == 'compiled-plan' and value.get('nextPageToken') is None,
            'stream-inspect-public-view')
    revision = value.get('revision')
    require(isinstance(revision, dict) and revision.get('deploymentId') == 'blue'
            and revision.get('publicationId') == publication,
            'stream-inspect-exact-publication')
    entries = value.get('capabilities')
    require(isinstance(entries, list) and len(entries) == int(clock), 'stream-inspect-exact-page')
    if clock:
        entry = entries[0]
        require(entry.get('id') == CLOCK and entry.get('contract') == CLOCK
                and entry.get('provider') == CLOCK_PROFILE
                and entry.get('inspection', {}).get('providerProfile') == CLOCK_PROFILE,
                'stream-inspect-ordinary-clock-control')
    usage = value.get('nodeUsage')
    require((isinstance(usage, dict) and usage.get('scope') == 'node') if node_usage else usage is None,
            'stream-inspect-node-scope')
    if node_usage:
        counters = usage.get('counters')
        require(isinstance(counters, dict) and not any(name.startswith('stream_') for name in counters),
                'stream-inspect-no-fabricated-stream-usage')
    return {'revision': revision, 'state': value['state'], 'capabilities': entries,
            'executionPermission': False, 'streamUsageObserved': False}


def inspection_frontend(result, *, refusal=None):
    if refusal is not None:
        require(result.returncode == 1 and result.stdout == b'', 'stream-inspect-refusal-channel')
        value = decode(result.stderr, 65536)
        require(value == {'schemaVersion': 'latent.outbound-stream.operator.result.v1',
                'command': 'inspect', 'status': 'failed', 'code': refusal, 'uncertain': False},
                'stream-inspect-exact-redacted-refusal')
        return {'exitCode': 1, 'code': refusal, 'uncertain': False}
    require(result.returncode == 0 and result.stderr == b'', 'stream-inspect-success-channel')
    value = decode(result.stdout, 65536)
    require(isinstance(value, dict) and set(value) == {'schemaVersion', 'command', 'status', 'result'}
            and value['schemaVersion'] == 'latent.outbound-stream.operator.result.v1'
            and value['command'] == 'inspect' and value['status'] == 'completed',
            'stream-inspect-front-end-envelope')
    return value['result']


def inspect_configuration(directory, fixture):
    from tools.phase2_operator_scenario import configure_node, TOKEN
    from tools.phase2_operator_process import read_json
    path = configure_node(directory, fixture, 'tests')
    value = read_json(path)
    value.update(budgetProfile={'mode': 'phase3'}, capabilityPolicies={'formatVersion': 1},
        providers={'formatVersion': 1,
            'clockMonotonic': {'identity': {'id': 'clock', 'tenant': 'tests',
                'service': 'clock-host', 'epoch': 1}},
            'bindings': [{'name': 'clock-binding', 'tenant': 'tests', 'consumerService': 'packaging',
                'providerService': 'clock-host', 'contract': CLOCK, 'providerBinding': 'inspect-clock'}]})
    # Authenticated administrator, deliberately WITHOUT the node-operator claim.
    value['credentials'].append({'token': TOKEN + '-ADMIN', 'subject': 'tenant-admin',
        'tenant': 'tests', 'role': 'admin'})
    path.unlink()
    from tools.phase2_operator_process import write_json as private_json
    private_json(path, value)
    return path


def inspect_specification(publication):
    from tools.phase2_operator_scenario import NODE_ID
    from tools.outbound_stream_operator import PROFILE, CAPABILITY
    # A planned descriptor is information only. No installed stream or grant is claimed.
    return {'node': NODE_ID, 'tenant': 'tests', 'provider': {'id': 'unavailable-stream',
        'tenant': 'tests', 'service': 'unavailable-stream-host', 'capability': CAPABILITY,
        'profile': PROFILE, 'configurationDigest': 'sha256:' + 'a' * 64,
        'configurationEpoch': '1'}, 'consumer': 'packaging', 'publication': publication,
        'principal': {'kind': 'administrator', 'subject': 'workflow-operator'},
        'destination': {'host': '127.0.0.1', 'port': 32123, 'transport': 'tcp'},
        'bindingId': 'never-installed-stream', 'policyId': 'never-created-stream'}


def inspect_live(cli, node_binary, frontend, fixture, output, deadline, cancellation):
    from tools.phase2_operator_process import Client, Process, read_json, stopped_record, write_json as private_json
    from tools.phase2_operator_scenario import stop, TOKEN, NODE_ID
    from tools.dev_workflow import policy_operations
    from tools.outbound_stream_operator import PROFILE, CAPABILITY

    class BoundedClient(Client):
        def call(self, *arguments, **keywords):
            require(self.calls < 48, 'stream-inspect-cli-count')
            value = super().call(*arguments, **keywords)
            require(len(encode(value)) <= 65536, 'stream-inspect-cli-result-bound')
            return value

    record = {'cases': [], 'status': 'incomplete', 'streamInstalled': False,
        'streamGrantCreated': False, 'guestInvoked': False, 'streamSocketDispatched': False,
        'providerReadiness': 'not-observed', 'executionPermission': False,
        'positiveLiveUsageQualified': False, 'rotationQualified': False,
        'quarantineQualified': False, 'wholeIssue739Acceptance': False}
    with tempfile.TemporaryDirectory(prefix='lsf-stream-inspect-') as temporary:
        work = Path(temporary).absolute()
        work.chmod(0o700)
        node_dir = work / 'node'
        node_dir.mkdir(mode=0o700)
        config = inspect_configuration(node_dir, fixture)
        config_before = config.read_bytes()
        client = BoundedClient(cli, work, cancellation, deadline)
        node = None
        primary = False
        try:
            node = Process([str(node_binary), 'serve', '--config', str(config)], node_dir,
                dict(client.environment, HOME=str(node_dir)), cancellation, maximum=262144)
            node.startup_record = node.line(min(deadline, time.monotonic() + 30))
            startup = encode(node.startup_record)
            require(TOKEN.encode() not in startup and str(work).encode() not in startup,
                    'stream-inspect-startup-private-input-disclosed')
            endpoint = node.startup_record.get('endpoint', '')
            require(re.fullmatch(r'127\.0\.0\.1:[0-9]{1,5}', endpoint), 'stream-inspect-loopback-node')
            client.config = work / 'operator-client.json'
            private_json(client.config, {'formatVersion': 1, 'defaultProfile': 'operator', 'profiles': [{
                'name': 'operator', 'endpoint': 'http://' + endpoint, 'tenant': 'tests',
                'token': TOKEN, 'connectTimeoutMillis': 2000, 'rpcTimeoutMillis': 15000}]})
            client.node = node
            readiness_deadline = min(deadline, time.monotonic() + 10)
            while True:
                ready = client.call('node', 'get', NODE_ID)['data']
                if ready['inventory']['health']['ready']:
                    break
                require(time.monotonic() < readiness_deadline, 'stream-inspect-node-readiness')
                cancellation.check()
                time.sleep(min(0.025, max(0, readiness_deadline - time.monotonic())))
            installed = node.startup_record.get('providers')
            require(isinstance(installed, list) and len(installed) == 1
                    and installed[0].get('capability') == CLOCK
                    and installed[0].get('profile') == CLOCK_PROFILE,
                    'stream-inspect-only-ordinary-clock-installed')
            record['nodeStartup'] = node.startup_record
            publications = {}
            for name in ('blue', 'green'):
                operation = 'inspect-publish-' + name
                result = client.call('release', 'publish-package', fixture / name / 'package',
                    '--evidence', fixture / name / 'evidence/index.json', '--operation-id', operation,
                    '--expected-generation', '0')
                release, accepted = result['data']['release'], result['data']['operation']
                publication = release['publication']
                require(result['outcomeKnown'] and publication['tenant'] == 'tests'
                        and re.fullmatch('publication:sha256:[0-9a-f]{64}', publication['id'])
                        and accepted['publication'] == publication,
                        'stream-inspect-real-admitted-publication')
                require(client.call('release', 'operation', operation)['data']['receipt'] == accepted,
                        'stream-inspect-publication-receipt')
                publications[name] = publication['id']
            require(publications['blue'] != publications['green'], 'stream-inspect-distinct-publications')
            binding = {'formatVersion': 1, 'tenant': 'tests', 'capability': CLOCK,
                'providerProfile': CLOCK_PROFILE, 'configurationDigest': installed[0]['configurationDigest'],
                'configurationEpoch': 1, 'restriction': {'operations': ['now-nanos']}}
            policy = {'formatVersion': 1, 'tenant': 'tests', 'rules': [{'id': 'clock-only',
                'effect': 'allow', 'principals': [{'kind': 'administrator', 'subject': 'workflow-operator'}],
                'services': ['packaging'], 'publications': [publications['blue']], 'capability': CLOCK,
                'operations': ['now-nanos'], 'resources': {'kind': 'clock'},
                'ceiling': {'operations': 1, 'inputBytes': 0, 'outputBytes': 8, 'wallTimeMillis': 5000}}]}
            policies = {}
            for kind, identity, document in (('provider-binding', 'inspect-clock', binding),
                                              ('policy', 'inspect-clock-policy', policy)):
                path = work / (kind + '.json')
                private_json(path, document)
                operation = 'inspect-create-' + kind
                result = client.call('policy', '--kind', kind, 'apply', '--id', identity,
                    '--file', path, '--operation-id', operation, '--expected-generation', '0')
                policy_operations.confirm({'id': operation, 'tenant': 'tests', 'intent': {
                    'policyId': identity, 'recordKind': kind, 'document': document,
                    'expectedGeneration': '0'}}, result)
                policies[(kind, identity)] = result['data']['policy']
            deployment = read_json(fixture / 'blue/deployment.json')
            deployment['spec']['publication'] = publications['blue']
            deployment['spec']['grants'] = [{'capability': CLOCK, 'policy': 'inspect-clock-policy'}]
            path = work / 'deployment.json'
            private_json(path, deployment)
            before = client.call('deployment', 'get', 'blue', '--operation-snapshot', codes=(0, 6))['data']
            require(before.get('deployment') is None, 'stream-inspect-new-deployment-only')
            result = client.call('deployment', 'apply', path, '--operation-id', 'inspect-deploy',
                '--expected-state-version', before['stateVersion'], '--expected-generation', '0')
            require(result['outcomeKnown'] and result['data'].get('auditAck') is not None
                    and result['data']['receipt']['publication']['id'] == publications['blue'],
                    'stream-inspect-deployment-admission')
            selected = client.call('deployment', 'get', 'blue')['data']['deployment']
            require(selected['publication']['id'] == publications['blue'], 'stream-inspect-selected-publication')
            record['cases'].append({'case': INSPECT_CASES[0], 'publications': publications,
                'deployment': selected, 'syntheticSignedTestEvidence': True})

            def listing(*filters, usage=True, codes=(0,)):
                return client.call('capability', 'list', '--deployment', 'blue', *filters,
                    *(('--include-node-usage',) if usage else ()), '--page-size', '1', codes=codes)

            original = inspection_view(listing()['data'], publications['blue'], clock=True)
            record['cases'].append({'case': INSPECT_CASES[1], 'view': original})
            for label, filters in ((INSPECT_CASES[2], ('--provider', PROFILE, '--contract-prefix', CLOCK)),
                    (INSPECT_CASES[3], ('--provider', CLOCK_PROFILE, '--contract-prefix', CAPABILITY))):
                record['cases'].append({'case': label,
                    'view': inspection_view(listing(*filters)['data'], publications['blue'])})

            frontend_calls = []
            def packaged(label, publication, credential, refusal=None):
                state_root = work / label
                state_root.mkdir(mode=0o700)
                spec = state_root / 'specification.json'
                private_json(spec, inspect_specification(publication))
                remaining = deadline - time.monotonic()
                require(remaining > 0 and len(frontend_calls) < 3, 'stream-inspect-frontend-bound')
                result = process.run([str(frontend), 'stream-operator', 'inspect', '--cli', str(cli),
                    '--client-config', str(credential), '--state-dir', str(state_root),
                    '--specification', str(spec), '--deployment', 'blue'], work,
                    timeout=min(45, remaining), maximum=65536, graceful=10, check=node.drain)
                clean_output(result, TOKEN, work)
                observed = inspection_frontend(result, refusal=refusal)
                require(not (state_root / 'operations.json').exists()
                        and not (state_root / 'stream-policy-receipts.json').exists(),
                        'stream-inspect-no-stream-policy-mutation')
                frontend_calls.append({'case': label, 'exitCode': result.returncode,
                    'stdout': {'bytes': len(result.stdout), 'sha256': 'sha256:' + hashlib.sha256(result.stdout).hexdigest()},
                    'stderr': {'bytes': len(result.stderr), 'sha256': 'sha256:' + hashlib.sha256(result.stderr).hexdigest()}})
                return observed

            value = packaged('exact-stream', publications['blue'], client.config)
            record['cases'].append({'case': INSPECT_CASES[4],
                'view': inspection_view(value, publications['blue'])})
            observed = packaged('different-publication', publications['green'], client.config,
                'stream-operator-inspection-publication-changed')
            record['cases'].append({'case': INSPECT_CASES[5], **observed})
            operator_config = client.config
            admin_config = work / 'admin-client.json'
            profile = read_json(operator_config)
            profile['profiles'][0]['token'] = TOKEN + '-ADMIN'
            private_json(admin_config, profile)
            client.config = admin_config
            try:
                inspection_view(listing(usage=False)['data'], publications['blue'], clock=True, node_usage=False)
                denial = listing(codes=(4,))
                require(denial.get('category') == 'platform-failure' and denial.get('requestDispatched') is True
                        and denial.get('outcomeKnown') is True
                        and denial.get('error', {}).get('code') == 'permission-denied',
                        'stream-inspect-authenticated-node-scope-denial')
                packaged_denial = packaged('tenant-admin', publications['blue'], admin_config,
                    'operator-request-rejected-last-deployment-retained')
            finally:
                client.config = operator_config
            record['cases'].append({'case': INSPECT_CASES[6], 'tenantReadSucceeded': True,
                'nodeUsageDenied': True, 'packaged': packaged_denial})
            require(client.call('deployment', 'get', 'blue')['data']['deployment'] == selected,
                    'stream-inspect-deployment-changed')
            for (kind, identity), expected in policies.items():
                require(client.call('policy', '--kind', kind, 'get', '--id', identity)['data']['policy'] == expected,
                        'stream-inspect-ordinary-policy-changed')
            require(config.read_bytes() == config_before, 'stream-inspect-node-configuration-changed')
            stop(client, node)
            record['shutdown'] = stopped_record(node)
            require(TOKEN.encode() not in bytes(node.buffers[0]) + bytes(node.buffers[1])
                    and str(work).encode() not in bytes(node.buffers[0]) + bytes(node.buffers[1]),
                    'stream-inspect-node-private-input-disclosed')
            record['cases'].append({'case': INSPECT_CASES[7], 'configurationAndPoliciesUnchanged': True,
                'nodeReapedCleanly': True})
            record.update(status='passed', cliProcesses=client.calls,
                packagedFrontendProcesses=frontend_calls, nestedInspectionCliProcesses=3)
            return record
        except BaseException:
            primary = True
            record['status'] = 'failed'
            raise
        finally:
            if node is not None:
                try:
                    node.close()
                except BaseException:
                    record['cleanupFailed'] = True
                    if not primary:
                        raise
            try:
                require(len(encode(record)) <= 65536, 'stream-inspect-receipt-bound')
                write_json(output / 'inspection.json', record)
            except BaseException:
                if not primary:
                    raise


def qualify_inspect(output, revision):
    """One current native/frontend build and one closed actual-node programme."""
    from tools import host_codec_wasmtime, result_owner_bytes
    from tools.build_observation import build_environment
    from tools.build_process_signals import owned_cancellation
    from tools.phase3_resource_identity import source_identity, inventory
    from tools.qualify_host_codec_native import Stages, exact_list, exact_result, materials
    from tools.rust_capsule_build import Commands
    from tools.dev_distribution import frontend_files
    require(sys.platform == 'linux' and re.fullmatch('[0-9a-f]{40}', revision),
            'stream-inspect-exact-linux-source')
    output = fresh(output)
    stage, stages, primary = 'source-inputs', None, False
    record = {'schemaVersion': 'latent.stream-operator.unavailable-inspection.v1', 'status': 'incomplete',
        'sourceRevision': revision, 'wholeIssue739Acceptance': False,
        'guestCompilerExecuted': False, 'signedFixtureIsSyntheticTestEvidence': True}
    def inputs():
        return {'native': source_identity(ROOT), 'materials': {**materials(ROOT),
            **{name: file_identity(ROOT / name) for name in INSPECT_RECIPE}}}
    try:
        host_codec_wasmtime.verify(ROOT)
        result_owner_bytes.verify(ROOT)
        before = inputs()
        write_json(output / 'source-inputs.json', before)
        environment = build_environment(output)
        target = Path(os.environ.get('CARGO_TARGET_DIR', ROOT / 'target')).resolve()
        environment.update(CARGO_TARGET_DIR=str(target), RUSTUP_TOOLCHAIN='1.97.1',
            CARGO_BUILD_JOBS='2', CARGO_INCREMENTAL='0', CARGO_PROFILE_DEV_DEBUG='0', CARGO_PROFILE_TEST_DEBUG='0',
            CARGO_PROFILE_DEV_DEBUG_ASSERTIONS='true', CARGO_PROFILE_TEST_DEBUG_ASSERTIONS='true',
            CARGO_PROFILE_DEV_OVERFLOW_CHECKS='true', CARGO_PROFILE_TEST_OVERFLOW_CHECKS='true')
        stages = Stages(Commands(ROOT, output, environment, deadline_seconds=1320, command_seconds=1200), output)
        stage = 'exact-source-revision'
        require(stages.run(stage, 'git', 'rev-parse', 'HEAD').decode().strip() == revision,
                'stream-inspect-source-revision')
        stage = 'clean-source-before'
        require(stages.run(stage, 'git', '-c', 'core.fsmonitor=false', 'diff', '--no-ext-diff',
                '--exit-code', 'HEAD', '--') == b'', 'stream-inspect-clean-source')
        stage = 'pinned-rust-version'
        require(stages.run(stage, 'rustc', '--version').decode().startswith('rustc 1.97.1 ('),
                'stream-inspect-pinned-rust')
        cargo = ('cargo', '--config', ROOT / '.cargo/managed-guest.toml')
        stage = 'build-cli-and-node-once'
        stages.run(stage, *cargo, 'build', '--locked', '-p', 'latent', '-p', 'latentd')
        stage = 'build-current-frozen-frontend-once'
        frontend_output = ROOT / 'target/stream-operator-inspect-frontend'
        require(not frontend_output.exists(), 'stream-inspect-new-frontend-output')
        stages.run(stage, sys.executable, '-B', ROOT / 'tools/build_dev_frontend.py', '--output', frontend_output)
        frontend_record = json.loads((frontend_output / 'build.json').read_bytes())
        require(frontend_record.get('sourceCommit') == revision and frontend_record.get('sourceDirty') is False
                and frontend_record.get('files') == frontend_files(frontend_output),
                'stream-inspect-frozen-frontend-source')
        frontend = frontend_output / 'dist/latent-dev/latent-dev'
        products = {'latent': target / 'debug/latent', 'latentd': target / 'debug/latentd', 'frontend': frontend}
        product_limits = {'latent': 128 * 1024**2, 'latentd': 256 * 1024**2, 'frontend': 64 * 1024**2}
        identities = {name: file_identity(path, product_limits[name]) for name, path in products.items()}
        fixture = output / 'signed-fixture'
        environment['LSF_OPERATOR_FIXTURE_ROOT'] = str(fixture)
        arguments = (*cargo, 'test', '--locked', '-p', 'latent-policy', '--lib', FIXTURE_CONTROL,
                     '--', '--exact', '--ignored')
        stage = 'signed-fixture-exact-list'
        exact_list(stages.run(stage, *arguments, '--list'), (FIXTURE_CONTROL,))
        stage = 'signed-fixture-export-once'
        exact_result(stages.run(stage, *arguments, '--test-threads=1'), (FIXTURE_CONTROL,))
        fixture_identity = inventory(fixture, maximum_files=128, maximum_bytes=16 * 1024**2,
                                     deadline=stages.commands.deadline)
        stage = 'actual-unavailable-provider-inspection'
        with owned_cancellation() as cancellation:
            observed = inspect_live(products['latent'], products['latentd'], frontend, fixture, output,
                min(stages.commands.deadline - 15, time.monotonic() + 180), cancellation)
        stage = 'clean-source-after'
        require(stages.run(stage, 'git', '-c', 'core.fsmonitor=false', 'diff', '--no-ext-diff',
                '--exit-code', 'HEAD', '--') == b'', 'stream-inspect-clean-source')
        require(tuple(row['case'] for row in observed['cases']) == INSPECT_CASES,
                'stream-inspect-exact-eight-cases')
        require(inputs() == before and fixture_identity == inventory(fixture, maximum_files=128,
                maximum_bytes=16 * 1024**2, deadline=stages.commands.deadline)
                and frontend_record['files'] == frontend_files(frontend_output)
                and identities == {name: file_identity(path, product_limits[name])
                    for name, path in products.items()}, 'stream-inspect-input-or-product-changed')
        require(time.monotonic() < stages.commands.deadline, 'stream-inspect-overall-deadline')
        record.update(status='passed', products=identities, frontendSource=frontend_record,
            fixture=fixture_identity, observation=observed, commands=stages.records)
        return record
    except BaseException:
        primary = True
        record.update(status='failed', failedStage=stage, commands=stages.records if stages else [])
        raise
    finally:
        try:
            require(len(encode(record)) <= 262144, 'stream-inspect-final-receipt-bound')
            write_json(output / 'inspect-result.json', record)
            inventory(output, maximum_files=256, maximum_bytes=34 * 1024**2,
                      deadline=time.monotonic() + 5)
        except BaseException:
            if not primary:
                raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-input', type=Path)
    parser.add_argument('--frontend-input', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--inspect', action='store_true')
    parser.add_argument('--source-commit')
    args = parser.parse_args()
    try:
        if args.inspect:
            require(args.native_input is None and args.frontend_input is None and args.source_commit is not None,
                    'stream-inspect-current-products-only')
            qualify_inspect(args.output, args.source_commit)
        else:
            require(args.source_commit is None, 'stream-inspect-source-only-new-mode')
            qualify(args.native_input, args.frontend_input, args.output)
        return 0
    except Exception:
        print('stream-operator-owned-configuration-check-failed', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Four actual TypeScript calls; admission and physical retirement remain authoritative."""
import json
from pathlib import Path
import tempfile
import time

from tools.build_process_signals import owned_cancellation
from tools.phase2_operator_process import read_json, require, stopped_record
from tools.phase2_operator_scenario import connect, stop
from tools.phase3_resource_identity import file_identity
from tools.phase3_resource_os import Probe
from tools.qualify_resource_tenants import signed_inputs, stop_observation_peer
from tools import resource_tenant_node as tenants
from tools.rust_capsule_node import RecordingClient, call, configure, delete_all, deploy, sample, selected_revision
from tools.rust_capsule_project import fresh, write_json
from tools.sdk_explicit_fallback_node import consumption, retirement, owned_cleanup
from tools.typescript_elimination_fixture import CASES, expected
from tools.sdk_provider_scenario import close_failed_provider, start_provider

LANGUAGES = ('typescript',)


def outcome(language, row, seed, alternate, reached):
    require(language == 'typescript' and row['processReaped'] is True
        and row['response']['outcomeKnown'] is row['response']['requestDispatched'] is True
        and row['response']['schemaVersion'] == 'latent.cli.result.v1'
        and row['response']['command'] == 'invoke', 'typescript-elimination-known-reaped-result')
    if alternate is None:
        require(row['exitCode'] == 4 and row['decoded'] is None
            and row['response']['category'] == 'platform-failure'
            and row['response']['error']['code'] == 'guest-trap'
            and row['response']['data']['terminalState'] == 'guest_trap', 'typescript-elimination-uncaught-terminal-trap')
        return {'category': 'guest-trap', 'preciseInstructionCauseProved': False}
    require(row['exitCode'] == 0 and row['response']['category'] == 'success'
        and row['response']['error'] is None and row['decoded'] == expected(seed, alternate, reached),
        'typescript-elimination-native-refusal-and-real-alternate-required')
    return {'category': 'explicit-application-fallback' if reached else 'unselected-root-edge',
        'seed': seed, 'alternate': alternate, 'nativeRefusalVerified': reached,
        'transparentClockCompatibility': False}


def run(language, artifact, signed, binaries, output, deadline, *, reached):
    require(language in LANGUAGES and type(reached) is bool, 'elimination-node-language')
    output = fresh(output)
    component = file_identity(artifact / 'component.wasm', 64 * 1024**2)
    capsule = read_json(artifact / 'capsule.json')
    imports = tenants.required_imports(capsule)
    require(imports == [], 'typescript-elimination-original-pure-imports')
    release = signed_inputs(signed, component['sha256'])
    record = {'schemaVersion': 'latent.typescript.explicit-elimination.node.v1', 'status': 'incomplete',
        'language': language, 'component': component, 'release': release, 'cases': [], 'rootEdgeSelected': reached,
        'clockGrantAdded': False, 'transparentClockCompatibility': False,
        'oldProgrammeReplayed': False, 'fullTicketQualification': False}
    stage = 'normal-node-setup'
    try:
        with tempfile.TemporaryDirectory(prefix='lsf-explicit-elimination-') as temporary, owned_cancellation() as cancellation:
            work = Path(temporary)
            for name in ('node', 'examples', 'peer'):
                (work / name).mkdir(mode=0o700)
            client = RecordingClient(binaries['latent'], work / 'examples', cancellation,
                min(deadline, time.monotonic() + 600), evidence=output / 'controls',
                invocation_timeout_millis=120000, control_timeout_millis=125000)
            peer, port = start_provider(client, work / 'peer', maximum_seconds=600)
            with owned_cleanup(lambda: peer.close() if 'peerShutdown' in record else close_failed_provider(peer), record):
                config, settings = configure(work / 'node', signed, port, language=language)
                tenants.configure(settings, capsule, language)
                config.write_bytes((json.dumps(settings, sort_keys=True, separators=(',', ':')) + '\n').encode())
                record['configurationIdentity'] = file_identity(config)
                stage = 'normal-node-startup'
                node = connect(client, binaries['latentd'], work / 'node', config, 'examples', 0)
                with owned_cleanup(node.close, record):
                    record['startup'] = node.startup_record
                    probe = Probe(node, file_identity(binaries['latentd'], 512 * 1024**2))
                    stage = 'normal-publication-and-explicit-runtime-grants'
                    source = signed / 'my-greeting'
                    published = client.call('release', 'publish-package', source / 'package',
                        '--evidence', source / 'evidence/index.json', '--operation-id', 'elimination-publish',
                        '--expected-generation', '0')
                    require(published['outcomeKnown'] is True
                        and published['data']['release']['digest'] == component['sha256'], 'elimination-original-publication')
                    publication = published['data']['operation']['publication']['id']
                    manifest = client.directory / 'deployment.json'
                    write_json(manifest, tenants.scoped_deployment(read_json(source / 'deployment.json'), 'examples'))
                    target = deploy(client, manifest, publication)
                    target = tenants.install_grants(client, node, manifest, publication, target, imports, language, 'examples')
                    require(target['grants'] == [],
                        'typescript-elimination-no-clock-grant')
                    record['publication'] = publication
                    for index, (mode, seed, alternate) in enumerate(CASES):
                        name = f'elimination-{language}-{index}'
                        stage = name
                        pin = selected_revision(client, target)
                        row = call(client, target, 'greeting', 'greet', [f'elimination:{mode}:{seed}'], name)
                        # The raw invocation and real owner observations survive any oracle refusal.
                        physical = retirement(client, probe, target, output, name, 1)
                        item = {'name': name, 'invocation': file_identity(client.evidence / (name + '.json')),
                            'retirement': physical, 'seed': seed, 'expectedAlternate': alternate}
                        record['cases'].append(item)
                        require(pin['releaseDigest'] == component['sha256']
                            and row['response']['data']['resolvedRevision'] == pin, 'elimination-exact-current-revision')
                        consumption(row['response']['data']['consumption'], target['budget'])
                        item['observation'] = outcome(language, row, seed, alternate, reached)
                        write_json(output / (name + '-case.json'), item)
                    delete_all(client, [target['name']])
                    file_identity_after_delete = output / 'after-delete.json'
                    write_json(file_identity_after_delete, sample(client, probe, 'after-elimination-delete', 0))
                    record['afterDelete'] = file_identity(file_identity_after_delete)
                    stop(client, node)
                    record['nodeShutdown'] = stopped_record(node)
                    client.node = None
                    record['peerShutdown'] = stop_observation_peer(peer)
                    require(client.calls <= 384 and record['nodeShutdown']['reaped'] is True
                        and record['nodeShutdown']['record']['clean'] is True, 'elimination-clean-reaped-bounded-node')
                    record['cliCalls'] = client.calls
            cancellation.check()
        require(len(record['cases']) == 4 and time.monotonic() < deadline, 'elimination-four-complete-original-budget-cases')
        record['status'] = 'passed'
        write_json(output / 'qualified.json', record)
        return record
    except BaseException as error:
        record.update(status='failed', stage=stage, errorCategory=type(error).__name__)
        try:
            write_json(output / 'FAILED.json', record)
        except BaseException:
            pass
        raise

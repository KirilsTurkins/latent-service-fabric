"""Focused controller/closure controls; actual signed Java execution is separate."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import java_http_phase_node as node
from tools import qualify_java_http_phases as campaign
from tools.phase2_operator_process import WorkflowError


class JavaHttpPhaseCampaign(unittest.TestCase):
    def test_connect_observations_stop_at_sixteen_without_replaying_or_claiming_a_witness(self):
        clock = [0.]
        selected = {'revisionId': 'revision:test'}
        process = Mock();process.owner.exited.side_effect = lambda: clock[0] >= 2.5
        peer = Mock();peer.origin.return_value = {'host': '127.0.0.1', 'port': 1234}
        peer.observation.return_value = {'requests': [], 'failure': None}
        peer.gates.return_value = [];peer.poll.side_effect = lambda _delay: clock.__setitem__(0, clock[0]+.02)
        backlog = SimpleNamespace(origin=peer.origin)
        target = {'name': 'route', 'budget': {'wallTimeLimitMillis': 5000}}
        row = {'processReaped': True, 'exitCode': 0, 'decoded': ['1:connect-timeout:false'],
            'response': {'outcomeKnown': True, 'data': {'resolvedRevision': selected,
                'consumption': {'outboundRequests': '1'}}}}
        with tempfile.TemporaryDirectory() as temporary:
            client = SimpleNamespace(deadline=1000, evidence=Path(temporary))
            with patch.object(node.time, 'monotonic', side_effect=lambda: clock[0]), \
                    patch.object(node, 'selected_revision', return_value=selected), \
                    patch.object(node, 'start_call', return_value=process) as start, \
                    patch.object(node, 'finish_call', return_value=row) as finish, \
                    patch.object(node, 'usage', return_value={
                        'counters': {'pool_connecting_connections': '0'}}) as usage:
                with self.assertRaisesRegex(WorkflowError, 'no-real-pending-witness'):
                    node.invoke(client, Mock(), target, peer, Mock(), [backlog]*3, 7, 'no-witness')
            self.assertEqual(usage.call_count, 16)
            start.assert_called_once();finish.assert_called_once();process.close.assert_called_once()
            self.assertTrue((Path(temporary)/'no-witness-result.json').is_file())

    def test_configuration_selects_only_phase_contract_and_retains_original_limits(self):
        from tools.java_http_fiber_node import configuration as original
        from tools.rust_capsule_project import read_json
        peer = SimpleNamespace(provider_destinations=lambda: [{
            'origin': {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234},
            'addresses': {'networks': ['127.0.0.1/32'], 'specialAddresses': ['127.0.0.1']},
            'resolution': {'kind': 'static', 'addresses': ['127.0.0.1']},
            'allowedRequestHeaders': ['accept', 'user-agent', 'x-conformance'], 'redirectDestinations': []}])
        backlog = SimpleNamespace(origin=lambda: {'scheme': 'http', 'host': '127.0.0.1', 'port': 2345})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);credential = root/'credential';credential.write_bytes(b'public fixture')
            (root/'old').mkdir();(root/'new').mkdir();(root/'releases').mkdir()
            (root/'releases/policy.json').write_text('{}')
            old = read_json(original(root/'old', root/'releases', peer, credential))
            new = read_json(node.configuration(root/'new', root/'releases', peer, credential, [backlog]))
            old_http = old['providers']['httpStreaming'];new_http = new['providers']['httpStreaming']
            new_http.pop('phaseTiming');self.assertEqual(new_http['configuration']['destinations'].pop()['origin'], backlog.origin())
            self.assertEqual(old_http, new_http)
            self.assertEqual(new['providers']['activationRuntime'], old['providers']['activationRuntime'])
            self.assertEqual(new['budgetProfile'], old['budgetProfile'])
            old_bindings = old['providers']['bindings'];new_bindings = new['providers']['bindings']
            for row in new_bindings:
                if row['contract'] == node.CAPABILITY: row['contract'] = 'latent:http/streaming@0.3.0'
            self.assertEqual(old_bindings, new_bindings)

    def test_grants_are_explicit_profile_bound_with_original_ceiling_and_no_legacy_authority(self):
        from tools.guest_runtime_profiles import profiles
        providers = [{'id': name, 'capability': capability, 'profile': profile,
            'configurationDigest': 'sha256:'+'1'*64}
            for name, (capability, profile, _operation, _kind) in profiles('java').items()]
        providers += [{'id': 'activation', 'capability': node.ACTIVATION, 'profile': 'owned-activation',
            'configurationDigest': 'sha256:'+'2'*64},
            {'id': 'http-standard', 'capability': node.CAPABILITY, 'profile': node.PROFILE,
             'configurationDigest': 'sha256:'+'3'*64}]
        peer = SimpleNamespace(startup_record={'providers': providers});recorded = []
        origins = [{'scheme': 'http', 'host': '127.0.0.1', 'port': 1234}]
        with patch.object(node, 'policy', side_effect=lambda *args: recorded.append(args)):
            runtime, authorized = node.grants(None, peer, 'publication:test', origins)
        self.assertEqual(authorized, runtime+[{'capability': node.CAPABILITY, 'policy': 'http-allow'}])
        http = next(row[-1] for row in recorded if row[1:3] == ('policy', 'http-allow'))
        rule = http['rules'][0]
        self.assertEqual(rule['resources']['origins'], origins)
        self.assertEqual(rule['ceiling'], {'operations': 64, 'inputBytes': 65536,
            'outputBytes': 262144, 'wallTimeMillis': 5000})
        self.assertFalse(any(row.get('capability') == 'latent:http/streaming@0.3.0' for row in authorized))
        providers[-1]['profile'] = 'legacy-or-unqualified'
        with patch.object(node, 'policy'), self.assertRaisesRegex(WorkflowError, 'http-provider-profile'):
            node.grants(None, peer, 'publication:test', origins)

    def test_every_exact_result_is_source_revision_owned_and_root_errors_cannot_be_phase_errors(self):
        selected = {'revisionId': 'revision:test'}
        for mode in range(11):
            row = {'processReaped': True, 'exitCode': 0, 'decoded': [node.expected(mode)],
                'response': {'outcomeKnown': True, 'category': 'success',
                    'data': {'resolvedRevision': selected, 'consumption': {'outboundRequests': '1'}}}}
            if mode in node.TERMINAL:
                code = node.TERMINAL[mode];row['exitCode'] = 4;row['decoded'] = None
                row['response'].update(category='platform-failure', error={'code': code})
                row['response']['data']['terminalState'] = code.replace('-', '_')
            node.validate_result(row, mode, selected)
            mutations = [lambda value: value.update(processReaped=False),
                lambda value: value['response'].update(outcomeKnown=False),
                lambda value: value['response']['data'].update(resolvedRevision={'revisionId': 'other'}),
                lambda value: value['response']['data']['consumption'].update(outboundRequests='2')]
            if mode in node.TERMINAL:
                mutations.append(lambda value: value.update(exitCode=0, decoded=['1:connect-timeout:false']))
            else:
                mutations.append(lambda value: value.update(decoded=['forged-or-wrong-uncertainty']))
            for mutate in mutations:
                changed = copy.deepcopy(row);mutate(changed)
                with self.subTest(mode=mode, mutation=mutate), self.assertRaises(WorkflowError):
                    node.validate_result(changed, mode, selected)

    def test_public_client_closure_preserves_transitive_edge_and_owned_resources(self):
        from tools.java_resource_artifacts import resource_selection, resource_metadata
        def row(name, edges):
            return {'id': name, 'role': 'application', 'format': 'file',
                'mount': 'dependencies/java/0000.jar', 'dependencies': edges,
                'original': {'digest': campaign.ORIGINAL_JAR, 'size': 1},
                'metadata': {'scope': 'selected-runtime', 'coordinates': name}}
        candidate = {'artifacts': [row(campaign.PRIMARY, [campaign.CHILD]),
            row(campaign.CHILD, []), row(campaign.COORDINATE, [])]}
        entry = {'path': 'fixture.txt', 'originalEntry': 'fixture.txt', 'selectedVersion': 0,
            'digest': 'sha256:'+'9'*64, 'size': 1}
        selection = resource_selection(campaign.COORDINATE, campaign.ORIGINAL_JAR, [entry], 25)
        owned = selection['entries'][0]['artifact'];request = candidate['artifacts'][2]
        request['metadata']['resourceSelection'] = selection;request['dependencies'] = [owned]
        candidate['artifacts'].append({'id': owned, 'role': 'resource', 'format': 'file',
            'mount': 'dependencies/java/resources/'+owned.split(':', 1)[1]+'.bin', 'dependencies': [],
            'original': {'digest': entry['digest'], 'size': 1},
            'metadata': resource_metadata(campaign.COORDINATE, campaign.ORIGINAL_JAR, entry, 25)})
        self.assertEqual(set(campaign.selected_clients(candidate)),
            {campaign.PRIMARY, campaign.CHILD, campaign.COORDINATE})
        changes = [lambda value: value['artifacts'][0].update(dependencies=[]),
            lambda value: value['artifacts'][2]['original'].update(digest='sha256:'+'0'*64),
            lambda value: value['artifacts'][2].update(dependencies=[]),
            lambda value: value['artifacts'][3]['metadata'].update(jar=campaign.PRIMARY),
            lambda value: value['artifacts'].append(row('unreviewed:extra:1', []))]
        for change in changes:
            value = copy.deepcopy(candidate);change(value)
            with self.assertRaises(WorkflowError): campaign.selected_clients(value)

    def test_full_native_and_auxiliary_source_fence_rejects_extra_wit_before_build(self):
        from tools import wait_runtime_native_products as native
        from tools.java_replay_materials import git_source_identity
        record = {'source': git_source_identity(native.SOURCE), 'materials': native.READER._git_materials()}
        with patch.object(campaign, 'read_json', return_value=record):
            self.assertTrue(campaign.native_source(Path('prepared'))['equalToCompiledProducer'])
            original = campaign.inventory
            def changed(path, **kwargs):
                value = original(path, **kwargs)
                if path == campaign.ROOT/'wit':
                    value['files'].append({'path': 'unqualified/package.wit',
                        'sha256': 'sha256:'+'0'*64, 'bytes': 1})
                return value
            with patch.object(campaign, 'source_identity', return_value=record['source']), \
                    patch.object(campaign, 'inventory', side_effect=changed), self.assertRaisesRegex(
                        WorkflowError, 'auxiliary-input-drift'):
                campaign.native_source(Path('prepared'))
        original_error = WorkflowError('source-refused-before-build')
        with patch.object(campaign, 'verify_prepared'), patch.object(campaign, 'native_source',
                side_effect=original_error), patch.object(campaign, 'execute') as execute:
            with self.assertRaises(WorkflowError) as caught:
                campaign.run(Path('output'), Path('prepared'), Path('sdk'))
            self.assertIs(caught.exception, original_error);execute.assert_not_called()

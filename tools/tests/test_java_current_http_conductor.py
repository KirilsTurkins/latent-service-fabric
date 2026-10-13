"""Explicit current collector selections retain the historical protocol boundary."""
import copy
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from tools import run_java_transaction_http_qualification as conductor
from tools.java_transaction_qualification import current_recipient, policies
from tools.phase2_operator_process import write_json
from tools.tests.test_java_transaction_provision import observation


class CurrentHttpConductor(unittest.TestCase):
    def test_host_inspection_retires_original_clock_interval_before_returning_profiles(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification import evidence, lifecycle
        value, operations, _ = observation()
        events = []
        client = SimpleNamespace()
        with patch.object(lifecycle, 'native', side_effect=lambda *_a, **_k:
                (events.append('inspect'), evidence.encoded(value))[1]), \
             patch.object(lifecycle, 'admission_lease_interval', side_effect=lambda actual:
                (self.assertIs(actual, client), events.append('lease'))):
            hosts = lifecycle.inspect(client, Path('native'), Path('configuration'), operations)
        self.assertEqual(hosts.value, value)
        self.assertEqual(events, ['inspect', 'lease'])
        with patch.object(lifecycle, 'native', return_value=evidence.encoded({})), \
             patch.object(lifecycle, 'admission_lease_interval') as lease:
            with self.assertRaises(ValueError):
                lifecycle.inspect(client, Path('native'), Path('configuration'), operations)
        lease.assert_not_called()

    def test_offline_migration_requires_actual_wide_value_commit_and_effect_before_snapshot(self):
        from unittest.mock import Mock, patch
        from tools.java_transaction_qualification import offline_campaign
        publication = 'publication:sha256:' + 'a' * 64
        runner = offline_campaign.OfflineCampaign.__new__(offline_campaign.OfflineCampaign)
        runner.native = SimpleNamespace(calls=12)
        runner.client = SimpleNamespace(evidence=SimpleNamespace(passed=Mock()))
        sequence = Mock()
        runner.schema = Mock(return_value=({}, {}, {}))
        runner.restore = Mock()
        aggregate = {'key-version': {'none': None}}
        result = {'disposition': 'committed', 'effect-ids': ['b' * 64]}
        runner.campaign = SimpleNamespace(query=Mock(return_value=({}, aggregate)),
            socket=Mock(return_value={}), result=Mock(return_value=result),
            publications={'put-once-compatible-v2': publication},
            wait_effect=Mock(return_value={'retired': True}), peer_record=Mock(return_value={}))
        sequence.attach_mock(runner.campaign.wait_effect, 'effect')
        sequence.attach_mock(runner.schema, 'schema')
        with patch.object(offline_campaign.http, 'aggregate', return_value={'count': str(2**32 + 3)}), \
             patch.object(offline_campaign.lifecycle, 'lookup', return_value={}), \
             patch.object(offline_campaign, 'rpc_result') as inspected:
            sequence.attach_mock(inspected, 'inspection')
            observed = runner.execute()
        self.assertEqual([call[0] for call in sequence.mock_calls], ['effect', 'inspection', 'schema'])
        runner.campaign.query.assert_called_once_with(4)
        call = runner.campaign.socket.call_args
        self.assertEqual(call.args, ('command',))
        self.assertEqual(call.kwargs['original_key'], 'java-before-schema-wide-value')
        self.assertEqual(call.kwargs['condition'], '"absent"')
        self.assertEqual(call.kwargs['body'], offline_campaign.command_input(2**32 - 1))
        runner.campaign.wait_effect.assert_called_once_with(publication, call.kwargs['original_key'], result)
        inspected.assert_called_once_with({}, result, publication, call.kwargs['original_key'])
        runner.schema.assert_called_once_with(2**32 + 3)
        self.assertEqual(observed['nativeActions'], 12)
        runner.schema.reset_mock()
        runner.restore.reset_mock()
        with patch.object(offline_campaign.http, 'aggregate', return_value={'count': '4'}):
            with self.assertRaisesRegex(ValueError, 'actual-wide-java-value-before-schema'):
                runner.execute()
        runner.schema.assert_not_called()
        runner.restore.assert_not_called()

    def test_restore_checks_native_activation_retirement_before_starting_runtime(self):
        from unittest.mock import Mock, patch
        from tools.java_transaction_qualification import offline_campaign
        view = list(b'NV\x02' + bytes([19]) * 32
                    + b''.join(value.to_bytes(8, 'little') for value in (1, 2, 3, 4)))
        restored_view = view[:59] + list((5).to_bytes(8, 'little'))
        file = {'root': '/private/original-snapshots', 'name': 'restore-checkpoint-v2.snapshot'}
        snapshot = {'snapshotDigest': 'sha256:' + 'a' * 64, 'manifestDigest': 'sha256:' + 'b' * 64}
        window, review = 'sha256:' + 'c' * 64, 'sha256:' + 'd' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            configuration = root / 'original-node.json'
            settings = {'dataDirectory': str(root), 'state': {'formatVersion': 2,
                'checkpointRoot': str(root / 'checkpoint'), 'createIfMissing': False, 'operations': []}}
            write_json(configuration, settings)
            campaign = SimpleNamespace(query=lambda _: (None, object()),
                result=lambda _: {'disposition': 'committed'}, socket=lambda *_a, **_k: {},
                wait_effect=lambda *_a: None, full_path=configuration)
            runner = offline_campaign.OfflineCampaign.__new__(offline_campaign.OfflineCampaign)
            runner.campaign, runner.directory, runner.configuration = campaign, root, configuration
            runner.current_v2, runner.migration_operation = True, 'java-schema-v1-to-v2'
            runner.client = SimpleNamespace(evidence=SimpleNamespace(record=lambda *_a: None))
            runner.node = SimpleNamespace(current_activation=object(), start=Mock())
            runner.publication = 'publication:sha256:' + 'e' * 64
            runner.recipient = lambda _: {'unchanged': True}
            runner.quiesce = lambda *_a: None
            runner.refresh_authority = lambda _: None
            runner.inspect = lambda: {'view': restored_view}
            responses = iter([
                {'snapshot': snapshot, 'windowDigest': window},
                {**snapshot, 'destinationIdentity': 'synthetic-source-control'},
                {'reviewDigest': review},
                {'action': 'resume-restored-migration', 'receipt': list(b'RMA\x01source-control'),
                 'view': restored_view[:43] + list((3).to_bytes(8, 'little')) + restored_view[51:],
                 'replay': False, **snapshot, 'windowAcknowledgement': window,
                 'reviewDigest': review, 'resourcePhysicallyRetired': False}])
            def action(request):
                if request['action'] == 'restore':
                    (root / 'restored-data/state').mkdir(parents=True)
                    (root / 'restored-checkpoint').mkdir()
                return next(responses)
            runner.action = Mock(side_effect=action)
            current = {'state-view': 'synthetic-source-control'}
            with patch.object(offline_campaign, 'precondition', return_value={}), \
                 patch.object(offline_campaign.http, 'aggregate', return_value={'count': '4'}), \
                 patch.object(offline_campaign.http, 'view_token', return_value=bytes(view)), \
                 patch.object(offline_campaign.restore_installation, 'catalogs', return_value={}):
                with self.assertRaisesRegex(ValueError, 'closed-first-restored-migration-activation-result'):
                    runner.restore(3, file, snapshot, current)
            runner.node.start.assert_not_called()
            self.assertEqual(runner.action.call_count, 4)
            request = runner.action.call_args.args[0]
            self.assertEqual(request['action'], 'resume-restored-migration')
            self.assertEqual(request['expectedView'], restored_view)

    def test_restored_activation_refuses_old_receipts_replay_and_changed_physical_or_history_witnesses(self):
        from tools.java_transaction_qualification import offline_campaign
        before = list(b'NV\x02' + bytes([19]) * 32
                      + b''.join(value.to_bytes(8, 'little') for value in (1, 2, 3, 4)))
        after = before[:43] + list((3).to_bytes(8, 'little')) + before[51:]
        request = {'action': 'resume-restored-migration', 'expectedView': before,
                   'snapshotDigest': 'sha256:' + 'a' * 64, 'manifestDigest': 'sha256:' + 'b' * 64,
                   'windowAcknowledgement': 'sha256:' + 'c' * 64}
        review = 'sha256:' + 'd' * 64
        result = {**request, 'receipt': list(b'RMA\x01synthetic-source-control'), 'view': after,
                  'replay': False, 'reviewDigest': review, 'resourcePhysicallyRetired': True}
        result.pop('expectedView')
        self.assertEqual(offline_campaign.restored_migration_result(result, request, review), result)
        changes = ({'receipt': list(b'NRS\x02old')}, {'receipt': list(b'RMA\x01')},
                   {'receipt': [True, 77, 65, 1, 0]}, {'receipt': [0] * 8193}, {'replay': True},
                   {'resourcePhysicallyRetired': False}, {'resourcePhysicallyRetired': 1},
                   {'snapshotDigest': 'sha256:' + 'e' * 64}, {'reviewDigest': 'sha256:' + 'e' * 64},
                   {'view': before}, {'view': after[:59] + list((5).to_bytes(8, 'little'))}, {'approved': True})
        for change in changes:
            with self.subTest(change=list(change)), self.assertRaises(ValueError):
                offline_campaign.restored_migration_result(dict(result, **change), request, review)

    def test_signed_service_integration_is_explicit_and_only_marks_deferred_update_rows(self):
        from tools.java_transaction_qualification import configuration as cfg, evidence, inputs
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            items, publications = [], {}
            names = ('aggregate', 'put-once-legacy-v1', 'put-once-compatible-v2', 'put-once-writer-v2')
            for index, name in enumerate(names):
                directory = root / name
                (directory / 'project').mkdir(parents=True)
                raw = evidence.encoded({'capsule': cfg.SERVICE, 'namespace': cfg.NAMESPACE,
                    'deployment': cfg.DEPLOYMENT, 'binding': cfg.DEPLOYMENT,
                    'operations': [{'operation': function,
                                    'mode': 'strict-command' if function == 'update' else 'fresh-query'}
                                   for function in ('update', 'query', 'scan')]})
                (directory / 'project/transaction-binding.json').write_bytes(raw)
                items.append(SimpleNamespace(name=name, directory=directory,
                    component_digest='sha256:' + str(index + 1) * 64, companion_digest=inputs.digest(raw),
                    requirements_digest=None if name == 'aggregate' else 'sha256:' + 'e' * 64))
                publications[name] = 'publication:sha256:' + str(index + 5) * 64
            original = conductor.cfg.installed(tuple(items), publications, 'e' * 64)
            selected = conductor.cfg.installed(tuple(items), publications, 'e' * 64,
                credential_reference='java-current-http', service_integration_dispatch=True)
            self.assertEqual(len(selected), len(original))
            for old, current in zip(original, selected):
                if 'deferredHttp' not in old:
                    self.assertEqual(old, current)
                else:
                    self.assertEqual(current['function'], 'update')
                    self.assertNotIn('dispatchAuthority', old['deferredHttp'])
                    self.assertEqual(current['deferredHttp']['dispatchAuthority'],
                                     {'formatVersion': 1, 'mode': 'signed-service-integration'})
                    remaining = copy.deepcopy(current)
                    remaining['deferredHttp'].pop('dispatchAuthority')
                    remaining['deferredHttp']['credentialReference'] = cfg.RECIPIENT_CREDENTIAL
                    self.assertEqual(old, remaining)
            for selected_flag, reference in ((1, 'java-current-http'), (True, cfg.RECIPIENT_CREDENTIAL)):
                with self.assertRaises(ValueError):
                    conductor.cfg.installed(tuple(items), publications, 'e' * 64,
                        credential_reference=reference, service_integration_dispatch=selected_flag)

    def test_restored_migration_request_keeps_exact_snapshot_window_and_original_operation(self):
        from tools.java_transaction_qualification import offline_campaign
        view = list(b'NV\x02' + bytes([19]) * 32
                    + b''.join(value.to_bytes(8, 'little') for value in (1, 2, 3, 4)))
        file = {'root': '/private/original-snapshots', 'name': 'restore-checkpoint-v2.snapshot'}
        snapshot = {'snapshotDigest': 'sha256:' + 'a' * 64, 'manifestDigest': 'sha256:' + 'b' * 64}
        window = 'sha256:' + 'c' * 64
        original = copy.deepcopy(file)
        request = offline_campaign.restored_resume_request(view, file, snapshot, window, 'java-schema-v1-to-v2')
        self.assertEqual(request, {'action': 'resume-restored-migration', 'operationId': 'java-restored-resume',
            'migrationOperationId': 'java-schema-v1-to-v2', 'file': file, 'expectedView': view,
            **snapshot, 'windowAcknowledgement': window})
        request['file']['name'] = 'local-copy'
        self.assertEqual(file, original)
        self.assertEqual(offline_campaign.restored_resume_request(view, None, None, None),
            {'action': 'resume', 'operationId': 'java-restored-resume', 'expectedView': view})
        for migration, changed in (('different-migration', snapshot),
                                   ('java-schema-v1-to-v2', dict(snapshot, snapshotDigest='sha256:' + '0' * 64))):
            with self.assertRaises(ValueError):
                offline_campaign.restored_resume_request(view, file, changed, window, migration)

    def test_return_to_legacy_records_both_deployments_without_reusing_measured_case(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification import configuration as cfg, evidence, lifecycle
        from tools.java_transaction_qualification.current_activation import CurrentActivation
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            collector = evidence.Evidence(root / 'evidence')
            activation = CurrentActivation.__new__(CurrentActivation)
            activation.client = SimpleNamespace(evidence=collector)
            activation.configuration = SimpleNamespace(authority='localhost:1')
            activation.node = SimpleNamespace(process=None, start=lambda *_a, **_k: None)
            name = 'put-once-legacy-v1'
            activation.items = {name: SimpleNamespace(name=name)}
            activation.path = lambda _: root / 'selected.json'
            activation.metadata = {name: ({'generation': '1'}, {'deploymentGeneration': 1})}
            with patch.object(lifecycle, 'bind_http_routes') as binding:
                activation.start(None, name, 'legacy-runtime')
                activation.metadata[name] = ({'generation': '3'}, {'deploymentGeneration': 3})
                activation.start(None, name, 'legacy-after-diagnostic')
                self.assertEqual(binding.call_count, 2)
            self.assertEqual(collector.cases, ['deploy-' + name + '-legacy-runtime',
                                              'deploy-' + name + '-legacy-after-diagnostic'])
            self.assertEqual(len(collector.files), 2)
            from tools.phase2_operator_process import read_json
            receipts = [read_json(collector.directory / row['path']) for row in collector.files]
            self.assertEqual([row['observed']['deployment']['generation'] for row in receipts], ['1', '3'])

    def test_current_proposals_bind_native_state_staging_and_exact_http_dispatch_grants(self):
        from tools.java_transaction_qualification import configuration as cfg
        value, operations, publications = observation()
        for row in value['deferredHttp']:
            row['operation'] = 'http'
        hosts = policies.ObservedHosts.read(value, operations, intent_operation='http')
        endpoint = current_recipient.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 52027}, 'e' * 64)
        proposal = policies.documents(hosts, publications, current_http_endpoint=endpoint)
        grants = {row['capability']: row for row in proposal['deploymentGrants']}
        self.assertEqual(len(grants), len(proposal['deploymentGrants']))
        self.assertEqual(set(grants), {*(pair[0] for pair in cfg.CLOCKS.values()),
                                      policies.STATE_CONTRACT, policies.INTENT_CONTRACT})
        self.assertEqual(grants[policies.STATE_CONTRACT], {'capability': policies.STATE_CONTRACT,
                         'policy': cfg.STATE_POLICY, 'operations': policies.DATA_OPERATIONS})
        self.assertEqual(grants[policies.INTENT_CONTRACT], {'capability': policies.INTENT_CONTRACT,
                         'policy': cfg.STAGING_POLICY, 'operations': ['stage']})
        self.assertNotIn(policies.HTTP_CONTRACT, grants)
        provider = hosts.providers['http']
        self.assertEqual(proposal['bindings']['java-dispatch-installed'], policies.binding(
            policies.HTTP_CONTRACT, provider['profile'], provider['configurationDigest'],
            int(provider['configurationEpoch']), ['send']))
        for rule, source in zip(proposal['policies'][cfg.DISPATCH_POLICY]['rules'], hosts.effects):
            self.assertEqual(rule['capability'], policies.HTTP_CONTRACT)
            self.assertEqual(rule['operations'], ['send'])
            self.assertEqual(rule['publications'], [source['publication']])
            self.assertEqual(rule['principals'], [{'kind': 'service', 'subject': source['dispatchSubject']}])
            self.assertEqual(rule['resources'], {'kind': 'http', 'origins': [endpoint['origin']],
                'methods': ['GET', 'POST'], 'paths': ['/effect'], 'pathPrefixes': ['/receipts/']})
            self.assertEqual(rule['ceiling'], {'operations': 1, 'inputBytes': 27,
                'outputBytes': 2048, 'wallTimeMillis': 2000})
        value['deferredHttp'][0]['operation'] = 'put-once'
        with self.assertRaises(ValueError):
            policies.documents(hosts, publications, current_http_endpoint=endpoint)

    def test_current_session_program_requires_explicit_profile_order_and_single_runtime(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification import lifecycle
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            with self.assertRaises(ValueError):
                lifecycle.Node(SimpleNamespace(phase4=False), root / 'unused', root,
                               current_publication_program=True)
            node = lifecycle.Node(SimpleNamespace(phase4=True), root / 'unused', root,
                                  current_publication_program=True)
            path = root / 'configuration.json'
            write_json(path, {'state': {'formatVersion': 2, 'operations': []}})
            with patch.object(lifecycle, 'Process') as process:
                for position, session in ((0, None), (0, 'authority'), (2, 'namespace-create'),
                                           (14, 'restored-runtime')):
                    node.ordinal = position
                    with self.subTest(position=position, session=session), self.assertRaises(ValueError):
                        node.start(path, current_session=session)
                node.ordinal = 0
                path = root / 'populated-configuration.json'
                write_json(path, {'state': {'formatVersion': 2, 'operations': [{'publication': 'extra'}]}})
                with self.assertRaises(ValueError):
                    node.start(path, current_session='publish')
                process.assert_not_called()
            legacy = lifecycle.Node(SimpleNamespace(), root / 'unused', root)
            legacy.ordinal = 6
            with self.assertRaises(ValueError):
                legacy.start(path)

    def test_current_transition_retires_before_metadata_and_never_starts_after_uncertain_mutation(self):
        from unittest.mock import patch
        from tools.java_transaction_qualification.current_activation import CurrentActivation
        from tools.java_transaction_qualification import configuration as cfg, lifecycle
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            names = ('aggregate', 'put-once-legacy-v1', 'put-once-compatible-v2',
                     'put-once-writer-v2', 'put-once-diagnostics')
            publications = {name: 'publication:sha256:' + str(index + 1) * 64
                            for index, name in enumerate(names)}
            items = tuple(SimpleNamespace(name=name, component_digest='sha256:' + str(index + 5) * 64)
                          for index, name in enumerate(names))
            rows = [{'tenant': cfg.TENANT, 'contract': cfg.CONTRACT, 'binding': cfg.DEPLOYMENT,
                     'deployment': cfg.DEPLOYMENT, 'incarnation': 1, 'function': function,
                     'publication': publications[item.name], 'componentDigest': item.component_digest}
                    for item in items for function in ('update', 'query', 'scan')]
            full = root / 'inspected.json'
            write_json(full, {'state': {'formatVersion': 2, 'operations': rows}})
            configuration = cfg.Configuration(root / 'bootstrap.json',
                {'state': {'formatVersion': 2, 'operations': []}}, 'localhost:1', {})
            events = []
            node = SimpleNamespace(process=None, current_publication_program=True)
            node.start = lambda path, **kwargs: events.append(('start', path, kwargs))
            node.stop = lambda: events.append(('stop',))
            client = SimpleNamespace(phase4=True, evidence=SimpleNamespace(passed=lambda *_: None))
            activation = CurrentActivation(client, configuration, node, root, items, publications,
                                           {'deploymentGrants': ['original']}, full)
            with patch.object(lifecycle, 'deployment_metadata', side_effect=ValueError('uncertain')) as metadata, \
                 patch.object(lifecycle, 'admission_lease_interval') as lease:
                with self.assertRaisesRegex(ValueError, 'uncertain'):
                    activation.select_metadata('put-once-legacy-v1', 'legacy-metadata')
                self.assertEqual([row[0] for row in events], ['start', 'stop'])
                self.assertEqual(activation.metadata, {})
                lease.assert_not_called()
                metadata.assert_called_once()
            events.clear()
            with patch.object(lifecycle, 'deployment_metadata', return_value=({'generation': '1'}, {'original': True})), \
                 patch.object(lifecycle, 'admission_lease_interval', side_effect=lambda _: events.append(('lease',))):
                selected = activation.select_metadata('put-once-legacy-v1', 'legacy-metadata')
            self.assertEqual([row[0] for row in events], ['start', 'stop', 'lease'])
            from tools.phase2_operator_process import read_json
            self.assertEqual(read_json(selected)['state']['operations'], rows[3:6])
            self.assertEqual(configuration.value['state']['operations'], [])

    def test_active_runtime_selects_one_exact_publication_and_copies_original_operations(self):
        from tools.java_transaction_qualification import configuration as cfg
        rows = []
        for index in (1, 2):
            for function in ('update', 'query', 'scan'):
                rows.append({'tenant': cfg.TENANT, 'contract': cfg.CONTRACT, 'binding': cfg.DEPLOYMENT,
                             'deployment': cfg.DEPLOYMENT, 'incarnation': 1, 'function': function,
                             'publication': 'publication:sha256:' + str(index) * 64,
                             'componentDigest': 'sha256:' + str(index + 2) * 64})
        before = copy.deepcopy(rows)
        selected = cfg.active_operations(rows, 'publication:sha256:' + '1' * 64, 'sha256:' + '3' * 64)
        self.assertEqual(selected, rows[:3])
        selected[0]['function'] = 'changed-local-copy'
        self.assertEqual(rows, before)
        for changed in (rows[:2], rows[:3] + [rows[0]], [dict(row, componentDigest='sha256:' + '4' * 64) for row in rows[:3]]):
            with self.assertRaises(ValueError):
                cfg.active_operations(changed, 'publication:sha256:' + '1' * 64, 'sha256:' + '3' * 64)

    def test_retained_decoders_have_four_distinct_explicit_signed_sources_without_generic_alias(self):
        from tools.java_transaction_qualification import recovery
        names = ('put-once-legacy-v1', 'put-once-compatible-v2', 'put-once-writer-v2', 'put-once-diagnostics')
        items = {name: SimpleNamespace(component_digest='sha256:' + str(index + 1) * 64)
                 for index, name in enumerate(names)}
        publications = {name: 'publication:sha256:' + str(index + 5) * 64 for index, name in enumerate(names)}
        items['aggregate'] = SimpleNamespace(component_digest='sha256:' + 'a' * 64)
        publications['aggregate'] = 'publication:sha256:' + 'b' * 64
        selected = recovery.decoder_sources(items, publications)
        self.assertEqual(len(selected), 4)
        self.assertFalse(any(row['publication'] == publications['aggregate'] for row in selected))
        for changed in (dict(publications, **{names[0]: publications[names[1]]}),
                        {key: value for key, value in publications.items() if key != names[0]}):
            with self.assertRaises(ValueError):
                recovery.decoder_sources(items, changed)

    def test_installation_keeps_exact_declared_ca_reference_and_body_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            tls = root / 'tls'
            tls.mkdir()
            for name in ('ca.der', 'server.pem', 'key.pem'):
                (tls / name).write_bytes(b'synthetic-source-control-only')
            endpoint = current_recipient.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 52027}, 'e' * 64)
            endpoint_path = root / 'endpoint.json'
            write_json(endpoint_path, endpoint)
            installation = {'identity': {'id': 'http', 'tenant': 'examples', 'service': 'runtime-host', 'epoch': 1},
                            'credentialDirectory': '/original/private/credentials',
                            'credentials': [{'reference': 'java-current-http', 'file': 'original',
                                             'destination': 0, 'header': 'authorization'}],
                            'deferred': [endpoint], 'configuration': {
                                'formatVersion': 1, 'publicRoots': False,
                                'extraRoots': [list((tls / 'ca.der').read_bytes())], 'destinations': [],
                                'limits': {'maximumRequestBodyBytes': 27, 'maximumResponseBodyBytes': 2048,
                                           'maximumEncodedResponseBytes': 2048, 'maximumHeaderBytes': 8192,
                                           'maximumHeaders': 32, 'maximumRedirects': 0}}}
            path = root / 'installation.json'
            write_json(path, installation)
            args = SimpleNamespace(current_http_installation=path, current_http_tls=tls,
                                   current_http_endpoint=endpoint_path)
            self.assertEqual(conductor.current_installation(args), installation)
            for index, changed in enumerate((('ca', None), ('reference', None), ('limits', None), ('approval', None))):
                invalid = copy.deepcopy(installation)
                if changed[0] == 'ca':
                    invalid['configuration']['extraRoots'] = [[1, 2, 3]]
                elif changed[0] == 'reference':
                    invalid['credentials'][0]['reference'] = 'java-put-once'
                elif changed[0] == 'limits':
                    invalid['configuration']['limits']['maximumRequestBodyBytes'] = 32768
                else:
                    invalid['configuration']['approved'] = True
                invalid_path = root / f'install-{index}.json'
                write_json(invalid_path, invalid)
                args.current_http_installation = invalid_path
                with self.assertRaises(ValueError):
                    conductor.current_installation(args)

    def test_endpoint_file_is_closed_and_retains_original_twenty_seven_byte_ceiling(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            value = current_recipient.endpoint({'scheme': 'https', 'host': 'localhost', 'port': 52027}, 'e' * 64)
            path = root / 'endpoint.json'
            write_json(path, value)
            self.assertEqual(conductor.current_endpoint(SimpleNamespace(current_http_endpoint=path)), value)
            for index, change in enumerate(({'approved': True}, {'maximumPayloadBytes': 4096},
                                            {'origin': {'scheme': 'http', 'host': 'localhost', 'port': 52027}})):
                invalid = root / f'invalid-{index}.json'
                write_json(invalid, dict(value, **change))
                with self.assertRaises(ValueError):
                    conductor.current_endpoint(SimpleNamespace(current_http_endpoint=invalid))

    def test_current_endpoint_cannot_select_historical_or_unpaired_capsules(self):
        with self.assertRaisesRegex(ValueError, 'current-http-requires-explicit-current-captures'):
            conductor.current_mode(SimpleNamespace(current_selections=None, current_selections_digest=None,
                                                    current_http_endpoint=Path('/not-read')))

    def test_observed_current_operation_requires_explicit_selection_and_all_publications_match(self):
        value, operations, _ = observation()
        for row in value['deferredHttp']:
            row['operation'] = 'http'
        before = copy.deepcopy(value)
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations)
        hosts = policies.ObservedHosts.read(value, operations, intent_operation='http')
        self.assertEqual(hosts.value, before)
        value['deferredHttp'][0]['operation'] = 'put-once'
        with self.assertRaises(ValueError):
            policies.ObservedHosts.read(value, operations, intent_operation='http')

    def test_fault_staging_framing_uses_exact_operation_without_changing_historical_accounting(self):
        from tools.java_transaction_qualification import diagnostic_campaign as diagnostic
        self.assertEqual(diagnostic.stage_write_bytes('put-once'), diagnostic.STAGE_WRITE_BYTES)
        self.assertEqual(diagnostic.stage_write_bytes('http'), diagnostic.STAGE_WRITE_BYTES - 4)
        with self.assertRaises(ValueError):
            diagnostic.stage_write_bytes('unknown')


if __name__ == '__main__':
    unittest.main()

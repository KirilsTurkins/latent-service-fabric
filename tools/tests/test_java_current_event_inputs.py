"""Signed Java event source inputs constrain packaging and never grant authority."""
import json
from pathlib import Path
import tempfile
import unittest

from tools.java_transaction_schema import SOURCE, create
from tools.rust_capsule_project import read_file, read_json, snapshot
from tools.transaction_guest_project import CURRENT_EVENT_PROFILE, EVENT_REQUIREMENTS, package_effect_requirements


class CurrentJavaEventInputs(unittest.TestCase):
    def test_explicit_native_profile_is_carried_without_changing_guest_intent(self):
        profile = 'js-window-v1:' + 'a' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plain = create(root / 'plain', 'legacy-v1')
            project = create(root / 'current', 'legacy-v1', event_profile=profile)
            files = snapshot(project)
            self.assertEqual(read_file(project / SOURCE), read_file(plain / SOURCE))
            self.assertIn(b'new Intent("approved-event", "event", payload)', files[SOURCE])
            self.assertNotIn(EVENT_REQUIREMENTS, snapshot(plain))
            requirements = read_json(project / EVENT_REQUIREMENTS)
            self.assertEqual(requirements['idempotencyProfile'], profile)
            self.assertEqual(requirements['operation'], 'event')
            self.assertEqual(requirements['protocol'], 'lsf-jetstream-event-v1')
            output = root / 'package'
            output.mkdir()
            self.assertEqual(package_effect_requirements(output, read_json(project / 'capsule-project.json'), files),
                             (EVENT_REQUIREMENTS, 'asset', 'application/json'))
            self.assertEqual((output / EVENT_REQUIREMENTS).read_bytes(), files[EVENT_REQUIREMENTS])
            from tools.java_transaction_qualification.packaging import schema_assets
            self.assertEqual(schema_assets(files)[CURRENT_EVENT_PROFILE], files[CURRENT_EVENT_PROFILE])
            from types import SimpleNamespace
            from tools.java_transaction_qualification.inputs import digest
            from tools.java_transaction_qualification.packaging import captured_assets
            item = SimpleNamespace(name="aggregate", requirements_digest=None,
                                   event_requirements_digest=digest(files[EVENT_REQUIREMENTS]))
            self.assertEqual(captured_assets(item, files)[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            with self.assertRaises(ValueError):
                captured_assets(SimpleNamespace(name="aggregate", requirements_digest=None,
                                                event_requirements_digest="sha256:" + "0" * 64), files)
            without_marker = dict(files)
            del without_marker[CURRENT_EVENT_PROFILE]
            with self.assertRaises(ValueError):
                schema_assets(without_marker)

    def test_compiler_selection_is_exclusive_and_captures_the_profile(self):
        from tools.compile_transaction_guests import authored_project, compile_guests
        profile = 'js-window-v1:' + 'a' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = authored_project('java', 'aggregate', root / 'project', java_current_event_profile=profile)
            self.assertEqual(read_json(project / EVENT_REQUIREMENTS)['idempotencyProfile'], profile)
            for language, options in [
                ('rust', {}), ('java', {'java_schema_put_once': True}),
                ('java', {'java_post_stage_diagnostic': True}), ('java', {'java_state_acceptance': True}),
                ('java', {'java_early_http_denial': True}),
                ('java', {'java_current_http_profile': 'qualified-http-v1:' + 'b' * 64}),
            ]:
                target = root / ('invalid-' + str(len(list(root.iterdir()))))
                with self.assertRaises(ValueError):
                    compile_guests(language, target, java_current_event_profile=profile, **options)
                self.assertFalse(target.exists())
            with self.assertRaises(ValueError):
                authored_project('java', 'forbidden-http', root / 'wrong', java_current_event_profile=profile)

    def test_node_configuration_pins_only_the_selected_event_operation(self):
        from tools.java_transaction_qualification.configuration import current_event_operations
        from tools.java_transaction_qualification.inputs import ComponentInput, digest
        profile = 'js-window-v1:' + 'a' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / 'project', 'legacy-v1', event_profile=profile)
            files = snapshot(project)
            item = ComponentInput('aggregate', root, 'sha256:' + '1' * 64,
                digest(files['transaction-binding.json']), 'sha256:' + '2' * 64, '3' * 40,
                'sha256:' + '4' * 64, None, digest(files[EVENT_REQUIREMENTS]))
            args = dict(provider_id='events', credential_reference='event-secret',
                        staging_binding='event-stage', staging_policy='stage',
                        dispatch_binding='event-dispatch', dispatch_policy='dispatch')
            publication = 'publication:sha256:' + '5' * 64
            rows = current_event_operations(item, publication, '6' * 64, **args)
            self.assertEqual([row['function'] for row in rows], ['update', 'query', 'scan'])
            self.assertEqual(rows[0]['deferredEvent']['requirementsDigest'], item.event_requirements_digest)
            self.assertEqual(rows[0]['deferredEvent']['providerIncarnation'], '6' * 64)
            self.assertEqual(rows[0]['deferredEvent']['dispatchAuthority']['mode'], 'signed-service-integration')
            self.assertNotIn('deferredEvent', rows[1])
            self.assertNotIn('deferredEvent', rows[2])
            with self.assertRaises(ValueError):
                current_event_operations(item, publication, 'BAD', **args)
            for identity in ('', 'x' * 257, 'bad\u0085identity'):
                with self.assertRaises(ValueError):
                    current_event_operations(item, publication, '6' * 64, **{**args, 'provider_id': identity})
            changed = json.loads(files[EVENT_REQUIREMENTS])
            changed['binding'] = 'other-event'
            (project / EVENT_REQUIREMENTS).write_text(json.dumps(changed), encoding='utf-8')
            with self.assertRaises(ValueError):
                current_event_operations(item, publication, '6' * 64, **args)
            from dataclasses import replace
            reselected = replace(item, event_requirements_digest=digest(read_file(project / EVENT_REQUIREMENTS)))
            with self.assertRaises(ValueError):
                current_event_operations(reselected, publication, '6' * 64, **args)

    def test_observed_event_scope_requires_the_same_signed_provider_and_profile(self):
        import copy
        from tools.java_transaction_qualification.configuration import (current_event_operations, SERVICE, TENANT)
        from tools.java_transaction_qualification.event_hosts import ObservedEventHost
        from tools.java_transaction_qualification.inputs import ComponentInput, digest
        profile = 'js-window-v1:' + 'a' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / 'project', 'legacy-v1', event_profile=profile)
            files = snapshot(project)
            item = ComponentInput('aggregate', root, 'sha256:' + '1' * 64,
                digest(files['transaction-binding.json']), 'sha256:' + '2' * 64, '3' * 40,
                'sha256:' + '4' * 64, None, digest(files[EVENT_REQUIREMENTS]))
            publication = 'publication:sha256:' + '5' * 64
            operations = current_event_operations(item, publication, '6' * 64, provider_id='events',
                credential_reference='event-secret', staging_binding='event-stage', staging_policy='stage',
                dispatch_binding='event-dispatch', dispatch_policy='dispatch')
            provider = {'id':'events','tenant':TENANT,'service':'event-host',
                'capability':'latent:events/publisher@0.2.0','profile':'native-nats-v1',
                'configurationDigest':'sha256:'+'6'*64,'configurationEpoch':'1'}
            subject = f'service:{len(TENANT.encode())}:{TENANT}:{len(SERVICE.encode())}:{SERVICE}'
            effect = {'tenant':TENANT,'service':SERVICE,'publication':publication,'namespace':'transactional-aggregate',
                'incarnation':1,'logicalBinding':'approved-event','operation':'event','stagingBinding':'event-stage',
                'dispatchBinding':'event-dispatch','providerProfile':'nats-jetstream-effect-v1',
                'configurationDigest':'sha256:'+'a'*64,'configurationEpoch':1,'dispatchSubject':subject,
                'dispatchRecoveryKind':'service-integration','dispatchRecoveryScope':'observed-scope',
                'resultPolicy':'java-original-result-v1'}
            caller = {'subject':'java-transaction-alice','ownerKind':'user','tenant':TENANT,'service':None,
                      'recoveryKind':'original-caller','recoveryScope':'original-caller-scope'}
            host = {'schemaVersion':'latent.transaction-host-inspection.v1','configuredProviders':[provider],
                'configuredHttpCallers':[caller],'configuredTransportCallers':[caller],'stateProviderProfile':'state',
                'stateConfigurationDigest':'sha256:'+'7'*64,'stateConfigurationEpoch':1,
                'deferredHttp':[],'deferredEvent':[effect]}
            selected = {'provider':'events','destination':'updated','adapter':'nats-jetstream-effect-v1',
                'intent_format':1,'payload_format':'nats-event-value-v1','idempotency_profile':profile}
            preview = {'schemaVersion':'latent.configured-event-effect-inspection.v1',
                       'adapters':[{'configurationDigest':'sha256:'+'6'*64,'configurationEpoch':1,'profile':selected}]}
            from tools.java_transaction_qualification.event_hosts import select_profile
            selected_profile = select_profile(preview, 'events', 'updated')
            self.assertEqual(selected_profile.idempotency_profile, profile)
            self.assertEqual(selected_profile.configuration_digest, 'sha256:' + '6' * 64)
            with self.assertRaises(ValueError):
                select_profile(preview, 'events', 'other')
            duplicate = copy.deepcopy(preview)
            duplicate['adapters'].append(copy.deepcopy(duplicate['adapters'][0]))
            with self.assertRaises(ValueError):
                select_profile(duplicate, 'events', 'updated')
            observed = ObservedEventHost.read(host, preview, operations, files[EVENT_REQUIREMENTS])
            self.assertEqual(observed.profile['destination'], 'updated')
            from unittest.mock import patch
            from tools.java_transaction_qualification import lifecycle
            with patch.object(lifecycle, 'native', side_effect=[json.dumps(preview).encode(), json.dumps(host).encode()]) as native, \
                 patch.object(lifecycle, 'admission_lease_interval') as retire:
                selected_preview = lifecycle.inspect_event_profile(object(), Path('latentd'), Path('node.json'))
                actual = lifecycle.inspect_event_host(object(), Path('latentd'), Path('node.json'), operations,
                                                      files[EVENT_REQUIREMENTS], selected_preview)
                self.assertEqual(actual.profile['destination'], 'updated')
                self.assertEqual(native.call_args_list[0].args[3], 'inspect-configured-event-effects')
                self.assertEqual(native.call_args_list[1].args[3], 'inspect-transaction-hosts')
                self.assertEqual(retire.call_count, 2)
            from tools.java_transaction_qualification.event_hosts import policy_documents
            proposals = policy_documents(observed, operations[0])
            self.assertEqual(proposals['bindings']['event-stage']['capability'], 'latent:intents/staging@0.1.0')
            self.assertEqual(proposals['bindings']['event-dispatch']['capability'], 'latent:events/publisher@0.2.0')
            self.assertEqual(proposals['policies']['dispatch']['rules'][0]['resources']['subjects'], ['updated'])
            self.assertEqual([grant['capability'] for grant in proposals['deploymentGrants']], ['latent:intents/staging@0.1.0'])
            from tools.java_transaction_qualification import policies
            class Client:
                def __init__(self, directory):
                    self.directory, self.calls = directory, []
                def call(self, *arguments):
                    self.calls.append(arguments)
                    operation_id = arguments[arguments.index('--operation-id') + 1]
                    return {'outcomeKnown': True, 'data': {'receipt': {'operationId': operation_id}}}
            policy_root = root / 'policy-inputs'
            policy_root.mkdir()
            client = Client(policy_root)
            mutations = policies.prepare_mutations(client, proposals)
            self.assertEqual(len(mutations), 4)
            original = (policy_root / mutations[-1]['file']).read_bytes()
            (policy_root / mutations[-1]['file']).write_bytes(original + b' ')
            with self.assertRaises(ValueError):
                policies.apply_retained(client, proposals, mutations)
            self.assertEqual(client.calls, [])
            (policy_root / mutations[-1]['file']).write_bytes(original)
            receipts = policies.apply_retained(client, proposals, mutations)
            self.assertEqual(len(receipts), 4)
            self.assertEqual(len(client.calls), 4)
            with self.assertRaises(TypeError):
                observed.profile['destination'] = 'other'
            changed_operation = copy.deepcopy(operations[0])
            changed_operation['deferredEvent']['dispatchPolicies'] = ['other']
            with self.assertRaises(ValueError):
                policy_documents(observed, changed_operation)
            oversized = copy.deepcopy(operations[0])
            oversized['componentDigest'] = 'x' * 100_000
            with self.assertRaises(ValueError):
                policy_documents(observed, oversized)
            for surface, field in [('host','publication'), ('host','dispatchSubject'), ('host','configurationDigest'),
                                   ('preview','configurationDigest'), ('preview','configurationEpoch')]:
                bad_host, bad_preview = copy.deepcopy(host), copy.deepcopy(preview)
                target = bad_host['deferredEvent'][0] if surface == 'host' else bad_preview['adapters'][0]
                target[field] = 'wrong'
                with self.assertRaises(ValueError):
                    ObservedEventHost.read(bad_host, bad_preview, operations, files[EVENT_REQUIREMENTS])
            bad_host = copy.deepcopy(host)
            bad_host['configuredTransportCallers'][0] = {**bad_host['configuredTransportCallers'][0], 'recoveryScope': 'different-caller'}
            with self.assertRaises(ValueError):
                ObservedEventHost.read(bad_host, preview, operations, files[EVENT_REQUIREMENTS])
            bad_host = copy.deepcopy(host)
            bad_host['configuredProviders'][0]['service'] = 'bad\u0085service'
            with self.assertRaises(ValueError):
                ObservedEventHost.read(bad_host, preview, operations, files[EVENT_REQUIREMENTS])
            ambiguous = copy.deepcopy(preview)
            duplicate = copy.deepcopy(ambiguous['adapters'][0])
            duplicate['profile']['idempotency_profile'] = 'js-window-v1:' + 'b' * 64
            ambiguous['adapters'].append(duplicate)
            with self.assertRaises(ValueError):
                ObservedEventHost.read(host, ambiguous, operations, files[EVENT_REQUIREMENTS])
            bad = copy.deepcopy(preview)
            bad['adapters'][0]['profile']['destination'] = ''
            with self.assertRaises(ValueError):
                ObservedEventHost.read(host, bad, operations, files[EVENT_REQUIREMENTS])
            bad = copy.deepcopy(preview)
            bad['adapters'][0]['profile']['intent_format'] = True
            with self.assertRaises(ValueError):
                ObservedEventHost.read(host, bad, operations, files[EVENT_REQUIREMENTS])
            with self.assertRaises(ValueError):
                ObservedEventHost.read(host, preview, operations, files[EVENT_REQUIREMENTS] + b' ')
            changed = json.loads(files[EVENT_REQUIREMENTS])
            changed['ceiling']['maximum_attempts'] = True
            raw = json.dumps(changed).encode()
            reselected = copy.deepcopy(operations)
            reselected[0]['deferredEvent']['requirementsDigest'] = digest(raw)
            with self.assertRaises(ValueError):
                ObservedEventHost.read(host, preview, reselected, raw)

    def test_packaging_refuses_changed_identity_missing_marker_and_ambiguous_effects(self):
        profile = 'js-window-v1:' + 'b' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / 'current', 'writer-v2', event_profile=profile)
            original = snapshot(project)
            model = read_json(project / 'capsule-project.json')
            changes = []
            missing = dict(original)
            del missing[CURRENT_EVENT_PROFILE]
            changes.append(missing)
            altered = dict(original)
            value = json.loads(altered[EVENT_REQUIREMENTS])
            value['idempotencyProfile'] = 'js-window-v1:' + 'c' * 64
            altered[EVENT_REQUIREMENTS] = json.dumps(value).encode()
            changes.append(altered)
            ambiguous = dict(original)
            ambiguous['deferred-http-requirements.json'] = b'{}'
            changes.append(ambiguous)
            for index, files in enumerate(changes):
                output = root / ('bad-' + str(index))
                output.mkdir()
                with self.assertRaises(ValueError):
                    package_effect_requirements(output, model, files)
                self.assertFalse((output / EVENT_REQUIREMENTS).exists())
            for bad in ('js-window-v1:' + 'A' * 64, 'qualified-http-v1:' + 'a' * 64, '', 7):
                with self.assertRaises(ValueError):
                    create(root / ('bad-profile-' + str(len(str(bad)))), 'legacy-v1', event_profile=bad)
            with self.assertRaises(ValueError):
                create(root / 'mixed', 'legacy-v1', effect='put-once', event_profile=profile)


if __name__ == '__main__':
    unittest.main()

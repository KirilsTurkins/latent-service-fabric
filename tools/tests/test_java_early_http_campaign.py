"""Closed early observer controls; synthetic values confer no runtime evidence."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import configuration as cfg, early_http_campaign as early, lifecycle, policies
from tools.java_transaction_qualification.inputs import digest
from tools.phase2_operator_process import write_json
from tools import run_java_early_http_qualification as runner

PUBLICATION = 'publication:sha256:' + 'a' * 64


def hosts():
    alice = {'subject': cfg.ALICE, 'ownerKind': 'user', 'tenant': cfg.TENANT, 'service': None,
             'recoveryKind': 'original-caller', 'recoveryScope': 'user:alice'}
    operator = dict(alice, subject=cfg.OPERATOR, ownerKind='administrator', recoveryScope='administrator:operator')
    return {'schemaVersion': 'latent.transaction-host-inspection.v1', 'stateProviderProfile': 'state-current',
            'stateConfigurationDigest': 'sha256:' + 'b' * 64, 'stateConfigurationEpoch': 1,
            'configuredHttpCallers': [alice], 'configuredTransportCallers': [alice, operator], 'deferredHttp': [],
            'configuredProviders': [{'id': name, 'tenant': cfg.TENANT, 'service': 'runtime-host',
                'capability': cfg.CLOCKS[name][0] if name in cfg.CLOCKS else policies.HTTP_CONTRACT,
                'profile': name + '-current', 'configurationDigest': 'sha256:' + 'c' * 64,
                'configurationEpoch': '1'} for name in (*cfg.CLOCKS, 'http')]}


class EarlyHttpControls(unittest.TestCase):
    def test_four_sessions_cannot_expand_other_programs_or_install_restore_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            client = SimpleNamespace(phase4=True, environment={}, cancellation=None)
            node = lifecycle.Node(client, root / 'unused', root, current_publication_program=True,
                                  current_program='early-http')
            self.assertEqual(node.program, ('publish', 'authority', 'namespace-create', 'early-http-runtime'))
            self.assertEqual(len(lifecycle.CURRENT_NODE_PROGRAM), 14)
            self.assertEqual(len(lifecycle.PENDING_NODE_PROGRAM), 6)
            path = root / 'node.json'
            rows = [{'publication': PUBLICATION, 'function': name} for name in ('update', 'query', 'scan')]
            with patch.object(lifecycle, 'Process', side_effect=RuntimeError('not-created')) as process:
                for position, session in enumerate(node.program):
                    node.ordinal = position
                    path = root / ('node-' + str(position) + '.json')
                    write_json(path, {'state': {'formatVersion': 2, 'operations': [] if position < 2 else rows}})
                    with self.assertRaisesRegex(RuntimeError, 'not-created'):
                        node.start(path, current_session=session)
                self.assertEqual(process.call_count, 4)
                with self.assertRaises(ValueError):
                    node.start(path, current_session='early-http-runtime')
                node.ordinal = 3
                with self.assertRaises(ValueError):
                    node.start(path, restore_authority=True)
                self.assertEqual(process.call_count, 4)
            with self.assertRaises(ValueError):
                lifecycle.Node(SimpleNamespace(), root / 'unused', root, current_program='early-http')

    def test_selection_is_one_early_capture_and_rejects_changed_or_six_component_documents(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / 'selection.json'
            row = {'sourceCommit': 'a' * 40, 'variant': 'forbidden-http-before-stage',
                   'reportDigest': 'sha256:' + 'b' * 64, 'componentDigest': 'sha256:' + 'c' * 64,
                   'compilerInputsDigest': 'sha256:' + 'd' * 64}
            write_json(path, {'schemaVersion': 'latent.java.early-http-selection.v1', 'selection': row})
            expected = digest(path.read_bytes())
            self.assertEqual(runner.selection(path, expected).variant, row['variant'])
            for mutate in (lambda value: value['selection'].update(variant='forbidden-http'),
                           lambda value: value.update(selections=[row]),
                           lambda value: value['selection'].update(sourceCommit='old')):
                value = {'schemaVersion': 'latent.java.early-http-selection.v1', 'selection': dict(row)}
                mutate(value)
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):
                    runner.selection(path, digest(path.read_bytes()))
            with self.assertRaises(ValueError):
                runner.selection(path, expected)

    def test_operations_use_exact_companion_service_and_never_install_effects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / 'project').mkdir()
            path = root / 'project/transaction-binding.json'
            value = {'capsule': early.SERVICE, 'deployment': early.DEPLOYMENT, 'binding': early.DEPLOYMENT,
                     'namespace': cfg.NAMESPACE, 'operations': [
                {'operation': name, 'mode': 'strict-command' if name == 'update' else 'fresh-query',
                 'inputFormat': 'lsf-wit-values-v1', 'resultFormat': 'lsf-wit-values-v1'}
                for name in ('update', 'query', 'scan')]}
            path.write_text(json.dumps(value))
            item = SimpleNamespace(name='forbidden-http-before-stage', requirements_digest=None,
                directory=root, companion_digest=digest(path.read_bytes()), component_digest='sha256:' + 'e' * 64)
            rows = early.operations(item, PUBLICATION)
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row['binding'] == early.DEPLOYMENT and 'deferredHttp' not in row for row in rows))
            item.requirements_digest = 'sha256:' + 'f' * 64
            with self.assertRaises(ValueError):
                early.operations(item, PUBLICATION)
            item.requirements_digest = None
            value['capsule'] = cfg.SERVICE
            path.write_text(json.dumps(value))
            item.companion_digest = digest(path.read_bytes())
            with self.assertRaises(ValueError):
                early.operations(item, PUBLICATION)

    def test_actual_host_proposals_exclude_http_intent_recovery_and_foreign_service(self):
        documents = early.proposals(hosts(), PUBLICATION)
        self.assertEqual(len(documents['bindings']), 3)
        self.assertEqual(len(documents['policies']), 3)
        self.assertEqual({row['capability'] for row in documents['deploymentGrants']},
                         {policies.STATE_CONTRACT, *[value[0] for value in cfg.CLOCKS.values()]})
        for policy in documents['policies'].values():
            for rule in policy['rules']:
                self.assertEqual(rule['services'], [early.SERVICE])
                self.assertEqual(rule['publications'], [PUBLICATION])
                self.assertTrue(set(rule['operations']).isdisjoint(policies.RECOVERY_OPERATIONS))
        state = documents['policies'][cfg.STATE_POLICY]['rules']
        self.assertEqual(state[0]['operations'], policies.DATA_OPERATIONS)
        self.assertEqual(state[1]['operations'], ['namespace-create', 'namespace-inspect', 'read-result'])

    def test_inspection_rejects_deferred_owner_duplicates_and_changed_caller_scope(self):
        for mutate in (lambda value: value['deferredHttp'].append({}),
                       lambda value: value['configuredProviders'].__setitem__(0, value['configuredProviders'][1]),
                       lambda value: value['configuredTransportCallers'][0].update(recoveryScope='foreign'),
                       lambda value: value['configuredHttpCallers'][0].update(service=early.SERVICE)):
            value = copy.deepcopy(hosts())
            # Break aliasing so a changed transport principal cannot silently
            # alter the independently observed HTTP owner in this control.
            value['configuredHttpCallers'] = copy.deepcopy(value['configuredHttpCallers'])
            mutate(value)
            with self.assertRaises(ValueError):
                early.proposals(value, PUBLICATION)

    def test_generic_rejection_platform_error_or_effect_cannot_qualify_typed_fixture(self):
        def result(frame, disposition='rejected', effects=None):
            return {'disposition': disposition, 'effect-ids': effects or [],
                    'result': {'body-base64': base64.b64encode(json.dumps(frame).encode()).decode()}}
        early.typed_denial(result([{'err': 'rejected'}]))
        for value in (result([{'err': 'permission-denied'}]), result([{'ok': None}]),
                      result([{'err': 'rejected'}], 'aborted'),
                      result([{'err': 'rejected'}], effects=['a' * 64])):
            with self.assertRaises(ValueError):
                early.typed_denial(value)

    def test_http_grant_fails_before_first_deployment_mutation(self):
        client = Mock()
        item = SimpleNamespace(name='forbidden-http-before-stage', component_digest='sha256:' + 'a' * 64)
        manifest = {'metadata': {'tenant': cfg.TENANT, 'name': early.DEPLOYMENT},
                    'spec': {'service': early.SERVICE, 'release': item.component_digest,
                             'resources': {'outboundRequests': 0}}}
        with patch.object(early, 'read_json', return_value=manifest), self.assertRaises(ValueError):
            early.metadata(client, Path('/unused'), item, PUBLICATION, [{'capability': policies.HTTP_CONTRACT}])
        client.call.assert_not_called()


if __name__ == '__main__':
    unittest.main()

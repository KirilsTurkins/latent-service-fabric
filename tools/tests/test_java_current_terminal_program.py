"""Closed collector selectors; mocked startup does not qualify a native programme."""
from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import run_java_transaction_http_qualification as runner
from tools.java_transaction_qualification import lifecycle
from tools.phase2_operator_process import write_json


class EnvironmentFixture:
    """Keep the real environment/Node selector while mocking external owners."""

    def __init__(self, root):
        self.root = root
        tls = root / 'input-tls'
        tls.mkdir()
        for name in ('ca.der', 'server.pem', 'key.pem'):
            (tls / name).write_bytes(b'controlled-tls-input')
        self.args = SimpleNamespace(node=root / 'unused-node', signer=root / 'unused-signer',
            aot_compiler=root / 'unused-compiler', current_http_tls=tls)
        self.client = SimpleNamespace(phase4=True, evidence=Mock())
        self.peer = Mock()
        self.configuration = SimpleNamespace(path=root / 'unused-configuration', value={})
        self.endpoint = {'endpointIncarnation': 'controlled-endpoint', 'origin': {'port': 51000}}
        self.preview = b'{"schemaVersion":"latent.configured-http-effect-inspection.v1","adapters":[{"profile":{"idempotency_profile":"controlled-profile"}}]}'

    def prepare(self, program, *, current=True, preview=None, lease_error=None):
        from tools.java_transaction_qualification import current_campaign
        work = self.root / 'work'
        work.mkdir()
        with patch.object(runner, 'current_endpoint', return_value=self.endpoint if current else None), \
             patch.object(runner, 'current_installation', return_value=object()), \
             patch.object(runner, 'native', return_value=self.preview if preview is None else preview), \
             patch.object(runner, 'read_json', return_value={}), \
             patch.object(runner.cfg, 'configure', return_value=self.configuration), \
             patch.object(current_campaign, 'load', return_value=((), None)), \
             patch.object(lifecycle, 'Peer', return_value=self.peer), \
             patch.object(lifecycle, 'Process') as process, \
             patch.object(lifecycle, 'admission_lease_interval', side_effect=lease_error) as lease:
            try:
                result = runner.prepare_environment(self.client, self.args, work, (), node_program=program)
            finally:
                process.assert_not_called()
            self.lease_calls = lease.call_count
            return result


class CurrentHttpTerminalProgram(unittest.TestCase):
    def node(self, root, **selected):
        return lifecycle.Node(SimpleNamespace(phase4=True, environment={}, cancellation=None),
                              root / 'unused-node', root, **selected)

    def original_program(self):
        return ('publish', 'authority', 'namespace-create', 'legacy-runtime',
            'diagnostic-metadata', 'diagnostic-runtime', 'legacy-metadata', 'legacy-after-diagnostic',
            'compatible-metadata', 'compatible-runtime', 'compatible-after-crash',
            'writer-metadata', 'writer-runtime', 'restored-runtime')

    def test_all_default_programs_keep_their_original_bounds_and_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            expected = self.original_program()
            self.assertEqual(lifecycle.CURRENT_NODE_PROGRAM, expected)
            self.assertEqual(lifecycle.CURRENT_METADATA_SESSIONS,
                {'publish', 'authority', 'diagnostic-metadata', 'legacy-metadata',
                 'compatible-metadata', 'writer-metadata'})
            for options, names in [({}, expected), ({'current_publication_program': True}, expected),
                    ({'current_publication_program': True, 'current_program': 'early-http'},
                     ('publish', 'authority', 'namespace-create', 'early-http-runtime')),
                    ({'current_publication_program': True, 'current_program': 'pending-close'},
                     ('publish', 'authority', 'namespace-create', 'legacy-runtime',
                      'pending-original-runtime', 'pending-restored-runtime'))]:
                with self.subTest(options=options):
                    node = self.node(root, **options)
                    self.assertEqual(node.program, names)
                    self.assertIs(node.metadata_sessions, lifecycle.CURRENT_METADATA_SESSIONS)
                    self.assertEqual((node.ordinal, node.restore_authority_sessions), (0, 0))
                    self.assertIsNone(node.process)

    def test_explicit_selection_is_prestart_one_shot_and_adds_only_four_slots(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(lifecycle, 'Process') as process:
            node = self.node(Path(temporary).resolve(), current_publication_program=True)
            node.select_current_http_terminal_program()
            original = self.original_program()
            self.assertEqual(node.program, (*original[:11],
                'cancellation-legacy-metadata', 'cancellation-legacy-runtime',
                'cancellation-compatible-metadata', 'cancellation-compatible-runtime', *original[11:]))
            self.assertEqual(node.metadata_sessions, lifecycle.CURRENT_METADATA_SESSIONS |
                {'cancellation-legacy-metadata', 'cancellation-compatible-metadata'})
            self.assertEqual((node.ordinal, node.restore_authority_sessions), (0, 0))
            self.assertIsNone(node.process)
            with self.assertRaisesRegex(ValueError, 'prestart-current-http-terminal-program'):
                node.select_current_http_terminal_program()
            process.assert_not_called()

    def test_legacy_early_and_pending_cannot_select_terminal_extension(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(lifecycle, 'Process') as process:
            root = Path(temporary).resolve()
            for selected in ({}, {'current_publication_program': True, 'current_program': 'early-http'},
                             {'current_publication_program': True, 'current_program': 'pending-close'}):
                with self.subTest(selected=selected):
                    node = self.node(root, **selected)
                    before = node.program, node.metadata_sessions
                    with self.assertRaisesRegex(ValueError, 'prestart-current-http-terminal-program'):
                        node.select_current_http_terminal_program()
                    self.assertEqual((node.program, node.metadata_sessions), before)
                    self.assertEqual((node.ordinal, node.restore_authority_sessions), (0, 0))
            process.assert_not_called()

    def test_live_started_restoring_and_replaced_programs_refuse_selection(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(lifecycle, 'Process') as process:
            root = Path(temporary).resolve()
            for field, value in [('process', object()), ('ordinal', 1), ('restore_authority_sessions', 1),
                                 ('program', tuple(list(lifecycle.CURRENT_NODE_PROGRAM)))]:
                with self.subTest(field=field):
                    node = self.node(root, current_publication_program=True)
                    setattr(node, field, value)
                    before = node.program, node.metadata_sessions, node.ordinal, node.process, node.restore_authority_sessions
                    with self.assertRaisesRegex(ValueError, 'prestart-current-http-terminal-program'):
                        node.select_current_http_terminal_program()
                    self.assertEqual((node.program, node.metadata_sessions, node.ordinal,
                                      node.process, node.restore_authority_sessions), before)
            process.assert_not_called()

    def test_selector_has_no_untyped_or_external_program_argument(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(lifecycle, 'Process') as process:
            for value in (True, False, 1, None, 'terminal', lifecycle.CURRENT_HTTP_TERMINAL_NODE_PROGRAM):
                with self.subTest(value=type(value).__name__):
                    node = self.node(Path(temporary).resolve(), current_publication_program=True)
                    with self.assertRaises(TypeError):
                        node.select_current_http_terminal_program(value)
                    self.assertIs(node.program, lifecycle.CURRENT_NODE_PROGRAM)
                    self.assertEqual(node.ordinal, 0)
            process.assert_not_called()

    def test_unselected_default_refuses_cancellation_and_keeps_writer_slot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            node = self.node(root, current_publication_program=True)
            node.ordinal = 11
            configuration = root / 'metadata.json'
            write_json(configuration, {'state': {'formatVersion': 2, 'operations': []}})
            with patch.object(lifecycle, 'Process', side_effect=RuntimeError('native-not-created')) as process:
                with self.assertRaisesRegex(ValueError, 'bounded-current-node-session-program'):
                    node.start(configuration, current_session='cancellation-legacy-metadata')
                process.assert_not_called()
                with self.assertRaisesRegex(RuntimeError, 'native-not-created'):
                    node.start(configuration, current_session='writer-metadata')
                self.assertEqual(process.call_count, 1)
                self.assertEqual(node.ordinal, 12)

    def test_selected_program_keeps_restore_authority_at_its_single_final_boundary(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            node = self.node(root, current_publication_program=True)
            node.select_current_http_terminal_program()
            configuration = root / 'restore-authority.json'
            write_json(configuration, {'state': {'formatVersion': 2, 'operations': [], 'createIfMissing': False}})
            with patch.object(lifecycle, 'Process', side_effect=RuntimeError('native-not-created')) as process:
                node.ordinal = 16
                with self.assertRaisesRegex(ValueError, 'current-restore-authority-after-writer-retirement'):
                    node.start(configuration, restore_authority=True)
                process.assert_not_called()
                self.assertEqual(node.restore_authority_sessions, 0)
                node.ordinal = 17
                with self.assertRaisesRegex(RuntimeError, 'native-not-created'):
                    node.start(configuration, restore_authority=True)
                self.assertEqual(node.restore_authority_sessions, 1)
                with self.assertRaises(ValueError):
                    node.start(configuration, restore_authority=True)
                self.assertEqual(process.call_count, 1)
                configuration = root / 'restored-runtime.json'
                write_json(configuration, {'state': {'formatVersion': 2, 'operations': [
                    {'publication': 'original', 'function': function} for function in ('update', 'query', 'scan')]}})
                with self.assertRaisesRegex(RuntimeError, 'native-not-created'):
                    node.start(configuration, current_session='restored-runtime')
                self.assertEqual(process.call_count, 2)
                with self.assertRaises(ValueError):
                    node.start(configuration, current_session='restored-runtime')
                self.assertEqual(process.call_count, 2)

    def test_real_environment_selects_extension_only_for_current_http_terminal(self):
        for program, length in [('terminal', 18), ('early-http', 4), ('pending-close', 6)]:
            with self.subTest(program=program), tempfile.TemporaryDirectory() as temporary:
                fixture = EnvironmentFixture(Path(temporary).resolve())
                peer, configuration, node = fixture.prepare(program)
                self.assertIs(peer, fixture.peer)
                self.assertIs(configuration, fixture.configuration)
                self.assertTrue(node.current_publication_program)
                self.assertEqual(node.current_program, program)
                self.assertEqual(len(node.program), length)
                self.assertEqual((node.ordinal, node.restore_authority_sessions), (0, 0))
                self.assertIsNone(node.process)
                self.assertEqual(fixture.lease_calls, 1)
                fixture.peer.close.assert_not_called()
                if program != 'terminal':
                    with self.assertRaises(ValueError):
                        node.select_current_http_terminal_program()

    def test_real_legacy_environment_keeps_default_without_current_selection(self):
        with tempfile.TemporaryDirectory() as temporary:
            fixture = EnvironmentFixture(Path(temporary).resolve())
            _, _, node = fixture.prepare('terminal', current=False)
            self.assertFalse(node.current_publication_program)
            self.assertEqual(node.program, self.original_program())
            self.assertEqual(fixture.lease_calls, 0)
            self.assertIsNone(node.process)
            with self.assertRaises(ValueError):
                node.select_current_http_terminal_program()

    def test_environment_preview_or_original_lease_failure_cannot_return_selected_node(self):
        for stage in ('preview', 'lease'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as temporary:
                fixture = EnvironmentFixture(Path(temporary).resolve())
                with patch.object(lifecycle.Node, 'select_current_http_terminal_program') as select:
                    with self.assertRaises(ValueError):
                        fixture.prepare('terminal', preview=b'{}' if stage == 'preview' else None,
                            lease_error=ValueError('original-lease-refusal') if stage == 'lease' else None)
                    select.assert_not_called()
                fixture.peer.close.assert_called_once_with()

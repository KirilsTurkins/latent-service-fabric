"""Controls for the signed combined witness's explicit capability custody."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import rust_thread_http_combined_node as node
from tools.phase2_operator_process import WorkflowError


def descriptors():
    return [{'id': identity, 'capability': capability, 'tenant': 'examples',
             'profile': profile, 'configurationEpoch': '1', 'configurationDigest': 'sha256:' + '1' * 64}
            for identity, capability, _ops, profile, _kind in node.PROVIDERS]


class CombinedGrantControls(unittest.TestCase):
    def test_only_diagnostic_source_verifier_build_is_optimized(self):
        from unittest.mock import Mock
        from tools import qualify_rust_thread_http_combined as qualification

        commands = Mock()
        qualification.build_native(commands)
        commands.run.assert_called_once()
        argv = commands.run.call_args.args
        self.assertEqual(argv[:2], ('build-current-feature-selected-host', 'cargo'))
        configurations = [argv[index + 1] for index, word in enumerate(argv) if word == '--config']
        self.assertEqual(configurations, [qualification.ROOT / '.cargo/managed-guest.toml',
                         'profile.dev.package.latent-component-threading.opt-level=3'])
        self.assertIn('--locked', argv)
        self.assertNotIn('--release', argv)
        self.assertEqual(argv[argv.index('--features') + 1],
                         'latentd/development-rust-http-combined,latent-packaging/development-rust-http-combined')

    def test_transport_wait_is_separate_from_the_original_guest_budget(self):
        import json
        from pathlib import Path
        import tempfile
        import time
        from tools import rust_capsule_node as calls

        budget = {'outboundRequests': 8, 'memoryBytes': 16_777_216,
                  'cpuFuel': 1_000_000_000, 'wallTimeLimitMillis': 5000}
        target = {'name': 'combined', 'service': 'my-greeting', 'budget': budget}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            client = node.witness_client('latent', root, object(), time.monotonic() + 300,
                                         root / 'evidence')
            ordinary = calls.RecordingClient('latent', root, object(), client.deadline,
                                             evidence=root / 'ordinary-evidence')
            self.assertEqual(ordinary.invocation_timeout_millis, 5000)
            self.assertEqual(client.invocation_timeout_millis, 120_000)
            self.assertEqual(client.control_timeout_millis, ordinary.control_timeout_millis)
            process = SimpleNamespace()
            with patch.object(calls, 'Process', return_value=process) as launch:
                self.assertIs(calls.start_call(client, target, 'greeting', 'greet',
                                               ['thread-http|http://127.0.0.1:1234'], 'bounded'), process)
            argv = launch.call_args.args[0]
            self.assertEqual(argv[argv.index('--rpc-timeout-ms') + 1], '120000')
            self.assertEqual(json.loads((root / 'bounded-budget.json').read_bytes()), budget)
            self.assertEqual(target['budget']['wallTimeLimitMillis'], 5000)
            launch.assert_called_once()

    def test_shared_provider_identity_still_requires_four_distinct_capabilities(self):
        observed = []
        peer = SimpleNamespace(origin=lambda role: {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234})
        owner = SimpleNamespace(startup_record={'providers': descriptors()})
        with patch.object(node, 'policy', side_effect=lambda *args: observed.append(args)):
            grants = node.grant(object(), owner, 'signed-publication', peer)
        self.assertEqual({row['capability'] for row in grants}, set(node.IMPORTS))
        self.assertEqual(len(observed), 8)
        native = [args for args in observed if args[2] == 'native-examples-allow']
        self.assertEqual(len(native), 1)
        self.assertEqual(native[0][3]['rules'][0]['operations'], ['start'])
        self.assertEqual(native[0][3]['rules'][0]['resources'], {'kind': 'context'})

    def test_missing_native_descriptor_refuses_before_any_policy_write(self):
        owner = SimpleNamespace(startup_record={'providers': descriptors()[:-2] + descriptors()[-1:]})
        peer = SimpleNamespace(origin=lambda role: None)
        with patch.object(node, 'policy') as mutation:
            with self.assertRaises(WorkflowError):
                node.grant(object(), owner, 'signed-publication', peer)
        mutation.assert_not_called()


    def test_failed_sibling_order_retains_the_actual_terminal_result(self):
        import json
        from pathlib import Path
        import tempfile
        import time
        from tools import rust_thread_http_sibling_node as sibling
        digest = 'sha256:' + '2' * 64
        target = {'budget': {'outboundRequests': 8, 'memoryBytes': 16_777_216,
                             'cpuFuel': 1_000_000_000, 'wallTimeLimitMillis': 5000}}
        peer = SimpleNamespace(gates=lambda: [], observation=lambda: {'acceptedConnections': 0},
                               origin=lambda: {'scheme': 'http', 'host': '127.0.0.1', 'port': 1234})
        process = SimpleNamespace(owner=SimpleNamespace(exited=lambda: True), close=lambda: None)
        terminal = {'exitCode': 4, 'decoded': None, 'processReaped': True,
                    'response': {'category': 'platform-failure'}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sibling, 'selected_revision', return_value={'releaseDigest': digest}), \
                patch.object(sibling, 'start_call', return_value=process), \
                patch.object(sibling, 'finish_call', return_value=terminal):
            with self.assertRaises(WorkflowError):
                sibling.invoke(SimpleNamespace(deadline=time.monotonic() + 10), object(), target,
                               peer, object(), Path(directory), digest)
            retained = json.loads((Path(directory) / 'rust-thread-http-terminal.json').read_bytes())
            self.assertEqual(retained, terminal)


if __name__ == '__main__':
    unittest.main()

"""Restart waits for the original durable floor without retrying failed startup."""
from pathlib import Path
import json
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import go_node_stop_restart as restart


class GoNodeStopRestartTests(unittest.TestCase):
    def fixture(self, root, **values):
        path = root / 'data/supply-chain/floor.json'
        path.parent.mkdir(parents=True)
        raw = json.dumps({'formatVersion': 1, 'epoch': 7, 'restartNotBefore': 104,
                         'policy': {'privatePolicyData': 'not-projected'}, **values}).encode()
        path.write_bytes(raw)
        return path, raw

    def test_existing_future_floor_must_elapse_before_the_single_native_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);path, raw = self.fixture(root)
            client = SimpleNamespace(deadline=200.0)
            seen = []
            node = object()
            def connect(actual, *args, **kwargs):
                seen.append('connect')
                self.assertEqual(len(pauses), 2)
                self.assertEqual(actual.deadline, 40.0)
                self.assertEqual(kwargs['startup_timeout'], 29)
                return node
            pauses = []
            with patch.object(restart.time, 'monotonic', side_effect=[10., 10., 10., 10.1]), \
                    patch.object(restart.time, 'time_ns', side_effect=[102000000000, 103000000000, 104000000000]), \
                    patch.object(restart.time, 'sleep', side_effect=pauses.append), \
                    patch.object(restart, 'connect', side_effect=connect):
                actual, record = restart.restart(client, 'latentd', root, root / 'node.json', 'examples', 2, root / 'receipt.json')
            self.assertIs(actual, node)
            self.assertEqual(pauses, [0.025, 0.025])
            self.assertEqual(seen, ['connect'])
            self.assertTrue(record['waitRequired'])
            self.assertEqual(record['readyAtUnixSeconds'], 104)
            self.assertEqual(record['startupAttempts'], 1)
            self.assertEqual(client.deadline, 200.)
            self.assertEqual(path.read_bytes(), raw)
            self.assertNotIn('privatePolicyData', json.dumps(record))

    def test_already_elapsed_floor_does_not_sleep_and_native_failure_is_not_retried(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);self.fixture(root)
            client = SimpleNamespace(deadline=25.0)
            original = RuntimeError('fixed-native-startup-failure')
            with patch.object(restart.time, 'monotonic', return_value=10.), \
                    patch.object(restart.time, 'time_ns', return_value=104000000000), \
                    patch.object(restart.time, 'sleep') as sleep, \
                    patch.object(restart, 'connect', side_effect=original) as connect:
                with self.assertRaises(RuntimeError) as failed:
                    restart.restart(client, 'latentd', root, root / 'node.json', 'examples', 2, root / 'receipt.json')
            self.assertIs(failed.exception, original)
            sleep.assert_not_called();connect.assert_called_once()
            self.assertEqual(client.deadline, 25.)
            self.assertEqual(json.loads((root / 'receipt.json').read_bytes())['status'], 'failed')

    def test_malformed_duplicate_bool_missing_and_unbounded_floors_never_spawn(self):
        for value in ({'epoch': True}, {'restartNotBefore': '104'}, {'restartNotBefore': 108},
                      {'extraPrivate': 'secret'}, {'epoch': 0}, {'formatVersion': True}):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary);self.fixture(root, **value)
                client = SimpleNamespace(deadline=50.)
                with patch.object(restart.time, 'monotonic', return_value=10.), \
                        patch.object(restart.time, 'time_ns', return_value=102000000000), \
                        patch.object(restart, 'connect') as connect, self.assertRaises(RuntimeError):
                    restart.restart(client, 'latentd', root, root / 'node.json', 'examples', 2, root / 'receipt.json')
                connect.assert_not_called()
        for raw in (b'{}', b'{"epoch":1,"epoch":2}', b'x' * 4097):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary);path, _ = self.fixture(root);path.write_bytes(raw)
                client = SimpleNamespace(deadline=50.)
                with patch.object(restart.time, 'monotonic', return_value=10.), \
                        patch.object(restart, 'connect') as connect, self.assertRaises((RuntimeError, ValueError)):
                    restart.restart(client, 'latentd', root, root / 'node.json', 'examples', 2, root / 'receipt.json')
                connect.assert_not_called()

    def test_original_deadline_clock_regression_and_floor_replacement_never_launch(self):
        for reason in ('deadline', 'regression', 'replacement'):
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary);path, _ = self.fixture(root)
                client = SimpleNamespace(deadline=10.1)
                times = [10., 11.] if reason == 'deadline' else [10., 10.]
                clocks = [102000000000, 101000000000] if reason == 'regression' else [102000000000, 104000000000]
                def pause(_):
                    if reason == 'replacement':
                        path.write_bytes(b'{}')
                with patch.object(restart.time, 'monotonic', side_effect=times), \
                        patch.object(restart.time, 'time_ns', side_effect=clocks), \
                        patch.object(restart.time, 'sleep', side_effect=pause), \
                        patch.object(restart, 'connect') as connect, self.assertRaises(RuntimeError):
                    restart.restart(client, 'latentd', root, root / 'node.json', 'examples', 2, root / 'receipt.json')
                connect.assert_not_called()
                self.assertEqual(client.deadline, 10.1)

    def test_failure_to_retain_start_evidence_closes_the_still_owned_new_node(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);self.fixture(root)
            node = SimpleNamespace(close=Mock())
            client = SimpleNamespace(deadline=50., node=node)
            with patch.object(restart.time, 'monotonic', return_value=10.), \
                    patch.object(restart.time, 'time_ns', return_value=104000000000), \
                    patch.object(restart, 'connect', return_value=node), \
                    patch.object(restart, 'write_json', side_effect=OSError('fixture-io-failure')), \
                    self.assertRaises(OSError):
                restart.restart(client, 'latentd', root, root / 'node.json', 'examples', 2, root / 'receipt.json')
            node.close.assert_called_once();self.assertIsNone(client.node)
            self.assertEqual(client.deadline, 50.)


if __name__ == '__main__':
    unittest.main()

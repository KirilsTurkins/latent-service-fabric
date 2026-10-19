from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools import qualify_java_published_http as campaign
from tools import replay_java_published_http as replay
from tools.phase2_operator_process import WorkflowError
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import read_json


class PublishedJavaReplay(unittest.TestCase):
    def test_actual_campaign_passthrough_keeps_native_history_separate(self):
        self.assertIs(replay.execute, campaign.execute)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            (source / 'tools').mkdir(parents=True)
            for name in ('java_replay_materials.py', 'replay_java_published_http.py'):
                (source / 'tools' / name).write_bytes(b'controlled source identity')
            binaries = {}
            for name in campaign.PRODUCTS:
                path = root / name
                path.write_bytes(name.encode())
                binaries[name] = path
            products = {name: file_identity(path) for name, path in binaries.items()}
            history = {'compiledSource': 'historical source', 'currentDevelopmentNativeCompilationClaimed': False}
            def execute(commands, selected, sdk, output):
                self.assertEqual(selected, binaries)
                self.assertEqual(sdk, root / 'tools')
                return {'status': 'passed', 'publishedClientInvocations': 26, 'nativeProducts': products}
            with mock.patch.object(replay, 'ROOT', source), \
                    mock.patch.object(replay.sys, 'platform', 'linux'), \
                    mock.patch.object(replay, 'verify_prepared', return_value=history) as verify, \
                    mock.patch.object(replay, 'native_products', return_value=binaries), \
                    mock.patch.object(replay, 'Commands'), \
                    mock.patch.object(replay, 'execute', side_effect=execute), \
                    mock.patch.object(replay.subprocess, 'check_output', return_value='a' * 40 + '\n'):
                result = replay.run(root / 'output', root / 'prepared', root / 'tools')
            self.assertEqual(verify.call_count, 2)
            self.assertEqual(result['nativeSource'], history)
            self.assertFalse(result['nativeRecompiled'])
            self.assertFalse(result['productionNativeTupleRecreated'])
            self.assertEqual(result['fixtureSource'], 'a' * 40)
            self.assertEqual(result, read_json(root / 'output/qualification.json'))

    def test_product_change_after_campaign_refuses_before_success_receipt(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            (source / 'tools').mkdir(parents=True)
            for name in ('java_replay_materials.py', 'replay_java_published_http.py'):
                (source / 'tools' / name).write_bytes(b'controlled source identity')
            binary = root / 'host'
            binary.write_bytes(b'original host')
            def execute(*args):
                before = file_identity(binary)
                binary.write_bytes(b'changed host')
                return {'status': 'passed', 'publishedClientInvocations': 26,
                        'nativeProducts': {'latentd': before}}
            with mock.patch.object(replay, 'ROOT', source), \
                    mock.patch.object(replay.sys, 'platform', 'linux'), \
                    mock.patch.object(replay, 'verify_prepared', return_value={'fixed': True}), \
                    mock.patch.object(replay, 'native_products', return_value={'latentd': binary}), \
                    mock.patch.object(replay, 'Commands'), \
                    mock.patch.object(replay, 'execute', side_effect=execute):
                with self.assertRaisesRegex(WorkflowError, 'final-material-drift'):
                    replay.run(root / 'output', root / 'prepared', root / 'tools')
            self.assertFalse((root / 'output/qualification.json').exists())
            failed = read_json(root / 'output/FAILED.json')
            self.assertEqual(failed['status'], 'failed')
            self.assertFalse(failed['nativeRecompiled'])

    def test_observer_failure_preserves_original_campaign_exception(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            (source / 'tools').mkdir(parents=True)
            for name in ('java_replay_materials.py', 'replay_java_published_http.py'):
                (source / 'tools' / name).write_bytes(b'controlled source identity')
            original = RuntimeError('original controlled failure')
            with mock.patch.object(replay, 'ROOT', source), \
                    mock.patch.object(replay.sys, 'platform', 'linux'), \
                    mock.patch.object(replay, 'verify_prepared', return_value={'fixed': True}), \
                    mock.patch.object(replay, 'native_products', return_value={}), \
                    mock.patch.object(replay, 'Commands'), \
                    mock.patch.object(replay, 'execute', side_effect=original), \
                    mock.patch.object(replay, 'write_json', side_effect=RecursionError('observer failed')):
                with self.assertRaises(RuntimeError) as raised:
                    replay.run(root / 'output', root / 'prepared', root / 'tools')
            self.assertIs(raised.exception, original)


if __name__ == '__main__':
    unittest.main()

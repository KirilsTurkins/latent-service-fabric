"""Finite source controls for the combined HTTP/ThreadPool compiler diagnostic."""
import copy
import unittest

from tools import compile_rust_thread_http_sibling as candidate

PUBLIC = 'examples:greeting/api@1.0.0#greet'


def graph():
    return {'packages': [{'name': 'examples:greeting@1.0.0'}],
        'worlds': [{'name': 'service', 'package': 0,
                    'exports': {'api': {'interface': {'id': 0}}}}],
        'interfaces': [{'name': 'api', 'package': 0,
                        'functions': {'greet': {'name': 'greet',
                            'kind': 'async-freestanding', 'result': 0}}}],
        'types': [{'kind': {'result': {'ok': 'string', 'err': 'string'}}}]}


class CombinedCompilerWit(unittest.TestCase):
    def test_exact_async_result_is_checked_without_mutating_contract(self):
        value = graph(); original = copy.deepcopy(value)
        self.assertEqual(candidate.select_http_result(value, 'service', PUBLIC),
                         {'result': {'ok': 'string', 'err': 'string'}})
        self.assertEqual(value, original)

    def test_sync_foreign_or_ambiguous_interfaces_refuse(self):
        value = graph(); value['interfaces'][0]['functions']['greet']['kind'] = 'freestanding'
        with self.assertRaises(ValueError):
            candidate.select_http_result(value, 'service', PUBLIC)
        value = graph()
        with self.assertRaises(ValueError):
            candidate.select_http_result(value, 'service', 'examples:other/api@1.0.0#greet')
        value['interfaces'].append(copy.deepcopy(value['interfaces'][0]))
        with self.assertRaises(ValueError):
            candidate.select_http_result(value, 'service', PUBLIC)

    def test_wrong_result_type_and_oversized_interface_set_refuse(self):
        value = graph(); value['types'][0]['kind']['result']['ok'] = 'u32'
        with self.assertRaises(ValueError):
            candidate.select_http_result(value, 'service', PUBLIC)
        value = graph(); value['interfaces'] *= 4097
        with self.assertRaises(ValueError):
            candidate.select_http_result(value, 'service', PUBLIC)

    def test_unrelated_unowned_interface_does_not_change_exact_match(self):
        value = graph(); value['interfaces'].append({'name': 'foreign', 'package': None, 'functions': {}})
        self.assertEqual(candidate.select_http_result(value, 'service', PUBLIC),
                         {'result': {'ok': 'string', 'err': 'string'}})


class CombinedCompilerSourceReceipt(unittest.TestCase):
    def test_git_recipe_binds_the_clean_expected_head_and_exact_bytes(self):
        from unittest.mock import patch
        head = 'a' * 40
        files = {'tools/example.py': b'original'}
        def git(*args, input=None):
            if args == ('rev-parse', '--verify', 'HEAD'):
                return (head + '\n').encode()
            if args == ('status', '--porcelain=v1', '--untracked-files=no'):
                return b''
            if args == ('rev-parse', 'HEAD^{tree}'):
                return ('b' * 40 + '\n').encode()
            if args == ('cat-file', '--batch'):
                self.assertEqual(input, (head + ':tools/example.py\n').encode())
                return (b'c' * 40 + b' blob 8\noriginal\n')
            raise AssertionError(args)
        with patch.object(candidate, 'git_read', side_effect=git):
            result = candidate.bind_recipe_to_git(head, files)
            self.assertEqual(result['head'], head)
            self.assertEqual(result['files'][0]['size'], 8)
            with self.assertRaises(ValueError):
                candidate.bind_recipe_to_git(head, {'tools/example.py': b'changed!'})
            with self.assertRaises(ValueError):
                candidate.bind_recipe_to_git('not-a-head', files)

    def test_git_recipe_rejects_dirty_checkout_and_truncated_blob(self):
        from unittest.mock import patch
        head = 'a' * 40
        def dirty(*args, input=None):
            return (head + '\n').encode() if args[0] == 'rev-parse' else b' M source\n'
        with patch.object(candidate, 'git_read', side_effect=dirty):
            with self.assertRaises(ValueError):
                candidate.bind_recipe_to_git(head, {'tools/example.py': b'original'})
        def truncated(*args, input=None):
            if args == ('rev-parse', '--verify', 'HEAD'):
                return (head + '\n').encode()
            if args[0] == 'status': return b''
            return b'c' * 40 + b' blob 8\norig'
        with patch.object(candidate, 'git_read', side_effect=truncated):
            with self.assertRaises(ValueError):
                candidate.bind_recipe_to_git(head, {'tools/example.py': b'original'})

    def test_contract_tool_receipt_requires_same_head_and_exact_binary(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        head = 'a' * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); tool = root / 'tool'; tool.write_bytes(b'contract-tool')
            receipt = {'schemaVersion': 'latent.rust.http-thread.contract-tool.v1',
                'status': 'passed-current-contracts-tool', 'head': head, 'source': {'head': head},
                'actualGuestExecuted': False, 'hostQualified': False,
                'tool': {'name': 'contracts-tool', 'digest': 'sha256:' + hashlib.sha256(tool.read_bytes()).hexdigest(),
                         'size': tool.stat().st_size},
                'commands': [{'stage': 'current-contracts-build', 'exitCode': 0}]}
            path = root / 'receipt.json'; path.write_text(json.dumps(receipt))
            self.assertEqual(candidate.verify_contract_tool(path, tool, head), path.read_bytes())
            tool.write_bytes(b'contract-TAMPER')
            with self.assertRaises(ValueError): candidate.verify_contract_tool(path, tool, head)
            tool.write_bytes(b'contract-tool')
            with self.assertRaises(ValueError): candidate.verify_contract_tool(path, tool, 'b' * 40)


    def test_owned_tool_and_sysroot_must_match_same_head_producer(self):
        import hashlib
        import json
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        head = 'a' * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); tool = root / 'context'; tool.write_bytes(b'context-tool')
            identity = {'name': 'rust-context', 'digest': 'sha256:' + hashlib.sha256(tool.read_bytes()).hexdigest(),
                        'size': tool.stat().st_size}
            report = {'schemaVersion': 'latent.rust.owned-thread-inputs.v1',
                'status': 'passed-compiler-inputs-only', 'sourceMatchedContextToolBuilt': True,
                'ownedThreadSysrootBuilt': True, 'actualGuestExecuted': False,
                'ordinaryThreadPoolQualified': False, 'contextTool': identity, 'sysrootIdentity': 'sysroot-id'}
            report_path = root / 'report.json'; report_path.write_text(json.dumps(report))
            source_path = root / 'source.json'; source_path.write_text(json.dumps({'head': head}))
            prepared = SimpleNamespace(value={'identity': 'sysroot-id'})
            candidate.verify_owned_inputs(report_path, source_path, prepared, tool, head)
            tool.write_bytes(b'context-bad!')
            with self.assertRaises(ValueError):
                candidate.verify_owned_inputs(report_path, source_path, prepared, tool, head)
            tool.write_bytes(b'context-tool')
            with self.assertRaises(ValueError):
                candidate.verify_owned_inputs(report_path, source_path, prepared, tool, 'b' * 40)
            prepared.value['identity'] = 'wrong'
            with self.assertRaises(ValueError):
                candidate.verify_owned_inputs(report_path, source_path, prepared, tool, head)


if __name__ == '__main__':
    unittest.main()

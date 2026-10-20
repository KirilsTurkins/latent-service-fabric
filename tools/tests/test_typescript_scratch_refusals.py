"""Only the actual captured bundle's closed node:fs diagnostic proves refusal."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from tools import qualify_typescript_scratch_refusals as qualifier
from tools.rust_capsule_project import write_json


def failure(root, *, stage='compile', command='bundle', marker=None):
    write_json(root/'BUILD-FAILED.json', {'formatVersion': 1, 'stage': stage,
        'commands': [{'stage': 'inspect-wit', 'exitCode': 0, 'seconds': 0.1},
            {'stage': command, 'exitCode': 1, 'seconds': 0.2}]})
    (root/'logs').mkdir()
    (root/'logs/01-bundle.stderr.txt').write_bytes(qualifier.MARKER if marker is None else marker)
    return SimpleNamespace(returncode=1, stdout=b'', stderr=b'bounded compiler failure')


class TypeScriptScratchRefusals(unittest.TestCase):
    def test_real_bundle_refusal_does_not_claim_a_node_runtime_or_signed_component(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            observed = qualifier.observed(root, failure(root))
            self.assertEqual(observed['module'], 'node:fs')
            self.assertEqual(observed['boundary'], 'captured-reachable-bundle-import')
            self.assertFalse(observed['runtimeFilesystemExecutionClaimed'])
            self.assertFalse(observed['rawDiagnosticsPublished'])

    def test_capture_setup_generic_trap_and_wrong_profile_do_not_count_as_filesystem_refusal(self):
        for kwargs in ({'stage': 'capture'}, {'command': 'componentize'},
                {'marker': b'unreachable-code'}, {'marker': b'standard-runtime-module-not-installed:node:os:spidermonkey-public-sync-v1'},
                {'marker': b'standard-runtime-module-not-installed:node:fs:other-profile'}):
            with self.subTest(kwargs=kwargs), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                with self.assertRaisesRegex(RuntimeError, 'scratch-typescript-'):
                    qualifier.observed(root, failure(root, **kwargs))

    def test_success_component_or_uncompleted_compiler_refuses(self):
        for changed in ('component.wasm', 'BUILD-COMPLETE.json', 'package', 'returncode'):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                completed = failure(root)
                if changed == 'returncode': completed.returncode = -9
                elif changed == 'package': (root/changed).mkdir()
                else: (root/changed).write_bytes(b'unexpected successful compiler output')
                with self.assertRaisesRegex(RuntimeError, 'scratch-typescript-'):
                    qualifier.observed(root, completed)


if __name__ == '__main__': unittest.main()

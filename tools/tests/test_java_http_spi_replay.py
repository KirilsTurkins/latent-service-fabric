"""Fixed-artifact refusal controls; modeled nodes never qualify SPI execution."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import replay_java_http_spi as replay
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import write_json


class JavaSpiPreparedReplay(unittest.TestCase):
    def test_different_archive_refuses_before_creating_any_retained_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)/'build'
            with self.assertRaisesRegex(WorkflowError, 'whole-archive-identity'):
                replay.extract(b'not-the-authenticated-e1c-archive', output)
            self.assertFalse(output.exists())

    def test_fixed_pin_set_refuses_escape_alias_nonregular_and_unbounded_shapes(self):
        good = {str(i): {'bytes': 1, 'sha256': 'sha256:'+'1'*64} for i in range(55)}
        for name in ('../escape', '/absolute', 'a/../b', 'a\\b', './alias'):
            with self.subTest(name=name), self.assertRaises(WorkflowError): replay.safe(name)
        for rows in ({}, {**good, '0': {'bytes': True}},
                {**good, '0': {'bytes': 64*1024**2+1}}):
            with patch.object(replay, 'read_json', return_value=rows), self.assertRaises(WorkflowError):
                replay.pins()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'component.wasm').mkdir()
            with patch.object(replay, 'pins', return_value={'component.wasm': good['0']}), \
                    patch.object(replay, 'source_proof') as source:
                with self.assertRaises(WorkflowError): replay.validate_build(root)
                source.assert_not_called()

    def test_changed_retained_component_refuses_before_reading_original_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);(root/'component.wasm').write_bytes(b'changed')
            with patch.object(replay, 'pins', return_value={'component.wasm': {
                    'sha256': 'sha256:'+'1'*64, 'bytes': 7}}), \
                    patch.object(replay, 'read_json') as original:
                with self.assertRaisesRegex(WorkflowError, 'retained-identity'):
                    replay.validate_build(root)
                original.assert_not_called()

    def test_incomplete_cases_and_post_execution_material_changes_cannot_publish_success(self):
        for incomplete, changed in ((True, False), (False, True)):
            with self.subTest(incomplete=incomplete, changed=changed), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary);prepared = root/'prepared';prepared.mkdir()
                proof = {'original': 'bound'}
                write_json(prepared/'retrieval.json', {'artifact': replay.ARTIFACT, 'build': proof})
                (root/'tools/fixtures').mkdir(parents=True)
                (root/replay.PINS).write_bytes(b'fixed pin preimage')
                (root/'tools/replay_java_http_spi.py').write_bytes(b'fixed reader preimage')
                result = {'status': 'passed', 'cases': [0]*6, 'invocations': 6,
                    'authorityDenials': 2, 'httpContacts': 3 if incomplete else 4}
                def node(*args, **kwargs):
                    if changed: (root/replay.PINS).write_bytes(b'tampered after node')
                    return result
                with patch.object(replay, 'ROOT', root), patch.object(replay, 'MATERIALS', ()), \
                        patch.object(replay, 'validate_build', return_value=proof), \
                        patch.object(replay, 'verify_prepared', return_value={'frozen': True}), \
                        patch.object(replay, 'native_source', return_value={'source': 'frozen'}), \
                        patch.object(replay, 'native_products', return_value={n:root/n for n in
                            ('latent', 'latentd', 'capsule_authoring')}), \
                        patch.object(replay, 'node_controls', side_effect=node):
                    with self.assertRaisesRegex(WorkflowError,
                            'incomplete-programme' if incomplete else 'final-source-or-products-drift'):
                        replay.run(root/'output', prepared, root/'native')
                self.assertFalse((root/'output/qualification.json').exists())

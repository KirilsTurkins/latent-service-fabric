"""The current C programme requires the full corrected128 native source."""
import copy
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import qualify_c_thread_runtime as qualification
from tools import host_codec_owned_reply_native_products as native
from tools import c_thread_linear_memory_native_source as historical
from tools.phase2_operator_process import WorkflowError

COMPILED = {'sha256': 'sha256:57443f6f4c0005e9320914e11ccc0219f34349c6312c803584a609aa90f14adf',
    'files': 3628, 'bytes': 31584586,
    'scope': 'explicit-apps-crates-rust-sdk-workloads-and-workspace-inputs',
    'hermetic': False, 'implicitCompilerInputs': 'not-attested'}


class CThreadOwnedReplyRuntime(unittest.TestCase):
    def test_explicit128_requires_whole_source_equality_and_never_uses_old114_fixture_projection(self):
        for current in (COMPILED, historical.CORRECTED):
            with patch.object(qualification, 'git_source_identity', return_value=COMPILED) as compiled, \
                    patch.object(qualification, 'source_identity', return_value=current), \
                    patch.object(historical, 'assert_current', side_effect=AssertionError('old114-route')) as old:
                if current == COMPILED:
                    proof = qualification.assert_current(qualification.ROOT, native)
                    self.assertEqual(proof['compiledSourceRevision'], native.SOURCE)
                    self.assertEqual(proof['compiledNativeSource'], COMPILED)
                    self.assertEqual(proof['consumerNativeSource'], COMPILED)
                    self.assertIs(proof['compiledSourceByteExact'], True)
                    self.assertEqual(proof['reviewedSourceChanges'], [])
                else:
                    with self.assertRaises(WorkflowError):
                        qualification.assert_current(qualification.ROOT, native)
                compiled.assert_called_once_with(native.SOURCE)
                old.assert_not_called()
        for field in COMPILED:
            bad = copy.deepcopy(COMPILED)
            bad[field] = True if type(bad[field]) is int else 'foreign'
            with self.subTest(field=field), \
                    patch.object(qualification, 'git_source_identity', return_value=COMPILED), \
                    patch.object(qualification, 'source_identity', return_value=bad), self.assertRaises(WorkflowError):
                qualification.assert_current(qualification.ROOT, native)

    def test_native_admission_refuses_changed_materials_source_or_missing_product_before_tool_use(self):
        identity = {'sha256': 'sha256:' + '1' * 64, 'bytes': 1}
        materials = {'wit/controlled/' + str(n) + '.wit': identity for n in range(148)}
        products = {name: identity for name in ('latent', 'latentd', 'examples/package',
            'examples/capsule_contracts', 'examples/capsule_authoring')}
        original = {'native': COMPILED, 'materials': materials}
        proof = {'compiledSourceRevision': native.SOURCE, 'compiledNativeSource': COMPILED,
            'consumerNativeSource': COMPILED, 'compiledSourceByteExact': True, 'reviewedSourceChanges': []}
        for mutation in (None, 'old-source', 'missing-product', 'snapshot-source', 'old134', 'material'):
            snapshot = copy.deepcopy(original)
            receipt = {'compiledSource': native.SOURCE, 'products': copy.deepcopy(products)}
            if mutation == 'old-source': receipt['compiledSource'] = historical.SOURCE
            elif mutation == 'missing-product': receipt['products'].pop('latent')
            elif mutation == 'snapshot-source': snapshot['native'] = historical.COMPILED
            elif mutation == 'old134': snapshot['materials'] = dict(list(materials.items())[:134])
            owner = SimpleNamespace(SOURCE=native.SOURCE,
                verify_prepared=Mock(return_value=receipt), native_products=Mock(return_value={'tools': 'not-executed'}))
            def current_identity(path):
                return dict(identity, bytes=2) if mutation == 'material' else identity
            with self.subTest(mutation=mutation), \
                    patch.object(qualification, 'assert_current', return_value=copy.deepcopy(proof)), \
                    patch.object(qualification, 'read_json', return_value=snapshot), \
                    patch.object(qualification, 'file_identity', side_effect=current_identity):
                if mutation is None:
                    before, source, tools = qualification.native_evidence(owner, Path('controlled'))
                    self.assertEqual(source['auxiliaryMaterialsByteExact'], 148)
                    self.assertEqual(source['perProductCompilation'], {name: {
                        'sourceRevision': native.SOURCE, 'nativeSource': COMPILED, 'identity': identity}
                        for name in products})
                    self.assertEqual(before, receipt)
                    self.assertEqual(tools, {'tools': 'not-executed'})
                    owner.native_products.assert_called_once_with(Path('controlled'))
                else:
                    with self.assertRaises(WorkflowError):
                        qualification.native_evidence(owner, Path('controlled'))
                    owner.native_products.assert_not_called()


if __name__ == '__main__':
    unittest.main()

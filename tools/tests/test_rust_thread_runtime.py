"""Consumer replay/policy refusals; no native or captured guest execution."""
import copy
import unittest

from tools import rust_thread_runtime_node as node, rust_thread_runtime_package as package
from tools.rust_capsule_project import ROOT, digest
from tools.phase2_operator_process import WorkflowError


class RustThreadRuntimeTests(unittest.TestCase):
    def test_native_reader_uses_current_catalogue_and_retains_failed_runtime_origin(self):
        from tools import rust_thread_native_products as native

        self.assertEqual(native.SOURCE, '9c0097fc4dee24c57e0cffbdf1963e47772b2ffc')
        self.assertEqual(native.RUN, 41116286833)
        self.assertEqual(native.ARTIFACT['id'], 13008060664)
        self.assertEqual(native.FAILED_RUNTIME_SOURCE,
                         '79911762b366381d7dc61da12d1b5e9aba2b3222')
        self.assertEqual(native.FAILED_RUNTIME_RUN, 41096399674)
        self.assertNotEqual(native.ARTIFACT, native.FAILED_RUNTIME_ARTIFACT)
        workflow = (ROOT / '.github/workflows/rust-thread-runtime.yml').read_text()
        self.assertIn('git fetch --no-tags --depth=1 origin ' + native.SOURCE, workflow)
        self.assertNotIn('git fetch --no-tags --depth=1 origin ' + native.FAILED_RUNTIME_SOURCE,
                         workflow)

    def test_retained_original_pair_refuses_foreign_core_envelope_and_double_framing(self):
        self.assertEqual(package.PREVIOUS_PINS['raw-core.wasm'],
                         package.HISTORICAL_PINS['raw-core.wasm'])
        self.assertEqual(package.LATEST_PREVIOUS_PINS['raw-core.wasm'],
                         (262561, '1016bc74d96585be6943d2b1396cf79ebd8f1fa66828a321d2ee251827431bcc'))
        self.assertNotEqual(package.PINS['raw-core.wasm'], package.PREVIOUS_PINS['raw-core.wasm'])
        self.assertNotEqual(package.PINS['raw-core.wasm'], package.LATEST_PREVIOUS_PINS['raw-core.wasm'])
        self.assertNotEqual(package.PINS['source-inputs.json'], package.PREVIOUS_PINS['source-inputs.json'])
        base = ROOT / 'crates/latent-component-threading/src/rust_catalogue'
        original = (base / 'reviewed-original-core.wasm').read_bytes()
        component = (base / 'reviewed-normal-component.wasm').read_bytes()
        framed = package.wrap_original(original, component)
        self.assertEqual(package.WRAPPED, {'bytes': len(framed), 'sha256': digest(framed)})
        self.assertTrue(framed.startswith(component))
        for old, normal in ((original[:-1] + bytes([original[-1] ^ 1]), component),
                            (original, component[:-1] + bytes([component[-1] ^ 1])),
                            (original, framed), (b'', component)):
            with self.subTest(original=len(old), component=len(normal)):
                with self.assertRaisesRegex(WorkflowError, 'rust-thread-original-component-pair'):
                    package.wrap_original(old, normal)

    def test_explicit_rust_policy_keeps_four_imports_and_refuses_implicit_budget_or_layout(self):
        settings = {'workers': {'runtime': 1, 'control': 1},
            'cells': [{'capacity': 1, 'queueCapacity': 2, 'maximumMemoryBytes': 33554432}],
            'providers': {'bindings': [{'name': 'existing-http'}]}}
        capsule = {'imports': [{'contract': name, 'optional': False} for name in package.IMPORTS],
            'execution': {'threading': 'cooperative',
                'limits': {'memoryBytes': 33554432, 'wallTimeLimitMillis': 5000}}}
        configured = node.configure(copy.deepcopy(settings), capsule)
        self.assertEqual(configured['engine']['threadingProfile'], package.PROFILE)
        # Preserve all four original source declarations as evidence, while the
        # authenticated final component (and its least-authority policy) has three.
        self.assertEqual(len(package.SOURCE_IMPORTS), 4)
        self.assertTrue(all(('import ' + name + ';').encode() in package.ORIGINAL_WIT
                            for name in package.SOURCE_IMPORTS))
        self.assertEqual(len(configured['providers']['bindings']), 4)
        self.assertEqual(configured['providers']['activationRuntime']['limits'], node.LIMITS)
        self.assertEqual(set(node.PROVIDERS), set(package.IMPORTS))
        runtime = configured['providers']['activationRuntime']['identity']
        self.assertNotIn('clockWall', configured['providers'])
        self.assertNotIn(package.SOURCE_IMPORTS[3], node.PROVIDERS)
        for name in ('clockMonotonic',):
            clock = configured['providers'][name]['identity']
            self.assertNotEqual((runtime['tenant'], runtime['service']), (clock['tenant'], clock['service']))
            binding = next(row for row in configured['providers']['bindings'] if row['name'] == name)
            self.assertEqual(binding['providerService'], clock['service'])
        for field, value in (('memoryBytes', 4194304), ('wallTimeLimitMillis', 1000)):
            changed = copy.deepcopy(capsule)
            changed['execution']['limits'][field] = value
            with self.assertRaisesRegex(WorkflowError, 'explicit-signed-qualification-envelope'):
                node.configure(copy.deepcopy(settings), changed)
        changed = copy.deepcopy(capsule)
        changed['imports'].pop()
        with self.assertRaisesRegex(WorkflowError, 'three-actual-component-imports'):
            node.configure(copy.deepcopy(settings), changed)
        changed = copy.deepcopy(capsule)
        changed['imports'].append({'contract': package.SOURCE_IMPORTS[3], 'optional': False})
        with self.assertRaisesRegex(WorkflowError, 'three-actual-component-imports'):
            node.configure(copy.deepcopy(settings), changed)
        configured = copy.deepcopy(settings)
        configured['cells'][0]['capacity'] = 2
        with self.assertRaisesRegex(WorkflowError, 'original-one-cell-envelope'):
            node.configure(configured, capsule)


if __name__ == '__main__':
    unittest.main()

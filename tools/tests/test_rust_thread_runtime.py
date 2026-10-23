"""Consumer replay/policy refusals; no native or captured guest execution."""
import copy
import unittest

from tools import rust_thread_runtime_node as node, rust_thread_runtime_package as package
from tools.rust_capsule_project import ROOT, digest
from tools.phase2_operator_process import WorkflowError


class RustThreadRuntimeTests(unittest.TestCase):
    def test_retained_original_pair_refuses_foreign_core_envelope_and_double_framing(self):
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
        self.assertEqual(len(configured['providers']['bindings']), 5)
        self.assertEqual(configured['providers']['activationRuntime']['limits'], node.LIMITS)
        self.assertEqual(set(node.PROVIDERS), set(package.IMPORTS))
        for field, value in (('memoryBytes', 4194304), ('wallTimeLimitMillis', 1000)):
            changed = copy.deepcopy(capsule)
            changed['execution']['limits'][field] = value
            with self.assertRaisesRegex(WorkflowError, 'explicit-signed-qualification-envelope'):
                node.configure(copy.deepcopy(settings), changed)
        changed = copy.deepcopy(capsule)
        changed['imports'].pop()
        with self.assertRaisesRegex(WorkflowError, 'four-original-declared-imports'):
            node.configure(copy.deepcopy(settings), changed)
        configured = copy.deepcopy(settings)
        configured['cells'][0]['capacity'] = 2
        with self.assertRaisesRegex(WorkflowError, 'original-one-cell-envelope'):
            node.configure(configured, capsule)


if __name__ == '__main__':
    unittest.main()

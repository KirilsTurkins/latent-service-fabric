"""Exact upstream fake-socket refusal; no network readiness is inferred."""
import ast
import hashlib
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import runtime
from tools.tests import test_go_runtime_overlay as overlay_tests
from tools.qualify_go_closed_network import outcomes

SOURCE = Path(__file__).parent / 'fixtures/go-closed-network/net_fake.go.in'


class GoClosedNetworkTests(unittest.TestCase):
    def test_only_exact_upstream_fake_socket_body_is_replaced_before_allocation(self):
        original = SOURCE.read_text(encoding='utf-8')
        self.assertEqual(hashlib.sha256(original.encode()).hexdigest(), runtime.FAKE_NETWORK_SHA256)
        before = re.search(r'(?ms)^func socket\(.*?^\}', original)[0]
        self.assertIn('newFakeNetFD(fd)', before)
        self.assertIn('fakeListen(fd, laddr)', before)
        self.assertIn('fakeConnect(ctx, fd, laddr, raddr)', before)
        adapted = runtime.closed_network_source(original)
        after = re.search(r'(?ms)^func socket\(.*?^\}', adapted)[0]
        self.assertEqual(after.split('{\n', 1)[1], '\treturn nil, errors.ErrUnsupported\n}')
        self.assertEqual(adapted.replace(after, before), original)

    def test_any_source_or_declaration_drift_is_refused_not_partially_rewritten(self):
        original = SOURCE.read_text(encoding='utf-8')
        for changed in (original + '// changed\n', original.replace('func socket(', 'func unknown('),
                        original.replace('fakeListen(fd, laddr)', 'other(fd, laddr)'),
                        runtime.closed_network_source(original)):
            with self.subTest(digest=hashlib.sha256(changed.encode()).hexdigest()), \
                    self.assertRaisesRegex(ValueError, 'source-drift:net/net_fake.go'):
                runtime.closed_network_source(changed)

    def test_real_default_overlay_refuses_fake_sockets_and_keeps_upstream_comparison_unchanged(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot, _, contracts = overlay_tests.GoRuntimeOverlayTests().fixture(root)
            original = (goroot / 'src/net/net_fake.go').read_bytes()
            with patch.dict(runtime.PREIMAGES, contracts, clear=True):
                strict = runtime.overlay(goroot, root / 'strict')
                comparison = runtime.scheduler_overlay(goroot, root / 'comparison')
            import json
            key = str(goroot / 'src/net/net_fake.go')
            rows = json.loads(strict.read_bytes())['Replace']
            self.assertIn(key, rows)
            self.assertEqual(Path(rows[key]).read_text(encoding='utf-8'), runtime.closed_network_source(original.decode()))
            self.assertNotIn(key, json.loads(comparison.read_bytes())['Replace'])
            self.assertEqual((goroot / 'src/net/net_fake.go').read_bytes(), original)

    def test_bad_or_missing_fake_source_fails_before_overlay_creation(self):
        for missing in (False, True):
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                goroot, _, contracts = overlay_tests.GoRuntimeOverlayTests().fixture(root)
                source = goroot / 'src/net/net_fake.go'
                if missing:
                    source.unlink()
                else:
                    source.write_bytes(source.read_bytes() + b'// source drift\n')
                with patch.dict(runtime.PREIMAGES, contracts, clear=True), self.assertRaises((ValueError, OSError)):
                    runtime.overlay(goroot, root / 'out')
                self.assertFalse((root / 'out').exists())

    def test_refusal_is_unconditional_before_any_optional_runtime_selection(self):
        tree = ast.parse((runtime.ROOT / 'tools/go_guest/runtime.py').read_text())
        overlay = next(row for row in tree.body if isinstance(row, ast.FunctionDef) and row.name == 'overlay')
        guarded = [row for row in overlay.body if isinstance(row, ast.Assign)
                   and any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                           and node.func.id == 'closed_network_source' for node in ast.walk(row))]
        self.assertEqual(len(guarded), 1)
        selected = next(row for row in overlay.body if isinstance(row, ast.If)
                        and isinstance(row.test, ast.Name) and row.test.id == 'activation')
        self.assertLess(guarded[0].lineno, selected.lineno)

    def test_reference_requires_both_original_false_successes_and_both_standard_refusals(self):
        original = b'tcp=fake-listener\nudp=fake-listener\n'
        corrected = b'tcp=unsupported\nudp=unsupported\n'
        self.assertEqual(outcomes(original, corrected),
            {'upstream': ['tcp=fake-listener', 'udp=fake-listener'],
             'corrected': ['tcp=unsupported', 'udp=unsupported']})
        for bad in (b'', b'tcp=fake-listener\n', corrected, original + b'unknown\n'):
            with self.assertRaisesRegex(ValueError, 'upstream-counterfactual'):
                outcomes(bad, corrected)
        for bad in (b'', b'tcp=unsupported\n', original, corrected + b'unknown\n'):
            with self.assertRaisesRegex(ValueError, 'standard-unsupported'):
                outcomes(original, bad)


if __name__ == '__main__':
    unittest.main()

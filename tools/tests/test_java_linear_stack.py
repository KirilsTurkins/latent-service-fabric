"""Guarded-link recipe controls; native layout execution is a separate witness."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from tools import java_capsule_build, qualify_java_fibers
from tools.java_guest import enum_guard

ROOT = Path(__file__).resolve().parents[2]
LINK_OWNERS = ('tools/java_guest/enum_guard.py', 'tools/java_guest/date_link_guard.py')


class JavaLinearStackTests(unittest.TestCase):
    def test_both_activation_link_paths_place_the_unchanged_stack_before_data(self):
        for owner in LINK_OWNERS:
            with self.subTest(owner=owner):
                tree = ast.parse((ROOT / owner).read_text(encoding='utf-8'))
                calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Attribute) and node.func.attr == 'run'
                         and isinstance(node.func.value, ast.Name)
                         and node.func.value.id == 'c_failure_context']
                self.assertEqual(len(calls), 1, 'inspect the actual guarded-link command')
                flags = []
                shared = 0
                for node in calls[0].args:
                    if isinstance(node, ast.Constant) and isinstance(node.value, str):
                        flags.append(node.value)
                    elif isinstance(node, ast.Starred) and isinstance(node.value, ast.Name) \
                            and node.value.id == 'ACTIVATION_C_STACK_FLAGS':
                        flags.extend(enum_guard.ACTIVATION_C_STACK_FLAGS)
                        shared += 1
                self.assertEqual(shared, 1, 'both production links use the shared reviewed stack flags')
                self.assertEqual(flags.count('-Wl,--stack-first'), 1)
                self.assertEqual([flag for flag in flags if 'stack-size=' in flag],
                                 ['-Wl,-z,stack-size=65536'])
                self.assertEqual([flag for flag in flags if '--max-memory=' in flag],
                                 ['-Wl,--max-memory=67108864'])
                self.assertIn('wasm32-wasip1', flags)
                self.assertIn('-Wl,--export-memory', flags)
                self.assertFalse(any('--global-base' in flag for flag in flags))

    def test_layout_owner_changes_invalidate_source_bound_compiler_inputs(self):
        self.assertTrue(set(LINK_OWNERS).issubset(java_capsule_build.RECIPE))
        # This unit isolates recipe identity; unrelated recipe bytes are fixtures,
        # not a claim that the entire compiler dependency closure was qualified.
        owners = {qualify_java_fibers.ROOT / name: (ROOT / name).read_bytes()
                  for name in LINK_OWNERS}
        with patch.object(qualify_java_fibers, 'read_file',
                          side_effect=lambda path: owners.get(path, b'fixture')):
            before = qualify_java_fibers.recipe_inputs()
            for owner in LINK_OWNERS:
                selected = qualify_java_fibers.ROOT / owner
                original = owners[selected]
                owners[selected] += b'\n'
                with self.subTest(owner=owner):
                    after = qualify_java_fibers.recipe_inputs()
                    self.assertEqual([key for key in before if before[key] != after[key]], [owner])
                owners[selected] = original


if __name__ == '__main__':
    unittest.main()

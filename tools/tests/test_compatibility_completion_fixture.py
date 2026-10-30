"""Ordinary project and capture handoff controls; no compiler or node execution."""
import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import compatibility_api_managed_fixture as managed
from tools import compatibility_resource_fixture as resources
from tools import compiler_compatibility_fixture as original
from tools import typescript_resource_runtime_fixture as original_typescript
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_project import ROOT, read_file, snapshot


class CompletionFixtures(unittest.TestCase):
    def test_actual_managed_project_and_counterfactual_preserve_all_original_sdk_and_library_inputs(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(subprocess, 'Popen', side_effect=AssertionError('no-compiler')):
            directory = Path(temporary) / 'project'
            prepared = managed.prepare(directory)
            before = snapshot(directory)
            # Only a fake accepted identity at this authoring boundary; real
            # capture, CIL metadata, ILC graphs and signed results are unrun.
            closure = SimpleNamespace(identity='source-control-accepted-identity')
            with patch.object(managed.application_dependencies, 'verify_inputs', return_value=closure):
                changed = managed.counterfactual(directory)
                with self.assertRaises(ValueError): managed.counterfactual(directory)
            after = snapshot(directory)
            self.assertEqual([name for name in before if before[name] != after[name]], [managed.ROOT_SOURCE])
            self.assertEqual(after[managed.ROOT_SOURCE], before[managed.ROOT_SOURCE].replace(managed.OLD, managed.NEW, 1))
            self.assertNotEqual(changed['sourceBefore'], changed['sourceAfter'])
            self.assertEqual(prepared['apiKey'], 'dotnet.System.IO.Path.GetTempFileName')
            self.assertEqual(json.loads(before['capsule-project.json'])['limits'],
                             json.loads(after['capsule-project.json'])['limits'])
            self.assertTrue(changed['libraryInputsUnchanged'])

    def test_original_capture_project_accepts_exact_two_bounded_source_inputs_without_implicit_compile(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(subprocess, 'Popen', side_effect=AssertionError('no-compiler')):
            root = Path(temporary)
            old = original.dotnet_sources(root / 'old')
            new = original.dotnet_sources(root / 'new', sources={'Core.cs': managed.CHILD, 'Library.cs': managed.LIBRARY})
            left, right = snapshot(old), snapshot(new)
            self.assertEqual(set(left), set(right))
            self.assertEqual([name for name in left if left[name] != right[name]], ['Library.cs', 'child/Core.cs'])
            self.assertEqual(left['Library.cs'], read_file(ROOT / (original.SOURCE + 'dotnet') / 'Library.cs'))
            for name in ('Library.csproj', 'child/Data.csproj', 'nuget.config'):
                self.assertEqual(left[name], right[name])
            with self.assertRaises(WorkflowError):
                original.dotnet_sources(root / 'invalid', sources={'Core.cs': managed.CHILD,
                    'Library.cs': managed.LIBRARY, 'ignored.cs': b'ignored input'})

    def test_ordinary_TS_resource_project_preserves_original_profile_grants_limits_and_capture_topology(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(subprocess, 'Popen', side_effect=AssertionError('no-compiler')):
            root = Path(temporary)
            old, _ = original_typescript.project(root / 'old', root / 'outside-old')
            new, record = resources.typescript(root / 'new', root / 'outside-new')
            self.assertEqual(snapshot(old), snapshot(new))
            before = snapshot(root / 'outside-old'); after = snapshot(root / 'outside-new')
            # The ordinary local file dependency absolute path necessarily
            # differs between owned parents; every other package input except
            # the fixed library is identical.
            for name in before:
                if name not in {'library/index.mjs', 'library/package.json'}:
                    self.assertEqual(before[name], after[name])
            left, right = (json.loads(value) for value in (before['library/package.json'], after['library/package.json']))
            left['dependencies'] = right['dependencies']
            self.assertEqual(left, right)
            self.assertEqual(record['physicalRetirement'], 'unproven')
            self.assertEqual(record['signedExecution'], 'pending')
            self.assertEqual(record['cases'], [list(row) for row in resources.TYPESCRIPT_CASES])

    def test_stack_source_is_fixed_fresh_and_cannot_reuse_an_existing_component_directory(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(subprocess, 'Popen', side_effect=AssertionError('no-compiler')):
            root = Path(temporary) / 'stack'
            value = resources.stack(root)
            original_bytes = snapshot(root)
            self.assertEqual(value['signedExecution'], 'pending')
            self.assertFalse(value['apiCauseFromUnreachable'])
            with self.assertRaises(ValueError): resources.stack(root)
            self.assertEqual(snapshot(root), original_bytes)


if __name__ == '__main__': unittest.main()

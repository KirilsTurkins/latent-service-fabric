"""Dedicated diagnostics programme; historical workflows stay byteexact."""
import hashlib
import unittest

from tools import ci_lane_inventory as lanes
from tools import activation_stack_native_products as products
from tools.rust_capsule_project import ROOT, read_file


class CompilerWorkflow(unittest.TestCase):
    def test_new_workflow_is_branch_scoped_and_keeps_old_resource_workflows_and_fixtures_exact(self):
        # Frozen source checkpoint e2f791; no inherited job selectors, commands
        # or whole-workflow restoration fixtures are edited for this feature.
        expected = {
            '.github/workflows/java-resource-runtime.yml': 'f748cda7dea09e59e5b5a8a50d4572f8c7a2dc3d0faa9b0887b049633bbf8a7b',
            '.github/workflows/dotnet-resource-runtime.yml': 'da03d35554ebc1bb71bd606b86b7d8cd90ac92a0b2fbd4439439098b1ede644e',
            'tools/tests/test_resource_late_workflows.py': '8105f29ee99e0645f246629eaef524bfdb63f9cd9bd18a2e7377f2b1d00b1070',
        }
        for name, sha in expected.items(): self.assertEqual(hashlib.sha256(read_file(ROOT/name)).hexdigest(), sha, name)
        workflow = lanes.workflow_model(read_file(ROOT/'.github/workflows/compiler-compatibility.yml').decode())
        self.assertEqual(set(workflow['on']), {'push'})
        self.assertEqual(workflow['on']['push']['branches'], ['feat/java-dotnet-diagnostics-679-20261021'])
        paths = workflow['on']['push']['paths']
        self.assertIn('.github/workflows/compiler-compatibility.yml', paths)
        self.assertIn('tools/qualify_compiler_compatibility.py', paths)
        self.assertIn('tools/fixtures/compatibility-java/**', paths)
        self.assertIn('tools/fixtures/compatibility-dotnet/**', paths)
        self.assertFalse(any('docs' in name or name == '**' for name in paths))
        self.assertEqual(set(workflow['jobs']), {'java-diagnostics', 'dotnet-diagnostics'})
        self.assertEqual(workflow['permissions'], {'contents': 'read', 'actions': 'read'})
        for name, job in workflow['jobs'].items():
            self.assertEqual(job['if'], "${{ github.event_name == 'push' && github.ref == 'refs/heads/feat/java-dotnet-diagnostics-679-20261021' }}")
            self.assertEqual(job['timeout-minutes'], 45 if name == 'java-diagnostics' else 40)

    def test_pinned_native_acquisition_token_scope_and_public_artifact_selection_are_exact(self):
        workflow = lanes.workflow_model(read_file(ROOT/'.github/workflows/compiler-compatibility.yml').decode())
        for name, job in workflow['jobs'].items():
            steps = job['steps']; commands = [step.get('run', '') for step in steps]
            fetch = next(i for i, run in enumerate(commands) if 'git fetch ' in run)
            retrieve = next(i for i, run in enumerate(commands) if 'tools/activation_stack_native_products.py' in run)
            execute = next(i for i, run in enumerate(commands) if 'tools/qualify_compiler_compatibility.py' in run)
            self.assertEqual(commands[fetch], 'git fetch --no-tags --depth=1 origin '+products.SOURCE)
            self.assertLess(fetch, retrieve); self.assertLess(retrieve, execute)
            self.assertEqual(steps[retrieve]['env'], {'GH_TOKEN': '${{ github.token }}'})
            for i, step in enumerate(steps):
                if i != retrieve: self.assertNotIn('GH_TOKEN', step.get('env', {}))
            self.assertEqual(sum('tools/qualify_compiler_compatibility.py' in run for run in commands), 1)
            self.assertFalse(any('cargo build' in run or 'qualify_resource_late_facilities.py' in run for run in commands))
            upload = steps[-1]; self.assertEqual(upload['if'], 'always()')
            paths = upload['with']['path']
            self.assertIn('/build/component.wasm', paths); self.assertIn('/build/package/**', paths)
            for private in ('*.dgml', '/project/**', '/build/*.json', 'diagnostic-source.json', 'signing-key', '.rsp'):
                self.assertNotIn(private, paths)


if __name__ == '__main__': unittest.main()

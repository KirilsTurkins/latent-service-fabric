"""Dedicated diagnostics programme; historical workflows stay byteexact."""
import hashlib
import copy
import json
import unittest

from tools import ci_lane_inventory as lanes
from tools import activation_stack_native_products as products
from tools.rust_capsule_project import ROOT, read_file


def original_workflow(test):
    workflow = lanes.workflow_model(read_file(ROOT/'.github/workflows/compiler-compatibility.yml').decode())
    restored = copy.deepcopy(workflow)
    test.assertEqual(set(restored['jobs']), {'java-diagnostics', 'dotnet-diagnostics', 'closure-required', 'closure-matrix'})
    for name in ('closure-required', 'closure-matrix'): del restored['jobs'][name]
    branches = restored['on']['push']['branches']
    test.assertEqual(branches.count('feat/sdk-compatibility-closure-20261025'), 1)
    branches.remove('feat/sdk-compatibility-closure-20261025')
    paths = restored['on']['push']['paths']
    for name in ('tools/compatibility_*.py', 'tools/qualify_compatibility_closure.py', 'tools/guest_api_analysis.py',
            'tools/guest_compiler_*.py', 'tools/guest_compatibility*.py', 'tools/*capsule_build.py',
            'tools/captured_compiler_isolation.py'):
        test.assertEqual(paths.count(name), 1); paths.remove(name)
    # All original jobs, setup, argv, artifacts and scheduling remain exact.
    test.assertEqual(hashlib.sha256(json.dumps(restored, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        '7f7c9f67efb2a828e6c606c14ce43bf657bf55550c5550f3db92da4ec74c4824')
    return restored


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
        workflow = original_workflow(self)
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
        workflow = original_workflow(self)
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

    def test_completion_requires_exact_eight_cells_and_original_native_and_process_bounds(self):
        from tools.qualify_compatibility_closure import JOB_MINUTES
        from tools.compatibility_closure_matrix import CELLS, PRESERVED_CELLS
        from tools.compatibility_preserved_cells import PINS
        workflow = lanes.workflow_model(read_file(ROOT/'.github/workflows/compiler-compatibility.yml').decode())
        job = workflow['jobs']['closure-required']
        self.assertEqual(job['if'], "${{ github.event_name == 'push' && github.ref == 'refs/heads/feat/sdk-compatibility-closure-20261025' }}")
        self.assertEqual(job['strategy'], {'fail-fast': False, 'max-parallel': 4, 'matrix': {
            'include': [{'cell': cell, 'minutes': minutes} for cell, minutes in JOB_MINUTES.items() if cell not in PRESERVED_CELLS]}})
        active = {row['cell'] for row in job['strategy']['matrix']['include']}
        self.assertEqual(set(PINS), set(PRESERVED_CELLS))
        self.assertEqual(active | set(PINS), set(CELLS))
        self.assertFalse(active & set(PINS))
        self.assertEqual(job['timeout-minutes'], '${{ matrix.minutes }}')
        self.assertEqual(job['env']['CARGO_BUILD_JOBS'], 2)
        steps = job['steps']; commands = [step.get('run', '') for step in steps]
        native = next(step for step in steps if 'tools/compatibility_native_products.py' in step.get('run', ''))
        self.assertEqual(native['env'], {'GH_TOKEN': '${{ github.token }}'})
        self.assertFalse(any('cargo build' in command or 'native_build.py' in command for command in commands))
        self.assertIn('--prepare-java-cache', '\n'.join(commands))
        execute = next(command for command in commands if '--cell "$CELL"' in command)
        self.assertIn('--engine "$RUNNER_TEMP/compatibility-typescript-engine/products"', execute)
        self.assertIn('*) exit 2', execute)
        admission = next(step for step in steps if step.get('id') == 'public')
        self.assertEqual(admission['if'], 'always()')
        self.assertIn('compatibility_closure_matrix.py retain', admission['run'])
        self.assertEqual(steps[-1]['if'], "${{ always() && steps.public.outputs.admitted == 'true' }}")
        self.assertEqual(steps[-1]['with']['path'], '${{ runner.temp }}/compatibility-public/**')
        rollup = workflow['jobs']['closure-matrix']
        self.assertEqual(rollup['needs'], 'closure-required')
        self.assertEqual(len([step for step in rollup['steps'] if 'download-artifact@' in step.get('uses', '')]), len(active))
        retained = [step for step in rollup['steps'] if 'compatibility_preserved_cells.py' in step.get('run', '')]
        self.assertEqual(len(retained), 1)
        self.assertEqual(retained[0]['env'], {'GH_TOKEN': '${{ github.token }}'})
        assemble = next(step['run'] for step in rollup['steps'] if 'closure_matrix.py assemble' in step.get('run', ''))
        self.assertIn('--preserved "$RUNNER_TEMP/compatibility-preserved"', assemble)
        self.assertIn('--diagnostics "$RUNNER_TEMP/compatibility-current-diagnostics"', assemble)


if __name__ == '__main__': unittest.main()

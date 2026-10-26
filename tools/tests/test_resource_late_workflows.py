"""Manual late lanes preserve all previous owning source and defaults."""
import hashlib
import unittest

from tools import ci_lane_inventory as ci_lanes
from tools import release_preparation_cli_native_products as products
from tools.rust_capsule_project import ROOT, read_file


class ResourceLateWorkflows(unittest.TestCase):
    ORIGINALS = {
        'java': 'dcba5d7051ed5930499f1518c03df1258538e7b1504b784d436ebdcdafecdae3',
        'dotnet': '2603388d03bbac5d473857bf39a6e932327b9c2fcf89ff5db15965529f9edf7d',
    }

    def test_removing_only_reviewed_selector_and_job_restores_both_original_workflows(self):
        for language, expected in self.ORIGINALS.items():
            raw = read_file(ROOT/('.github/workflows/'+language+'-resource-runtime.yml')).decode()
            if language == 'dotnet':
                raw, replay = raw.split('\n  replay-late-facilities:\n')
                self.assertTrue(replay.startswith("    if: ${{ github.event_name == 'workflow_dispatch' && inputs.replay_late_facilities && !inputs.late_facilities }}\n"))
                raw = raw.replace('      replay_late_facilities:\n'
                    '        description: Reuse the exact completed df4 AOT package after its managed-profile reader repair\n'
                    '        type: boolean\n        default: false\n', '', 1)
                raw = raw.replace('(!inputs.late_facilities && !inputs.replay_late_facilities)', '!inputs.late_facilities', 1)
                raw = raw.replace('inputs.late_facilities && !inputs.replay_late_facilities', 'inputs.late_facilities', 1)
            before, job = raw.split('\n  late-facilities:\n')
            self.assertTrue(job.startswith("    if: ${{ github.event_name == 'workflow_dispatch' && inputs.late_facilities }}\n"))
            if language == 'java':
                before = before.replace('      late_facilities:\n'
                    '        description: One fresh ordinary Java component for accepted callbacks after cancellation\n'
                    '        type: boolean\n        default: false\n', '', 1)
                before = before.replace('!(inputs.replay_retained_component || inputs.diagnose_retained_component || inputs.late_facilities)',
                    '!(inputs.replay_retained_component || inputs.diagnose_retained_component)', 1)
                before = before.replace("github.event_name == 'workflow_dispatch' && !inputs.late_facilities && (inputs.replay_retained_component || inputs.diagnose_retained_component)",
                    "github.event_name == 'workflow_dispatch' && (inputs.replay_retained_component || inputs.diagnose_retained_component)", 1)
            else:
                before = before.replace('  workflow_dispatch:\n    inputs:\n      late_facilities:\n'
                    '        description: One fresh ordinary managed component for accepted callbacks after DisposeAsync\n'
                    '        type: boolean\n        default: false\n', '  workflow_dispatch:\n', 1)
                before = before.replace("  resource-runtime:\n    if: ${{ github.event_name != 'workflow_dispatch' || !inputs.late_facilities }}\n",
                    '  resource-runtime:\n', 1)
            self.assertEqual(hashlib.sha256((before.rstrip()+'\n').encode()).hexdigest(), expected, language)

    def test_lanes_require_explicit_boolean_and_exact_historical_native_source_before_verification(self):
        for language in self.ORIGINALS:
            raw = read_file(ROOT/('.github/workflows/'+language+'-resource-runtime.yml')).decode()
            workflow = ci_lanes.workflow_model(raw)
            selector = workflow['on']['workflow_dispatch']['inputs']['late_facilities']
            self.assertEqual(selector['type'], 'boolean'); self.assertIs(selector['default'], False)
            job = workflow['jobs']['late-facilities']
            expected_if = "${{ github.event_name == 'workflow_dispatch' && inputs.late_facilities }}"
            if language == 'dotnet':
                expected_if = "${{ github.event_name == 'workflow_dispatch' && inputs.late_facilities && !inputs.replay_late_facilities }}"
            self.assertEqual(job['if'], expected_if)
            steps = job['steps']; commands = [step.get('run', '') for step in steps]
            fetch = next(i for i, command in enumerate(commands) if 'git fetch ' in command)
            retrieve = next(i for i, command in enumerate(commands) if 'tools/release_preparation_cli_native_products.py' in command)
            self.assertEqual(commands[fetch], 'git fetch --no-tags --depth=1 origin '+products.SOURCE)
            self.assertLess(fetch, retrieve)
            self.assertEqual(steps[retrieve]['env'], {'GH_TOKEN': '${{ github.token }}'})
            for i, step in enumerate(steps):
                if i != retrieve: self.assertNotIn('GH_TOKEN', step.get('env', {}))
            self.assertEqual(sum('tools/qualify_resource_late_facilities.py' in command for command in commands), 1)
            self.assertFalse(any('qualify_rust_capsules.py' in command or 'cargo build' in command for command in commands))


if __name__ == '__main__': unittest.main()

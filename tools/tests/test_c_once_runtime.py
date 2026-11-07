"""Focused receipt and source-selection controls; no guest result is fabricated."""
from pathlib import Path
import unittest

from tools import c_capsule_build, qualify_c_once_runtime as once, qualify_c_thread_runtime as old
from tools.c_guest.threading import RECIPE
from tools.c_guest.threading_compatibility import RECIPE as COMPATIBILITY
from tools.ci_lane_inventory import workflow_model
from tools.phase2_operator_process import WorkflowError


class OnceRuntimeControls(unittest.TestCase):
    def test_real_owner_witness_requires_exact_counts_and_bounded_memory(self):
        observed = once.witness('once:1:2:3:3:4:3:8:4096')
        self.assertEqual(observed['waits'], 3)
        self.assertEqual(observed['parkedTasks'], 3)
        self.assertFalse(observed['canonicalPollPendingClaimed'])
        self.assertFalse(observed['automaticCpuFairnessClaimed'])
        for bad in ('once:2:2:3:3:4:3:8:4096', 'once:1:1:3:3:4:3:8:4096',
                    'once:1:2:2:3:4:3:8:4096', 'once:1:2:3:2:4:3:8:4096',
                    'once:1:2:3:3:3:3:8:4096', 'once:1:2:3:3:4:2:8:4096',
                    'once:1:2:3:3:4:3:7:4096', 'once:1:2:3:3:4:3:8:0',
                    'once:01:2:3:3:4:3:8:4096', 'once:1:2:3:3:4:3:8:33554433'):
            with self.subTest(bad=bad), self.assertRaises(WorkflowError):
                once.witness(bad)

    def test_workflow_selects_every_current_receipt_input(self):
        workflow = workflow_model((once.ROOT / once.WORKFLOW).read_text())
        paths = set(workflow['on']['push']['paths'])
        required = set((*c_capsule_build.RECIPE, *RECIPE, *COMPATIBILITY, *old.MATERIALS,
            once.SELF, once.SOURCE, once.WORKFLOW, once.WORLD, 'tools/requirements.lock',
            'tools/toolchain.toml', 'tools/tests/test_c_once_runtime.py',
            'tools/qualify_java_server_lifecycle.py', 'tools/qualify_java_server_lifecycle_suite.py'))
        self.assertEqual(required - paths, set())
        self.assertTrue({'apps/**', 'crates/**', 'sdk/rust/**', 'tools/optimization-workloads/**',
            'sdk/c-guest/**', 'wit/**', 'schemas/**', 'api/proto/**', 'Cargo.toml', 'Cargo.lock',
            'rust-toolchain.toml', '.cargo/config.toml'} <= paths)
        self.assertEqual(workflow['on']['push']['branches'], ['development'])
        self.assertNotIn('pull_request', workflow['on'])
        self.assertEqual(workflow['concurrency'], {'group': 'c-once-current-${{ github.ref }}',
                                                    'cancel-in-progress': True})


if __name__ == '__main__':
    unittest.main()

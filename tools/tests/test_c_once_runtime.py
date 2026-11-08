"""Focused receipt and source-selection controls; no guest result is fabricated."""
from pathlib import Path
import json
import tempfile
import unittest

from tools import c_capsule_build, qualify_c_once_runtime as once, qualify_c_thread_runtime as old
from tools.c_guest.threading import RECIPE
from tools.c_guest.threading_compatibility import RECIPE as COMPATIBILITY
from tools.ci_lane_inventory import structural_workflow, workflow_model
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

    def test_root_drain_requires_both_exact_host_barriers_and_joined_result(self):
        for mode in ('pre', 'late'):
            observed = once.root_drain_witness(mode + ':3:3:3:1', mode)
            self.assertEqual(observed['waitsBeforeRoot'], 3)
            self.assertEqual(observed['waitsWithRootObserver'], 3)
            self.assertTrue(observed['applicationJoinCompleted'])
            self.assertTrue(observed['resultBytesUpdatedAfterRootReturn'])
            self.assertFalse(observed['canonicalPollPendingClaimed'])
            self.assertFalse(observed['kernelNativeFinalFreeProved'])
            for suffix in (':2:3:3:1', ':3:2:3:1', ':3:3:2:1', ':3:3:3:0', ':03:3:3:1'):
                with self.subTest(mode=mode, suffix=suffix), self.assertRaises(WorkflowError):
                    once.root_drain_witness(mode + suffix, mode)
        with self.assertRaises(WorkflowError):
            once.root_drain_witness('pre:3:3:3:1', 'late')
        with self.assertRaises(WorkflowError):
            once.root_drain_witness('pre:3:3:3:1', 'unknown')

    def test_combined_component_keeps_original_envelope_and_exact_fixture(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = once.prepare(Path(temporary) / 'project')
            self.assertEqual((project / 'src/main.c').read_bytes(), (once.ROOT / once.SOURCE).read_bytes())
            self.assertEqual((project / 'src/root-drain.h').read_bytes(),
                             (once.ROOT / once.ROOT_DRAIN_SOURCE).read_bytes())
            limits = json.loads((project / 'capsule-project.json').read_bytes())['limits']
            self.assertEqual((limits['cpuFuel'], limits['memoryBytes'], limits['wallTimeLimitMillis']),
                             (1_000_000_000, 32 * 1024 * 1024, 5000))
            self.assertEqual((limits['outboundRequests'], limits['childCalls'], limits['logBytes']), (0, 0, 0))

    def test_workflow_selects_every_current_receipt_input(self):
        workflow = workflow_model((once.ROOT / once.WORKFLOW).read_text())
        paths = set(workflow['on']['push']['paths'])
        required = set((*c_capsule_build.RECIPE, *RECIPE, *COMPATIBILITY, *old.MATERIALS,
            once.SELF, once.SOURCE, once.ROOT_DRAIN_SOURCE, once.WORKFLOW, once.WORLD, 'tools/requirements.lock',
            'tools/toolchain.toml', 'tools/tests/test_c_once_runtime.py',
            'tools/qualify_java_server_lifecycle.py', 'tools/qualify_java_server_lifecycle_suite.py'))
        self.assertEqual(required - paths, set())
        self.assertTrue({'apps/**', 'crates/**', 'sdk/rust/**', 'tools/optimization-workloads/**',
            'sdk/c-guest/**', 'wit/**', 'schemas/**', 'api/proto/**', 'Cargo.toml', 'Cargo.lock',
            'rust-toolchain.toml', '.cargo/config.toml'} <= paths)
        self.assertEqual(workflow['on']['push']['branches'], ['development', 'feat/c-root-drain-signed-20261108'])
        self.assertNotIn('pull_request', workflow['on'])
        self.assertEqual(workflow['concurrency'], {'group': 'c-once-current-${{ github.ref }}',
                                                    'cancel-in-progress': True})
        model = structural_workflow(workflow)
        contracts = once.ROOT / 'tools/ci/contracts/workflows/c-once-runtime.yml'
        policy = json.loads((contracts / 'workflow.json').read_bytes())
        job = json.loads((contracts / 'jobs/once.json').read_bytes())
        self.assertEqual(policy['policy'], {key: value for key, value in model.items() if key != 'jobs'})
        self.assertEqual(policy['requiredJobs'], ['once'])
        self.assertIn("github.ref == 'refs/heads/feat/c-root-drain-signed-20261108'", model['jobs']['once']['if'])
        self.assertEqual(job['definition'], model['jobs']['once'])


if __name__ == '__main__':
    unittest.main()

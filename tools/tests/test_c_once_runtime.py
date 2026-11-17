"""Focused receipt and source-selection controls; no guest result is fabricated."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

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

    def test_semaphore_witness_requires_real_parked_waiter_and_one_handoff(self):
        observed = once.semaphore_witness('sem:1:1:2:2:3:2:6:4096')
        self.assertEqual((observed['posts'], observed['waitersCompleted']), (1, 1))
        self.assertEqual((observed['waits'], observed['parkedTasks']), (2, 2))
        self.assertEqual(observed['observedBy'], 'ordinary-controller-before-post')
        self.assertFalse(observed['canonicalPollPendingClaimed'])
        self.assertFalse(observed['automaticCpuFairnessClaimed'])
        self.assertFalse(observed['timedOrProcessSharedClaimed'])
        for bad in ('sem:0:1:2:2:3:2:6:4096', 'sem:1:0:2:2:3:2:6:4096',
                    'sem:1:1:1:2:3:2:6:4096', 'sem:1:1:2:1:3:2:6:4096',
                    'sem:1:1:2:2:2:2:6:4096', 'sem:1:1:2:2:3:1:6:4096',
                    'sem:1:1:2:2:3:2:5:4096', 'sem:1:1:2:2:3:2:6:0',
                    'sem:01:1:2:2:3:2:6:4096', 'sem:1:1:2:2:3:2:6:33554433'):
            with self.subTest(bad=bad), self.assertRaises(WorkflowError):
                once.semaphore_witness(bad)

    def test_semaphore_invocation_uses_original_authority_and_retirement_checks(self):
        consumed = dict(cpuFuel=1, peakMemoryBytes=4096, outboundRequests=0, stateReadBytes=0,
                        stateWriteBytes=0, blobReadBytes=0, blobWriteBytes=0, logBytes=0,
                        effectCount=0, childCalls=0)
        row = {'processReaped': True, 'exitCode': 0, 'decoded': [{'ok': 'sem:1:1:2:2:3:2:6:4096'}],
               'response': {'outcomeKnown': True, 'requestDispatched': True,
                            'data': {'resolvedRevision': 'revision', 'consumption': consumed}}}
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(once.owner, 'selected_revision', return_value='revision'), \
                patch.object(once.owner, 'start_call', return_value='process') as start, \
                patch.object(once.owner, 'finish_call', return_value=row), \
                patch.object(once.owner, 'retire', return_value={'physicalOwnersAfter': 0,
                                                                 'activeProviderCountersAfter': 0}) as retire, \
                patch.object(once.owner, 'close_call') as close:
            result = once.invoke('client', 'probe', 'target', Path(directory), 'test-sem', 'sem')
            self.assertEqual(result['witness']['waitersCompleted'], 1)
            start.assert_called_once_with('client', 'target', once.owner.SERVICE, 'greet', ['sem'], 'test-sem')
            retire.assert_called_once_with('client', 'probe', 'target', Path(directory), 'test-sem')
            close.assert_called_once_with('process', primary_failure=False)

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
        self.assertEqual(workflow['on']['push']['branches'],
                         ['development', 'feat/c-root-drain-signed-20261108', 'feat/sdk-c-semaphore-signed-20261117'])
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
        self.assertIn("github.ref == 'refs/heads/feat/sdk-c-semaphore-signed-20261117'", model['jobs']['once']['if'])
        self.assertEqual(job['definition'], model['jobs']['once'])


if __name__ == '__main__':
    unittest.main()

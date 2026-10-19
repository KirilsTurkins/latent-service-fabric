"""Opt-in worker ownership and fail-closed source transformations.

These are source/selection controls; the additive signed native gate qualifies
actual Go startup, GC, original ledger finalization and Store retirement.
"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import activation, managed_idle, runtime
from tools import go_application_dependencies as dependencies
from tools import guest_runtime_receipts as receipts
from tools.rust_capsule_project import inventory
from tools.dev_workflow.common import digest, encode


def bridge_sources():
    return {'runtime/proc.go': '\tdoInit(runtime_inittasks) // Must be before defer.\n'
            'func execute(gp *g, inheritTime bool) {\n\tif gp.lsfParked { lsfTaskWake(gp) }\n}\n',
            'runtime/os_wasip1.go': (runtime.ROOT / 'sdk/go-guest/runtime/activation_bridge.go.in').read_text()}


class ManagedIdle(unittest.TestCase):
    def test_normal_project_creation_captures_profile_and_original_activation_contract(self):
        from tools.go_capsule_project import create, snapshot, validate
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / 'application', 'greeting', runtime_profile=managed_idle.PROFILE)
            files = snapshot(project)
            selected, _, _ = validate(files)
            self.assertEqual(selected['runtimeProfile'], managed_idle.PROFILE)
            self.assertIn(b'import latent:runtime/activation@0.1.0;', files['wit/world.wit'])
            self.assertIn(b'greet: async func(', files['wit/world.wit'])
            self.assertIn('vendor/lsf/sdk/go-guest/runtime/managed_idle.go.in', files)
            self.assertEqual(selected['limits']['logBytes'], 0)

    def test_profile_is_explicit_and_inherits_only_reviewed_predecessors(self):
        self.assertEqual(dependencies.selection()['runtimeProfile'], 'go-component-async-v1')
        self.assertIn(managed_idle.PROFILE, activation.INITIALIZER_PROFILES)
        self.assertIn(managed_idle.PROFILE, activation.TIMER_PROFILES)
        self.assertIn(managed_idle.PROFILE, activation.CHECKPOINT_PROFILES)
        self.assertEqual(dependencies.selection({'runtimeProfile': managed_idle.PROFILE})['runtimeProfile'], managed_idle.PROFILE)
        for profile in ('go-component-activation-v6', 'go-component-activation-v5-extra'):
            with self.subTest(profile=profile), self.assertRaisesRegex(ValueError, 'profile-not-installed'):
                dependencies.selection({'runtimeProfile': profile})

    def test_source_transform_rejects_missing_or_ambiguous_worker_and_retirement_hooks(self):
        original = bridge_sources()
        for filename, marker in (
                ('runtime/proc.go', '\tdoInit(runtime_inittasks) // Must be before defer.'),
                ('runtime/os_wasip1.go', 'if lsfTrustedIdle(fn.fn) { return [2]uint64{} }'),
                ('runtime/os_wasip1.go', '\tlsfActivationActive = false\n}')):
            for replacement in ('changed source hook', marker + '\n' + marker):
                sources = copy.deepcopy(original)
                sources[filename] = sources[filename].replace(marker, replacement)
                with self.subTest(filename=filename, replacement=replacement), \
                        self.assertRaisesRegex(ValueError, 'overlay-contract-drift'):
                    managed_idle.runtime_sources(sources, runtime.ROOT / 'sdk/go-guest')
        self.assertEqual(original, bridge_sources())

    def test_source_transform_keeps_actual_worker_allocation_and_user_ownership_separate(self):
        sources = bridge_sources()
        managed_idle.runtime_sources(sources, runtime.ROOT / 'sdk/go-guest')
        proc, bridge = sources['runtime/proc.go'], sources['runtime/os_wasip1.go']
        self.assertLess(proc.index('lsfPrepareManagedIdle()'), proc.index('doInit(runtime_inittasks)'))
        task = bridge.split('func lsfNewTask(', 1)[1].split('\n}', 1)[0]
        self.assertLess(task.index('lsfTakeManagedOwner()'), task.index('lsfRegister(0,'))
        self.assertIn('lsfManagedBeforeRun(gp)\n\t\tgp.lsfOwner = [2]uint64{}', bridge)
        self.assertIn('gp.startpc) && lsfManagedOwner(gp)', bridge)
        self.assertIn('status != _Gwaiting', bridge)
        self.assertLess(bridge.index('lsfRetireManagedIdle()'), bridge.index('lsfActivationActive = false'))
        # The actual component import occurs in pre-admission/retirement,
        # never in GC-side slot selection or maintenance park/wake hooks.
        take = bridge.split('func lsfTakeManagedOwner()', 1)[1].split('\n}', 1)[0]
        self.assertNotIn('lsfRegister(', take)
        self.assertNotIn('lsfSettle(', take)
        self.assertIn('lsfManagedAssigned >= lsfManagedCapacity', take)
        self.assertLess(proc.index('lsfManagedBeforeRun(gp)'), proc.index('if gp.lsfParked'))
        retired = bridge.split('func lsfRetireManagedIdle()', 1)[1]
        self.assertNotIn('lsfManagedOwners[index] =', retired)
        self.assertIn('!lsfManagedPrepared', bridge.split('func lsfManagedBeforeRun(', 1)[1].split('\n}', 1)[0])

    def test_incomplete_overlay_flags_fail_before_any_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot = root / 'goroot'
            goroot.mkdir()
            for value in (True, 1, 'yes'):
                destination = root / 'overlay'
                with patch.object(runtime, 'checked_sources', return_value={}), \
                        self.assertRaisesRegex(ValueError, 'managed-idle-requires-complete'):
                    runtime.overlay(goroot, destination, managed_idle=value)
                self.assertFalse(destination.exists())

    def test_runtime_receipt_binds_v5_project_and_captured_selection(self):
        profile = managed_idle.PROFILE
        component = b'not an actual runtime qualification'
        files = {'vendor/lsf/sdk/go-guest/runtime/managed_idle.go.in': b'captured worker implementation',
                 'wit/world.wit': b'package controlled:app;',
                 'capsule-project.json': encode({'runtimeProfile': profile}),
                 'sdk-lock.json': encode({'language': 'go'})}
        graph = {'selection': {'runtimeProfile': profile}, 'artifacts': []}
        files['latent.dependencies.lock.json'] = encode(graph)
        material = [{'name': 'compiler', 'digest': digest(b'compiler'), 'size': 8},
                    {'name': 'build-recipe', 'digest': digest(b'controlled recipe'), 'size': 17}]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            receipts.emit(output, 'go', profile, files, inventory(files), component, material,
                          graph=graph, binding_digest=digest(b'bindings'), configuration={'profile': profile})
            value = receipts.read((output / 'standard-runtime-selection.json').read_bytes())
            receipts.verify_build(value, 'go', files, inventory(files), component, material)
            files['capsule-project.json'] = encode({'runtimeProfile': 'go-component-activation-v4'})
            with self.assertRaisesRegex(ValueError, 'project-and-captured-runtime-profile-disagree'):
                receipts.verify_build(value, 'go', files, inventory(files), component, material)


if __name__ == '__main__':
    unittest.main()

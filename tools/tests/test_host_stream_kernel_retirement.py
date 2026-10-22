"""Fixed one-object admission and source-freeze controls; never build Linux."""
import unittest
from unittest.mock import patch

from tools import ci_lane_inventory as lanes
from tools import qualify_host_stream_kernel_retirement as candidate


class KernelRetirementObjectCheck(unittest.TestCase):
    def selected_configuration(self):
        objects = candidate.objects
        before = dict.fromkeys((*objects.REQUIRED, 'CONFIG_NETLABEL', 'CONFIG_XFRM',
            *objects.AUDIT_REQUIRED, *objects.DEVICE_REQUIRED, *objects.REGISTRATION_REQUIRED,
            *objects.RECIPIENT_REQUIRED), 'y')
        before.update(dict.fromkeys((*objects.DEVICE_DISABLED, *objects.REGISTRATION_DISABLED,
            'CONFIG_NET_DEV_REFCNT_TRACKER', 'CONFIG_LWTUNNEL', 'CONFIG_PREEMPT_RT'), 'n'))
        before.update(CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE='256',
            CONFIG_LSF_STREAM_FACTORY='n', CONFIG_MEMCG='y')
        return before, {**before, candidate.objects.SELECTED: 'y'}

    def parent_materials(self):
        names = set(candidate.source.preimages()['selectedWholeDerivedFiles'])
        names.update('unchanged-' + str(index) for index in range(189 - len(names)))
        return (dict.fromkeys(names, b'prior'),
            dict.fromkeys(('prior-source-' + str(index) for index in range(132)), {'sha256': 'a'}),
            dict.fromkeys(('original-' + str(index) for index in range(161)), b'original'))

    def test_only_factory_and_all_eighty_seven_original_oracles_are_selected(self):
        old = candidate.objects.object_selection(False, recipient=True)
        self.assertEqual((len(old), sum(map(len, old.values()))), (56, 243))
        self.assertEqual(candidate.object_selection(), {'net/factory.o': old['net/factory.o']})
        self.assertEqual(len(candidate.object_selection()['net/factory.o']), 87)
        self.assertEqual(candidate.recipe_inputs()[candidate.PARENT_RECIPE]['sha256'],
            candidate.PARENT_RECIPE_SHA)
        with patch.object(candidate.objects, 'object_selection', return_value={'net/factory.o': ()}), \
                self.assertRaisesRegex(ValueError, 'original-recipient-oracle-drift'):
            candidate.object_selection()

    def test_parent_recipe_drift_is_not_accepted_as_a_new_alias(self):
        original = candidate.objects.identity
        def changed(path):
            value = original(path)
            return {**value, 'sha256': '0' * 64} if path.name == 'qualify_host_stream_kernel_objects.py' else value
        with patch.object(candidate.objects, 'identity', side_effect=changed), \
                self.assertRaisesRegex(ValueError, 'reviewed-parent-recipe-changed'):
            candidate.recipe_inputs()

    def test_all_eighty_seven_definitions_must_be_unique_global_text_not_local_or_undefined(self):
        expected = candidate.object_selection()['net/factory.o']
        rows = ['%016x T %s\n' % (index, name) for index, name in enumerate(expected)]
        raw = ''.join(rows).encode()
        self.assertEqual(set(candidate.defined_symbols(raw, expected)), set(expected))
        for wrong in (raw.replace(b' T ', b' t ', 1),
                ('                 U ' + expected[0] + '\n' + ''.join(rows[1:])).encode(),
                raw + rows[0].encode(), ''.join(rows[1:]).encode(),
                raw.replace(b' T ', b' D ', 1)):
            with self.subTest(symbols=wrong[:75]), self.assertRaises(ValueError):
                candidate.defined_symbols(wrong, expected)
        with self.assertRaises(ValueError):
            candidate.defined_symbols(raw, (*expected[:-1], expected[0]))

    def test_original_132_materials_are_kept_and_two_new_sources_are_frozen(self):
        derived, frozen, original = self.parent_materials()
        changed = {name: b'changed' if name in candidate.source.preimages()['selectedWholeDerivedFiles']
            else raw for name, raw in derived.items()}
        with patch.object(candidate.objects, 'recipient_derive_frozen',
                return_value=(derived, frozen, original)) as parent, \
                patch.object(candidate.source, 'transform', return_value=changed):
            actual, materials, selected = candidate.derive_frozen('same-tree', 'same-original')
        parent.assert_called_once_with('same-tree', 'same-original')
        self.assertEqual(actual, changed)
        self.assertIs(selected, original)
        self.assertEqual(len(materials), 134)
        self.assertTrue(set(frozen) <= set(materials))
        self.assertEqual({key: materials[key] for key in frozen}, frozen)
        self.assertEqual(set(materials) - set(frozen), {
            'tools/host_stream_kernel_device_retirement.py',
            'tools/tests/fixtures/host_stream_kernel_device_retirement.json'})

    def test_unknown_output_membership_or_eighth_changed_fragment_refuses(self):
        derived, frozen, original = self.parent_materials()
        changed = {name: b'changed' if name in candidate.source.preimages()['selectedWholeDerivedFiles']
            else raw for name, raw in derived.items()}
        for wrong in (derived, {**changed, 'new-output': b'new'},
                {**changed, 'unchanged-0': b'eighth'}):
            with self.subTest(outputs=len(wrong)), \
                    patch.object(candidate.objects, 'recipient_derive_frozen',
                        return_value=(derived, frozen, original)), \
                    patch.object(candidate.source, 'transform', return_value=wrong), \
                    self.assertRaisesRegex(ValueError, 'seven-fragment-scope'):
                candidate.derive_frozen('tree', 'original')

    def test_after_hashes_are_checked_even_when_the_original_deriver_raises(self):
        original = candidate.objects.identity
        changed = False
        def observe(path):
            value = original(path)
            return {**value, 'sha256': '0' * 64} if changed else value
        def fail(*args):
            nonlocal changed
            changed = True
            raise RuntimeError('original-derivation-failure')
        with patch.object(candidate.objects, 'identity', side_effect=observe), \
                patch.object(candidate.objects, 'recipient_derive_frozen', side_effect=fail), \
                self.assertRaisesRegex(ValueError, 'source-changed-during-derivation'):
            candidate.derive_frozen('tree', 'original')
        with patch.object(candidate.objects, 'recipient_derive_frozen',
                side_effect=RuntimeError('original-derivation-failure')), \
                self.assertRaisesRegex(RuntimeError, 'original-derivation-failure'):
            candidate.derive_frozen('tree', 'original')

    def test_original_configuration_and_generated_security_cannot_be_weakened(self):
        before, after = self.selected_configuration()
        candidate.configuration(before, after)
        raw = ''.join('#define ' + name + ' ' + ('1' if value == 'y' else value) + '\n'
            for name, value in after.items() if value != 'n').encode()
        candidate.generated_configuration(raw)
        for name in candidate.objects.REQUIRED + candidate.objects.RECIPIENT_REQUIRED:
            with self.subTest(disabled=name), self.assertRaises(ValueError):
                candidate.configuration({**before, name: 'n'}, {**after, name: 'n'})
            with self.subTest(generated=name), self.assertRaises(ValueError):
                candidate.generated_configuration(raw.replace(('#define ' + name + ' 1\n').encode(), b''))
        for name, value in (('CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE', '128'),
                ('CONFIG_PREEMPT_RT', 'y'), ('CONFIG_NLMON', 'y'), ('CONFIG_PCI_IOV', 'y')):
            with self.subTest(changed=name), self.assertRaises(ValueError):
                candidate.configuration({**before, name: value}, {**after, name: value})
        with self.assertRaises(ValueError):
            candidate.configuration(before, {**after, 'CONFIG_MEMCG': 'n'})
        with self.assertRaises(ValueError):
            candidate.generated_configuration(raw + b'#define CONFIG_PREEMPT_RT 1\n')

    def test_local_or_wrong_repository_event_and_branch_refuse_before_source_or_output(self):
        expected = {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Linux',
            'GITHUB_REPOSITORY': 'KirilsTurkins/latent-service-fabric',
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': candidate.BRANCH}
        for field, value in (('GITHUB_ACTIONS', 'false'), ('RUNNER_OS', 'Windows'),
                ('GITHUB_REPOSITORY', 'outside/repository'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                ('GITHUB_REF_NAME', 'development')):
            with self.subTest(field=field), patch.object(candidate.sys, 'platform', 'linux'), \
                    patch.dict(candidate.os.environ, {**expected, field: value}, clear=True), \
                    patch.object(candidate, 'recipe_inputs') as recipe, \
                    patch.object(candidate.objects, 'snapshot_archive') as archive, \
                    self.assertRaises(ValueError):
                candidate.run(None, None)
            recipe.assert_not_called()
            archive.assert_not_called()
        with patch.object(candidate.sys, 'platform', 'linux'), \
                patch.dict(candidate.os.environ, expected, clear=True), \
                patch.object(candidate, 'recipe_inputs', side_effect=RuntimeError('passed-origin')):
            with self.assertRaisesRegex(RuntimeError, 'passed-origin'):
                candidate.run(None, None)

    def test_new_workflow_has_one_fixed_job_no_dispatch_inputs_or_sdk_build(self):
        value = lanes.workflow_model((candidate.ROOT / candidate.WORKFLOW).read_text())
        self.assertEqual(set(value['on']), {'push'})
        self.assertEqual(value['on']['push']['branches'], [candidate.BRANCH])
        self.assertFalse(value['concurrency']['cancel-in-progress'])
        self.assertEqual(set(value['jobs']), {'factory-object'})
        job = value['jobs']['factory-object']
        self.assertEqual((job['runs-on'], job['timeout-minutes']), ('ubuntu-24.04', 20))
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        self.assertIn('tools/qualify_host_stream_kernel_retirement.py', commands)
        self.assertNotIn('tools/qualify_host_stream_kernel_objects.py', commands)
        self.assertNotIn('cargo ', commands)
        self.assertNotIn('--recipient', commands)
        self.assertIn('--max-time 180', commands)
        upload = job['steps'][-1]
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['retention-days'], 3)
        self.assertTrue(upload['with']['path'].endswith('/objects/net/factory.o\n'))
        self.assertEqual(upload['with']['path'].count('.o\n'), 1)


if __name__ == '__main__':
    unittest.main()

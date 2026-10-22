"""Fixed four-object recipe and compile-only geometry guards; never build Linux."""
import hashlib
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_lane_inventory as lanes
from tools import qualify_host_stream_kernel_cleanup_stack as candidate


class CleanupStackObjects(unittest.TestCase):
    def selected_configuration(self):
        from tools.tests.test_host_stream_kernel_retirement import KernelRetirementObjectCheck
        before, after = KernelRetirementObjectCheck().selected_configuration()
        before.update(dict.fromkeys(candidate.STACK_REQUIRED, 'y'))
        before.update(dict.fromkeys(candidate.STACK_DISABLED, 'n'))
        after.update(before)
        after[candidate.objects.SELECTED] = 'y'
        return before, after

    def parent(self):
        return (dict.fromkeys(('derived-' + str(i) for i in range(189)), b'derived'),
            dict.fromkeys(('frozen-' + str(i) for i in range(138)), {'sha256': 'a'}),
            dict.fromkeys(('original-' + str(i) for i in range(161)), b'original'))

    def test_only_four_affected_units_and_111_global_function_oracles_are_selected(self):
        selected = candidate.object_selection()
        self.assertEqual(set(selected), {'net/factory.o', 'kernel/fork.o',
            'kernel/kthread.o', 'mm/vmalloc.o'})
        self.assertEqual(sum(map(len, selected.values())), 111)
        self.assertEqual(len(selected['net/factory.o']), 94)
        self.assertIn('kthread_create_worker', selected['kernel/kthread.o'])
        self.assertNotIn('__kthread_create_worker', selected['kernel/kthread.o'])
        self.assertTrue(candidate.task_source.definition('__kthread_create_worker').startswith(
            'static __printf(3, 0) struct kthread_worker *'))
        old = candidate.previous.object_selection()['net/factory.o']
        self.assertEqual(selected['net/factory.o'][:87], old)
        self.assertTrue(all(len(names) == len(set(names)) for names in selected.values()))
        recipe = candidate.recipe_inputs()
        self.assertEqual(len(recipe), 4)
        self.assertEqual(recipe[candidate.PARENT_RECIPE]['sha256'], candidate.PARENT_RECIPE_SHA)
        self.assertEqual(recipe[candidate.RETIREMENT_RECIPE]['sha256'], candidate.RETIREMENT_RECIPE_SHA)

    def test_parent_recipe_drift_is_not_an_accepted_alias(self):
        old = candidate.objects.identity
        def changed(path):
            value = old(path)
            return {**value, 'sha256': '0' * 64} if path.name == 'qualify_host_stream_kernel_retirement.py' else value
        with patch.object(candidate.objects, 'identity', side_effect=changed), \
                self.assertRaisesRegex(ValueError, 'reviewed-parent-recipe-changed'):
            candidate.recipe_inputs()

    def test_actual_global_text_symbols_and_readonly_geometry_data_are_distinct(self):
        expected = candidate.object_selection()['kernel/fork.o']
        rows = ['%016x T %s\n' % (i, name) for i, name in enumerate(expected)]
        raw = ''.join(rows).encode()
        self.assertEqual(set(candidate.defined_symbols(raw, expected)), set(expected))
        for wrong in (raw.replace(b' T ', b' t ', 1), raw.replace(b' T ', b' R ', 1),
                raw + rows[0].encode(), ''.join(rows[1:]).encode(),
                ('                 U ' + expected[0] + '\n').encode()):
            with self.subTest(raw=wrong[:80]), self.assertRaises(ValueError):
                candidate.defined_symbols(wrong, expected)

    def test_geometry_section_requires_fixed_count_magic_endianness_and_length(self):
        for target, (_, fields) in candidate.GEOMETRY.items():
            values = [candidate.GEOMETRY_MAGIC, len(fields), *range(len(fields))]
            raw = struct.pack('<' + 'Q' * len(values), *values)
            self.assertEqual(candidate.geometry_values(target, raw),
                dict(zip((name for name, _ in fields), range(len(fields)))))
            for wrong in (raw[:-1], raw + b'\0', b'\0' * len(raw),
                    struct.pack('>' + 'Q' * len(values), *values),
                    struct.pack('<QQ', candidate.GEOMETRY_MAGIC, len(fields) + 1) + raw[16:]):
                with self.subTest(target=target), self.assertRaises(ValueError):
                    candidate.geometry_values(target, wrong)

    def test_compile_only_suffix_preserves_exact_production_prefix_and_four_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            derived = {target[:-2] + '.c': b'/* exact reviewed prefix */\n'
                for target in candidate.GEOMETRY}
            for name, raw in derived.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_bytes(raw)
            recorded = candidate.compile_geometry(root, derived)
            self.assertEqual(set(recorded), set(derived))
            for target in candidate.GEOMETRY:
                name = target[:-2] + '.c'
                self.assertEqual((root / name).read_bytes(), derived[name] + candidate.geometry_suffix(target))
                self.assertEqual(recorded[name]['reviewedDerivedPrefix']['sha256'],
                    hashlib.sha256(derived[name]).hexdigest())
            with self.assertRaisesRegex(ValueError, 'geometry-exact-source-prefix'):
                candidate.compile_geometry(root, derived)

    def test_original_materials_and_twelve_extra_whole_inputs_are_preserved(self):
        derived, frozen, selected = self.parent()
        extra = candidate.task_source.EXTRAS | set(candidate.source.preimages()['source'])
        def read(tree, name, maximum):
            self.assertEqual(maximum, candidate.maintained.MAX_FILE)
            self.assertIn(name, extra)
            return name.encode()
        with patch.object(candidate.objects, 'recipient_derive_frozen',
                return_value=(derived, frozen, selected)) as parent, \
                patch.object(candidate.paths, 'read', side_effect=read) as reads, \
                patch.object(candidate.task_source, 'authenticate') as task_auth, \
                patch.object(candidate.source, 'authenticate') as stack_auth, \
                patch.object(candidate.retirement_source, 'transform', return_value=derived), \
                patch.object(candidate.task_source, 'transform',
                    return_value=dict.fromkeys(range(199), b'task')), \
                patch.object(candidate.source, 'transform',
                    return_value=dict.fromkeys(range(208), b'stack')):
            outputs, materials, original = candidate.derive_frozen('tree', 'same-input')
        parent.assert_called_once_with('tree', 'same-input')
        self.assertEqual((len(outputs), len(materials), len(original)), (208, 144, 173))
        self.assertEqual(reads.call_count, 12)
        self.assertEqual(set(task_auth.call_args.args[0]), candidate.task_source.EXTRAS)
        self.assertEqual(set(stack_auth.call_args.args[0]), set(candidate.source.preimages()['source']))
        self.assertEqual({name: materials[name] for name in frozen}, frozen)

    def test_source_after_hash_checks_also_run_on_failed_parent_derivation(self):
        old = candidate.objects.identity
        changed = False
        def identity(path):
            value = old(path)
            return {**value, 'sha256': '0' * 64} if changed else value
        def fail(*args):
            nonlocal changed
            changed = True
            raise RuntimeError('original-failure')
        with patch.object(candidate.objects, 'identity', side_effect=identity), \
                patch.object(candidate.objects, 'recipient_derive_frozen', side_effect=fail), \
                self.assertRaisesRegex(ValueError, 'source-changed-during-derivation'):
            candidate.derive_frozen('tree', 'original')
        with patch.object(candidate.objects, 'recipient_derive_frozen',
                side_effect=RuntimeError('original-failure')), \
                self.assertRaisesRegex(RuntimeError, 'original-failure'):
            candidate.derive_frozen('tree', 'original')

    def test_original_security_and_stack_configuration_cannot_be_disabled_or_changed(self):
        before, after = self.selected_configuration()
        candidate.configuration(before, after)
        raw = ''.join('#define ' + name + ' ' + ('1' if value == 'y' else value) + '\n'
            for name, value in after.items() if value != 'n').encode()
        candidate.generated_configuration(raw)
        for name in candidate.STACK_REQUIRED:
            with self.subTest(name=name), self.assertRaises(ValueError):
                candidate.configuration({**before, name: 'n'}, {**after, name: 'n'})
        for name in candidate.STACK_DISABLED:
            with self.subTest(name=name), self.assertRaises(ValueError):
                candidate.configuration({**before, name: 'y'}, {**after, name: 'y'})
        with self.assertRaises(ValueError):
            candidate.generated_configuration(raw + b'#define CONFIG_MEMCG 1\n')
        with self.assertRaises(ValueError):
            candidate.configuration(before, {**after, 'CONFIG_SECURITY_SELINUX': 'n'})

    def test_closed_owning_origin_and_one_job_cannot_build_boot_or_link_more(self):
        origin = {'GITHUB_ACTIONS': 'true', 'RUNNER_OS': 'Linux',
            'GITHUB_REPOSITORY': 'KirilsTurkins/latent-service-fabric',
            'GITHUB_EVENT_NAME': 'push', 'GITHUB_REF_NAME': candidate.BRANCH}
        for key, wrong in (('GITHUB_ACTIONS', 'false'), ('GITHUB_EVENT_NAME', 'workflow_dispatch'),
                ('GITHUB_REF_NAME', 'development'), ('GITHUB_REPOSITORY', 'outside/repository')):
            with self.subTest(key=key), patch.object(candidate.sys, 'platform', 'linux'), \
                    patch.dict(candidate.os.environ, {**origin, key: wrong}, clear=True), \
                    patch.object(candidate, 'recipe_inputs') as recipe, self.assertRaises(ValueError):
                candidate.run(None, None)
            recipe.assert_not_called()
        value = lanes.workflow_model((candidate.ROOT / candidate.WORKFLOW).read_text())
        self.assertEqual(set(value['on']), {'push'})
        self.assertEqual(value['on']['push']['branches'], [candidate.BRANCH])
        self.assertFalse(value['concurrency']['cancel-in-progress'])
        self.assertEqual(set(value['jobs']), {'cleanup-stack-objects'})
        job = value['jobs']['cleanup-stack-objects']
        self.assertEqual((job['runs-on'], job['timeout-minutes']), ('ubuntu-24.04', 20))
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        self.assertIn('tools/qualify_host_stream_kernel_cleanup_stack.py', commands)
        self.assertNotIn('cargo ', commands)
        self.assertNotIn('vmlinux', commands)
        self.assertNotIn('bzImage', commands)
        self.assertIn('--max-time 180', commands)
        upload = job['steps'][-1]
        self.assertEqual(upload['if'], 'always()')
        self.assertEqual(upload['with']['retention-days'], 3)
        self.assertEqual(upload['with']['path'].count('.o\n'), 4)
        self.assertIn('/geometry/*.bin', upload['with']['path'])


if __name__ == '__main__':
    unittest.main()

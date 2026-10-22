"""Source-preimage and reversible transformation controls, not Linux execution."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_core as core


class KernelDeviceCoreSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = core.fixture()
        cls.sections = cls.value['sections']

    def test_original_whole_members_definitions_and_closed_gates_are_preserved(self):
        parent = core.prior.fixture()
        self.assertEqual(len(self.value['source']), 74)
        self.assertEqual(len(self.sections), 58)
        self.assertEqual({name: self.value['source'][name] for name in parent['source']}, parent['source'])
        self.assertEqual(set(self.value['source']) - set(parent['source']), core.EXTRAS)
        self.assertEqual({name: self.sections[name] for name in parent['sections']}, parent['sections'])
        self.assertEqual(set(self.sections) - set(parent['sections']), core.DEFINITIONS)
        self.assertTrue(all(self.value[name] is False for name in core.GATES))

    def test_missing_unknown_drifted_duplicate_and_crlf_definitions_refuse(self):
        with self.assertRaises(ValueError):
            core.authenticate({})
        for name in (*sorted(core.DEFINITIONS), 'kobject_cleanup', 'device_release', 'kobject_release'):
            raw = self.sections[name]['text']
            self.assertEqual(core.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('{', '{ ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    core.section(wrong, name)
        with self.assertRaises(KeyError):
            core.section('', 'unreviewed_producer')

    def test_new_input_definition_membership_and_enabled_production_flags_refuse(self):
        variants = []
        missing = json.loads(json.dumps(self.value))
        del missing['source']['drivers/base/base.h']
        variants.append(missing)
        unknown = json.loads(json.dumps(self.value))
        unknown['source']['unreviewed.c'] = {'bytes': 1, 'sha256': '0' * 64}
        variants.append(unknown)
        missing_definition = json.loads(json.dumps(self.value))
        del missing_definition['sections']['device_add']
        variants.append(missing_definition)
        for gate in core.GATES:
            changed = json.loads(json.dumps(self.value))
            changed[gate] = True
            variants.append(changed)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'fixture.json'
            for changed in variants:
                target.write_bytes(json.dumps(changed).encode())
                with patch.object(core, 'FIXTURE', target), self.assertRaises(ValueError):
                    core.fixture()

    def test_private_allocator_reverses_to_complete_original_initialization(self):
        original = self.sections['device_private_init']['text']
        selected = core.private_init(original)
        self.assertLess(selected.index('lsf_factory_device_core_owned(dev) != 1'), selected.index('if (dev->p)'))
        self.assertLess(selected.index('if (dev->p)'), selected.index('dev->p = '))
        selected = core.replace(selected,
            '\tif (lsf_factory_device_core_owned(dev) != 1)\n\t\treturn -EOPNOTSUPP;\n'
            '\tif (dev->p)\n\t\treturn -EOPNOTSUPP;\n', '')
        selected = core.replace(selected, 'int lsf_prepaid_device_private_init(struct device *dev)',
            'static int device_private_init(struct device *dev)')
        selected = core.replace(selected, 'dev->p = lsf_factory_device_core_allocate(dev, sizeof(*dev->p));',
            'dev->p = kzalloc(sizeof(*dev->p), GFP_KERNEL);')
        self.assertEqual(selected, original)

    def test_private_allocator_rejects_another_producer_instead_of_generic_rewrite(self):
        for name in ('device_initialize', 'device_add', 'device_release'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                core.private_init(self.sections[name]['text'])

    def test_cleanup_tail_follows_all_original_name_parent_and_type_release(self):
        original = self.sections['kobject_cleanup']['text']
        selected = core.private_cleanup(original)
        order = ('t->release(kobj)', 'kfree_const(name)', 'kobject_put(parent)',
            'lsf_factory_device_core_tail_finish(kobj)')
        positions = [selected.index(value) for value in order]
        self.assertEqual(positions, sorted(positions))
        selected = core.replace(selected, 'static void lsf_prepaid_kobject_cleanup(struct kobject *kobj)',
            'static void kobject_cleanup(struct kobject *kobj)')
        selected = core.replace(selected, '\tlsf_factory_device_core_tail_finish(kobj);\n', '')
        self.assertEqual(selected, original)
        with self.assertRaises(ValueError):
            core.private_cleanup(self.sections['kobject_release']['text'])

    def test_both_actual_core_metadata_frees_are_authenticated_separately(self):
        # name_error runs before the original kobject-release tail; release's
        # cached p is freed after the PCI callback. Neither path can be omitted.
        failed = self.sections['device_add']['text']
        released = self.sections['device_release']['text']
        self.assertEqual(failed.count('\tkfree(dev->p);\n'), 1)
        self.assertLess(failed.index('name_error:'), failed.index('kfree(dev->p)'))
        self.assertLess(failed.index('kfree(dev->p)'), failed.index('dev->p = NULL'))
        self.assertEqual(released.count('\tkfree(p);\n'), 1)
        self.assertLess(released.index('devres_release_all(dev)'), released.index('dev->release(dev)'))
        self.assertLess(released.index('dev->release(dev)'), released.index('kfree(p)'))
        for expression in ('p', 'dev->p'):
            source = '\tkfree(' + expression + ');\n'
            selected = core.metadata_free(expression)
            self.assertIn('if (!lsf_returned)\n\t\t\tkfree(' + expression + ');', selected)
            self.assertTrue(selected.endswith('#else\n' + source + '#endif\n'))


if __name__ == '__main__':
    unittest.main()

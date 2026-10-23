"""Authenticated original capability allocation/free and normal-body controls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_capabilities as caps


class KernelDeviceCapabilitiesSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = caps.fixture()
        cls.sections = cls.value['sections']

    def test_whole_original_members_and_all_prior_definitions_are_exact(self):
        parent = caps.prior.fixture()
        self.assertEqual(len(self.value['source']), 75)
        self.assertEqual(len(self.sections), 62)
        self.assertEqual({name: self.value['source'][name] for name in parent['source']}, parent['source'])
        self.assertEqual({name: self.sections[name] for name in parent['sections']}, parent['sections'])
        self.assertEqual(set(self.value['source']) - set(parent['source']), caps.EXTRAS)
        self.assertEqual(set(self.sections) - set(parent['sections']), caps.DEFINITIONS)
        self.assertTrue(all(self.value[name] is False for name in caps.GATES))

    def test_missing_unknown_drifted_duplicate_and_crlf_source_refuse(self):
        with self.assertRaises(ValueError):
            caps.authenticate({})
        for name in sorted(caps.DEFINITIONS):
            raw = self.sections[name]['text']
            self.assertEqual(caps.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('{', '{ ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    caps.section(wrong, name)
        with self.assertRaises(KeyError):
            caps.section('', 'unreviewed_capability')

    def test_new_membership_and_production_gate_changes_fail_closed(self):
        variants = []
        for target in ('source', 'sections'):
            value = json.loads(json.dumps(self.value))
            value[target]['unreviewed'] = {}
            variants.append(value)
        for gate in caps.GATES:
            value = json.loads(json.dumps(self.value))
            value[gate] = True
            variants.append(value)
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / 'fixture.json'
            for value in variants:
                target.write_bytes(json.dumps(value).encode())
                with patch.object(caps, 'FIXTURE', target), self.assertRaises(ValueError):
                    caps.fixture()

    def test_private_copy_changes_only_birth_and_guard_before_original_lookup(self):
        raw = self.sections['_pci_add_cap_save_buffer']['text']
        selected = caps.private_allocate(raw)
        self.assertLess(selected.index('lsf_factory_device_capabilities_owned(dev)'),
            selected.index('pci_find_ext_capability(dev, cap)'))
        self.assertLess(selected.index('lsf_factory_device_capability_allocate(dev,'),
            selected.index('pci_add_saved_cap(dev, save_state)'))
        selected = caps.replace(selected, 'int lsf_prepaid_pci_add_cap_save_buffer(',
            'static int _pci_add_cap_save_buffer(')
        selected = caps.replace(selected, '\n\tif (lsf_factory_device_capabilities_owned(dev) != 1)\n'
            '\t\treturn -EOPNOTSUPP;\n', '')
        selected = caps.replace(selected,
            'save_state = lsf_factory_device_capability_allocate(dev, sizeof(*save_state) + size);',
            'save_state = kzalloc(sizeof(*save_state) + size, GFP_KERNEL);')
        self.assertEqual(selected, raw)

    def test_normal_allocator_body_is_unchanged_after_closed_dispatch(self):
        raw = self.sections['_pci_add_cap_save_buffer']['text']
        selected = caps.allocator_dispatch(raw)
        original_body = raw.split('\n{\n', 1)[1][:-2]
        self.assertIn('\t{\n#endif\n' + original_body + '#ifdef CONFIG_LSF_STREAM_FACTORY', selected)
        self.assertLess(selected.index('if (lsf_owned < 0)'), selected.index('if (lsf_owned)'))
        self.assertLess(selected.index('if (lsf_owned)'), selected.index(original_body))
        self.assertIn('kzalloc(sizeof(*save_state) + size, GFP_KERNEL)', original_body)

    def test_final_hlist_free_supplies_device_and_member_without_normal_fallback_on_error(self):
        raw = self.sections['pci_free_cap_save_buffers']['text']
        selected = caps.final_return(raw)
        hook = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\t\tif (!lsf_factory_device_capability_return(dev, tmp))\n\t\t\tkfree(tmp);\n'
            '#else\n\t\tkfree(tmp);\n#endif\n')
        self.assertEqual(caps.replace(selected, hook, '\t\tkfree(tmp);\n'), raw)
        self.assertIn('hlist_for_each_entry_safe(tmp, n, &dev->saved_cap_space, next)', selected)
        self.assertEqual(raw.count('kfree(tmp);'), 1)

    def test_another_definition_cannot_be_used_as_the_allocator_or_final_free(self):
        raw = self.sections['pci_allocate_cap_save_buffers']['text']
        for operation in (caps.private_allocate, caps.allocator_dispatch, caps.final_return):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation(raw)


if __name__ == '__main__':
    unittest.main()

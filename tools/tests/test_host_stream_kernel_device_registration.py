"""Whole-maintained IDR algorithms, mutation admission and real final-return controls."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_registration as reg


class KernelDeviceRegistrationSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = reg.fixture()
        cls.sections = cls.value['sections']

    def setUp(self):
        # The already-validated immutable value avoids rereading the complete
        # layered fixture for every separate whole-definition projection.
        self.saved_fixture = reg.fixture
        self.fixture_cache = patch.object(reg, 'fixture', return_value=self.value)
        self.fixture_cache.start()
        self.addCleanup(self.fixture_cache.stop)

    def test_exact_original_members_definitions_and_uninstalled_gates(self):
        parent = reg.prior.fixture()
        self.assertEqual((len(self.value['source']), len(self.sections)), (80, 69))
        self.assertEqual({n: self.value['source'][n] for n in parent['source']}, parent['source'])
        self.assertEqual({n: self.sections[n] for n in parent['sections']}, parent['sections'])
        self.assertEqual(set(self.value['source']) - set(parent['source']), reg.EXTRAS)
        self.assertEqual(set(self.sections) - set(parent['sections']), reg.DEFINITIONS)
        self.assertTrue(all(self.value[name] is False for name in reg.GATES))

    def test_missing_duplicate_drift_crlf_unknown_definitions_refuse(self):
        for name in reg.DEFINITIONS:
            raw = self.sections[name]['text']
            self.assertEqual(reg.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('{', '{ ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    reg.section(wrong, name)
        with self.assertRaises(KeyError):
            reg.section('', 'another_idr')
        with self.assertRaises(ValueError):
            reg.authenticate({})

    def test_rehashed_membership_or_production_promotion_is_not_a_fixture(self):
        variants = []
        for target in ('source', 'sections'):
            value = json.loads(json.dumps(self.value))
            value[target]['unreviewed'] = {}
            variants.append(value)
        for gate in reg.GATES:
            value = json.loads(json.dumps(self.value))
            value[gate] = True
            variants.append(value)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.json'
            for value in variants:
                path.write_bytes(json.dumps(value).encode())
                with patch.object(reg, 'FIXTURE', path), self.assertRaises(ValueError):
                    self.saved_fixture()

    def test_bank_node_uses_actual_ctor_then_all_original_metadata_assignments(self):
        raw = self.sections['radix_tree_node_alloc']['text']
        selected = reg.private_node_alloc(raw)
        for absent in ('kmem_cache_alloc(', 'this_cpu_ptr(', 'kmemleak_update_trace('):
            self.assertNotIn(absent, selected)
        self.assertLess(selected.index('lsf_factory_device_registration_allocate('),
            selected.index('radix_tree_node_ctor(ret);'))
        self.assertLess(selected.index('radix_tree_node_ctor(ret);'), selected.index('ret->shift = shift;'))
        tail = raw[raw.index('out:\n') + len('out:\n'):]
        self.assertTrue(selected.endswith(tail.replace('\tif (ret) {\n',
            '\tif (ret) {\n\t\tradix_tree_node_ctor(ret);\n', 1)))
        self.assertIn('IS_ENABLED(CONFIG_DEBUG_KMEMLEAK)', selected)

    def test_extension_retains_whole_original_algorithm_after_exact_call_projection(self):
        raw = self.sections['radix_tree_extend']['text']
        selected = reg.private_extend(raw)
        selected = reg.replace(selected,
            'static int lsf_prepaid_device_radix_extend(struct lsf_device_registration_source source,\n'
            '\t\t\t\tstruct radix_tree_root *root, gfp_t gfp,',
            'static int radix_tree_extend(struct radix_tree_root *root, gfp_t gfp,')
        selected = reg.replace(selected, 'lsf_prepaid_device_radix_node_alloc(source, gfp, NULL,',
            'radix_tree_node_alloc(gfp, NULL,')
        self.assertEqual(selected, raw)

    def test_get_free_admits_before_actual_walk_even_without_a_new_allocation(self):
        raw = self.sections['idr_get_free']['text']
        selected = reg.private_get_free(raw)
        guard = ('\tif (source.kind != LSF_REGISTRATION_KIND_NODE ||\n'
            '\t    lsf_factory_device_registration_current(source) != 1)\n'
            '\t\treturn ERR_PTR(-EOPNOTSUPP);\n\n')
        self.assertLess(selected.index(guard), selected.index('radix_tree_load_root(root,'))
        selected = reg.replace(selected, guard, '')
        selected = reg.replace(selected,
            'void __rcu **lsf_prepaid_device_idr_get_free(struct lsf_device_registration_source source,\n'
            '\t\t\t      struct radix_tree_root *root,', 'void __rcu **idr_get_free(struct radix_tree_root *root,')
        selected = reg.replace(selected, 'lsf_prepaid_device_radix_extend(source, root, gfp, start, shift)',
            'radix_tree_extend(root, gfp, start, shift)')
        selected = reg.replace(selected, 'lsf_prepaid_device_radix_node_alloc(source, gfp, node, root, shift,',
            'radix_tree_node_alloc(gfp, node, root, shift,')
        self.assertEqual(selected, raw)

    def test_cyclic_source_precedes_original_two_attempts_and_entry_is_actual_node(self):
        raw = self.sections['idr_alloc_cyclic']['text']
        selected = reg.private_cyclic(raw)
        guard = ('\n\tif (source.kind != LSF_REGISTRATION_KIND_NODE || source.address != ptr ||\n'
            '\t    lsf_factory_device_registration_current(source) != 1)\n'
            '\t\treturn -EOPNOTSUPP;\n')
        self.assertLess(selected.index(guard), selected.index('if ((int)id < start)'))
        self.assertEqual(selected.count('lsf_prepaid_device_idr_alloc_u32(source, idr, ptr, &id, max, gfp)'), 2)
        selected = reg.replace(selected, guard, '')
        selected = reg.replace(selected,
            'int lsf_prepaid_device_idr_alloc_cyclic(struct lsf_device_registration_source source,\n'
            '\t\t\tstruct idr *idr, void *ptr, int start, int end, gfp_t gfp)',
            'int idr_alloc_cyclic(struct idr *idr, void *ptr, int start, int end, gfp_t gfp)')
        selected = selected.replace('lsf_prepaid_device_idr_alloc_u32(source, idr, ptr, &id, max, gfp)',
            'idr_alloc_u32(idr, ptr, &id, max, gfp)')
        self.assertEqual(selected, raw)

    def test_u32_preserves_id_before_pointer_and_real_tag_publication(self):
        raw = self.sections['idr_alloc_u32']['text']
        selected = reg.private_alloc_u32(raw)
        selected = reg.replace(selected,
            'static int lsf_prepaid_device_idr_alloc_u32(struct lsf_device_registration_source source,\n'
            '\t\t\tstruct idr *idr, void *ptr, u32 *nextid,',
            'int idr_alloc_u32(struct idr *idr, void *ptr, u32 *nextid,')
        selected = reg.replace(selected,
            'lsf_prepaid_device_idr_get_free(source, &idr->idr_rt, &iter, gfp, max - base)',
            'idr_get_free(&idr->idr_rt, &iter, gfp, max - base)')
        self.assertEqual(selected, raw)
        self.assertLess(raw.index('*nextid = iter.index + base;'), raw.index('radix_tree_iter_replace('))

    def test_rcu_preflight_before_cleanup_and_finish_only_at_original_slab_return(self):
        raw = self.sections['radix_tree_node_rcu_free']['text']
        selected = reg.final_radix_free(raw)
        prefix = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tstruct lsf_device_registration_source lsf_source;\n'
            '\tint lsf_owned = lsf_factory_device_registration_return_begin(node,\n'
            '\t\tLSF_REGISTRATION_KIND_IDR_NODE, &lsf_source);\n'
            '\tif (lsf_owned < 0)\n\t\treturn;\n#endif\n')
        ending = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (lsf_owned) {\n'
            '\t\t(void)lsf_factory_device_registration_return_finish(lsf_source);\n'
            '\t\treturn;\n\t}\n#endif\n')
        self.assertLess(selected.index(prefix), selected.index('memset(node->slots,'))
        self.assertLess(selected.index('INIT_LIST_HEAD('), selected.index(ending))
        self.assertEqual(reg.replace(reg.replace(selected, prefix, ''), ending, ''), raw)

    def test_revoke_failure_releases_known_constructor_mutex_without_clearing_active_fence(self):
        # The real caller owns the mutex after successful enter and reaches
        # leave synchronously on every exit; this is not a foreign unlock.
        source = (Path(reg.__file__).read_text())
        self.assertIn('int revoked = lsf_factory_device_registration_constructor_revoke();', source)
        begin = source.index("'    int revoked = lsf_factory_device_registration_constructor_revoke();")
        stop = source.index("outputs['net/factory-device.c'] = text.encode()", begin)
        leave = source[begin:stop]
        self.assertLess(leave.index('mutex_unlock(&factory_lock);'), leave.index('if (!revoked)'))
        self.assertNotIn('constructor_active = 0', leave)
        self.assertNotIn('constructor_task = NULL', leave)
        # Old early return was the real source counterexample: it precedes
        # release, while the corrected branch returns only after release.
        old = "if (!revoke()) return; mutex_unlock(&factory_lock);"
        self.assertLess(old.index('return;'), old.index('mutex_unlock'))
        owned = (reg.OWNED / 'factory-device-registration.c').read_text()
        revoke = owned[owned.index('int lsf_factory_device_registration_constructor_revoke('):]
        revoke = revoke[:revoke.index('\n}\n') + 3]
        self.assertIn('factory.device->constructor_task == current', revoke)
        self.assertIn('lsf_factory_device_firmware_poison();', revoke)
        self.assertNotIn('constructor_active = 0', revoke)

    def test_another_definition_is_never_an_accepted_transform_input(self):
        raw = self.sections['radix_tree_node_ctor']['text']
        for operation in (reg.private_node_alloc, reg.private_extend, reg.private_get_free,
                reg.private_alloc_u32, reg.private_cyclic, reg.final_radix_free):
            with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                operation(raw)


if __name__ == '__main__':
    unittest.main()

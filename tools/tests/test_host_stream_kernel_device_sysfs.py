"""Preserve actual kernfs/security bodies and bind the first private kobject scope."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_sysfs as sysfs


class KernelDeviceSysfsSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = sysfs.fixture()
        cls.sections = cls.value['sections']

    def setUp(self):
        self.saved_fixture = sysfs.fixture
        cache = patch.object(sysfs, 'fixture', return_value=self.value)
        cache.start()
        self.addCleanup(cache.stop)

    def test_authenticates_all_whole_prior_definitions_and_current_callback_table(self):
        old = sysfs.prior.fixture()
        self.assertEqual((len(self.value['source']), len(self.sections)), (86, 87))
        self.assertEqual({n: self.value['source'][n] for n in old['source']}, old['source'])
        self.assertEqual({n: self.sections[n] for n in old['sections']}, old['sections'])
        self.assertEqual(set(self.value['source']) - set(old['source']), sysfs.EXTRAS)
        self.assertEqual(set(self.sections) - set(old['sections']), sysfs.DEFINITIONS)
        self.assertTrue(all(self.value[n] is False for n in sysfs.GATES))
        self.assertIn('.get_ownership\t= device_get_ownership,', self.sections['device_ktype']['text'])
        self.assertIn('dev->class->get_ownership(dev, uid, gid);', self.sections['device_get_ownership']['text'])

    def test_unknown_missing_duplicate_drift_crlf_function_and_callback_object_refuse(self):
        for name in sysfs.DEFINITIONS:
            raw = self.sections[name]['text']
            self.assertEqual(sysfs.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('{', '{ ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    sysfs.section(wrong, name)
        with self.assertRaises(KeyError):
            sysfs.section('', 'unclosed_kernfs')
        with self.assertRaises(ValueError):
            sysfs.authenticate({})

    def test_rehashing_new_members_or_asserting_enablement_never_authenticates_fixture(self):
        values = []
        for key in ('source', 'sections'):
            value = json.loads(json.dumps(self.value));value[key]['unreviewed'] = {};values.append(value)
        for gate in sysfs.GATES:
            value = json.loads(json.dumps(self.value));value[gate] = True;values.append(value)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'fixture.json'
            for value in values:
                path.write_bytes(json.dumps(value).encode())
                with patch.object(sysfs, 'FIXTURE', path), self.assertRaises(ValueError):
                    self.saved_fixture()

    def test_private_birth_removes_normal_heap_and_per_cpu_preload_before_id_publication(self):
        raw = self.sections['__kernfs_new_node']['text']
        selected = sysfs.private_birth(raw)
        for absent in ('kstrdup_const(', 'kmem_cache_zalloc(', 'idr_preload(', 'idr_preload_end(', 'kmem_cache_free(', 'kfree_const('):
            self.assertNotIn(absent, selected)
        self.assertLess(selected.index('lsf_factory_device_registration_current(source)'), selected.index('lsf_factory_device_sysfs_name(source,'))
        self.assertLess(selected.index('lsf_factory_device_registration_allocate('), selected.index('lsf_prepaid_device_idr_alloc_cyclic('))
        self.assertLess(selected.index('lsf_factory_device_registration_node(kn, &node_source)'), selected.index('spin_lock(&kernfs_idr_lock)'))
        self.assertIn('ret = lsf_prepaid_device_idr_alloc_cyclic(node_source,', selected)
        for statement in ('root->id_highbits++;', 'root->last_id_lowbits = ret;',
                'kn->id = (u64)id_highbits << 32 | ret;', 'atomic_set(&kn->count, 1);',
                'RB_CLEAR_NODE(&kn->rb);', 'kn->flags = flags;',
                'ret = security_kernfs_init_security(parent, kn);',
                'idr_remove(&root->ino_idr, (u32)kernfs_ino(kn));'):
            self.assertIn(statement, selected)
        for label in (' err_out3:', ' err_out2:', ' err_out1:'):
            self.assertIn(label, selected)
        self.assertLess(selected.index('!uid_eq(uid, GLOBAL_ROOT_UID)'), selected.index('lsf_factory_device_sysfs_name(source,'))

    def test_default_and_outside_dispatch_preserves_every_original_body(self):
        for name, operation in (('kernfs_new_node', sysfs.normal_new_node),
                ('kernfs_create_link', sysfs.normal_link), ('sysfs_create_dir_ns', sysfs.normal_sysfs_dir),
                ('create_dir', sysfs.kobject_create_guard), ('__kernfs_iattrs', sysfs.iattrs_guard),
                ('kernfs_xattr_get', sysfs.xattr_get_guard), ('kernfs_xattr_set', sysfs.xattr_set_guard),
                ('security_kernfs_init_security', sysfs.security_guard)):
            with self.subTest(name=name):
                raw = self.sections[name]['text'];selected = operation(raw)
                original_body = raw.split('\n{\n', 1)[1][:-2]
                self.assertIn('\t{\n#endif\n' + original_body + '#ifdef CONFIG_LSF_STREAM_FACTORY', selected)
                self.assertLess(selected.index('return '), selected.index(original_body))

    def test_initial_source_is_actual_kobject_before_namespace_and_ownership_callbacks(self):
        selected = sysfs.kobject_create_guard(self.sections['create_dir']['text'])
        self.assertLess(selected.index('lsf_factory_device_registration_kobject(kobj,'), selected.index('kobject_namespace(kobj)'))
        selected = sysfs.private_sysfs_dir(self.sections['sysfs_create_dir_ns']['text'])
        self.assertLess(selected.index('lsf_prepaid_device_kobject_registration_ready(kobj)'), selected.index('kobject_get_ownership(kobj,'))
        self.assertIn('lsf_prepaid_device_kernfs_create_dir_ns(source, parent,', selected)
        ready = sysfs.kobject_ready(self.sections['device_ktype']['text'])
        self.assertLess(ready.index('lsf_factory_device_registration_current(source)'), ready.index('kobj->ktype != &device_ktype'))
        self.assertIn('kobj_to_dev(kobj)->class', ready)
        self.assertIn('kobj->parent->ktype->child_ns_type', ready)

    def test_private_descendant_keeps_sgid_parent_reference_and_same_dir_link_errors(self):
        raw = self.sections['kernfs_new_node']['text'];selected = sysfs.private_new_node(raw)
        self.assertIn('if (parent->mode & S_ISGID)', selected)
        self.assertIn('gid = parent->iattr->ia_gid;', selected)
        self.assertIn('kernfs_get(parent);', selected)
        self.assertIn('kn->parent = parent;', selected)
        selected = sysfs.private_create_dir(self.sections['kernfs_create_dir_ns']['text'])
        for statement in ('kn->dir.root = parent->dir.root;', 'kn->ns = ns;', 'kn->priv = priv;',
                'rc = kernfs_add_one(kn);', 'kernfs_put(kn);', 'return ERR_PTR(rc);'):
            self.assertIn(statement, selected)

    def test_link_classifies_both_origins_before_target_dereference_and_keeps_actual_target_ref(self):
        raw = self.sections['kernfs_create_link']['text'];selected = sysfs.normal_link(raw)
        self.assertLess(selected.index('lsf_factory_device_sysfs_pair(parent, target,'), selected.index('if (target->iattr)'))
        selected = sysfs.private_link(raw)
        for statement in ('kn->ns = target->ns;', 'kn->symlink.target_kn = target;',
                'kernfs_get(target);', 'error = kernfs_add_one(kn);', 'kernfs_put(kn);'):
            self.assertIn(statement, selected)
        self.assertIn('lsf_prepaid_device_kernfs_new_node(source, parent,', selected)

    def test_duplicate_diagnostic_uses_original_bank_and_preserves_warning_cleanup(self):
        selected = sysfs.private_warning(self.sections['sysfs_warn_dup']['text'])
        self.assertNotIn('kzalloc(', selected);self.assertNotIn('kfree(', selected)
        self.assertIn('lsf_factory_device_registration_allocate(source, PATH_MAX, LSF_REGISTRATION_KIND_NAME)', selected)
        for statement in ('kernfs_path(parent, buf, PATH_MAX);', 'pr_warn(', 'dump_stack();'):
            self.assertIn(statement, selected)
        self.assertLess(selected.index('dump_stack();'), selected.index('lsf_factory_device_sysfs_release(source, buf,'))

    def test_final_rcu_classifies_before_original_free_and_retains_complete_outside_body(self):
        raw = self.sections['kernfs_free_rcu']['text'];selected = sysfs.final_node(raw)
        self.assertLess(selected.index('lsf_factory_device_registration_node(kn,'), selected.index('kfree_const(kn->name);'))
        self.assertIn('if (owned < 0)\n\t\treturn;', selected)
        self.assertIn('lsf_prepaid_device_kernfs_free(kn);\n\t\treturn;', selected)
        self.assertTrue(selected.endswith(raw[raw.index('\n\tkfree_const(kn->name);'):]))
        self.assertIn('call_rcu(&kn->rcu, kernfs_free_rcu);', self.sections['kernfs_put']['text'])
        self.assertIn('idr_remove(&root->ino_idr, (u32)kernfs_ino(kn));', self.sections['kernfs_put']['text'])

    def test_actual_lsm_entry_rejects_unknown_hooks_but_keeps_mandatory_original_loop(self):
        raw = self.sections['security_kernfs_init_security']['text'];selected = sysfs.security_guard(raw)
        self.assertLess(selected.index('lsm_for_each_hook(scall, kernfs_init_security)'), selected.index('call_int_hook(kernfs_init_security,'))
        self.assertIn('scall->hl->hook.kernfs_init_security', selected)
        self.assertIn('#else\n\t\t\treturn -EOPNOTSUPP;', selected)
        self.assertEqual(selected.count('call_int_hook(kernfs_init_security, kn_dir, kn);'), 1)

    def test_selinux_actual_enodata_precedes_refusal_before_unclosed_context_allocation(self):
        raw = self.sections['selinux_kernfs_init_security']['text'];selected = sysfs.selinux_guard(raw)
        guard = '#ifdef CONFIG_LSF_STREAM_FACTORY\n\tif (owned)\n\t\treturn -EOPNOTSUPP;\n#endif\n'
        self.assertLess(selected.index('if (rc == -ENODATA)'), selected.index(guard))
        self.assertLess(selected.index(guard), selected.index('context = kmalloc(clen,'))
        extra = ('#ifdef CONFIG_LSF_STREAM_FACTORY\n'
            '\tstruct lsf_device_registration_source source;\n'
            '\tint owned = lsf_factory_device_registration_node(kn, &source);\n'
            '\tif (owned < 0 || (owned && lsf_factory_device_registration_current(source) != 1))\n'
            '\t\treturn -EOPNOTSUPP;\n#endif\n')
        self.assertEqual(sysfs.replace(sysfs.replace(selected, guard, ''), extra, ''), raw)


if __name__ == '__main__':
    unittest.main()

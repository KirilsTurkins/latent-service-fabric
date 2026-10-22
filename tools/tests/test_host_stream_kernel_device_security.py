"""Closed domain ownership and preservation of real SIGIO/LSM algorithms."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_security as security


class KernelDeviceSecuritySource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_fixture = staticmethod(security.fixture)
        cls.value = security.fixture()

    def setUp(self):
        cache = patch.object(security, 'fixture', return_value=self.value)
        cache.start()
        self.addCleanup(cache.stop)

    def raw(self, name):
        return self.value['sections'][name]['text']

    def test_fixed_originals_parent_and_uninstalled_claims(self):
        parent = security.prior.fixture()
        self.assertEqual((len(self.value['source']), len(self.value['sections'])), (96, 159))
        for field in ('source', 'sections'):
            self.assertEqual({name: self.value[field][name] for name in parent[field]}, parent[field])
        self.assertTrue(all(self.value[name] is False for name in security.GATES))

    def test_changed_duplicate_unknown_and_crlf_preimages_refuse(self):
        for name in security.DEFINITIONS:
            raw = self.raw(name)
            self.assertEqual(security.section(raw, name), raw)
            for wrong in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('\t', ' ', 1)):
                if wrong == raw:
                    wrong = raw.replace('(', '( ', 1)
                with self.subTest(name=name), self.assertRaises(ValueError):
                    security.section(wrong, name)
        with self.assertRaises(KeyError):
            security.section('', 'new_hook')

    def test_rehashed_members_or_enabled_qualification_claims_refuse(self):
        values = []
        for field in ('source', 'sections'):
            value = json.loads(json.dumps(self.value))
            value[field]['new_member'] = {}
            values.append(value)
        for name in security.GATES:
            value = json.loads(json.dumps(self.value))
            value[name] = True
            values.append(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            for value in values:
                path.write_bytes(json.dumps(value).encode())
                with patch.object(security, 'FIXTURE', path), self.assertRaises(ValueError):
                    self.original_fixture()

    def test_sigio_original_credential_namespace_rt_fallback_and_fasync_bodies_are_exact(self):
        names = ('sigio_perm', 'send_sigio_to_task', 'send_sigio', 'kill_fasync_rcu', 'kill_fasync')
        private = security.private_fcntl({'fs/fcntl.c': ''.join(self.raw(name) for name in names).encode()})
        for name in names:
            begin = private.index('lsf_prepaid_device_' + name + '(')
            begin = private.rfind('\n', 0, begin) + 1
            end = private.index('\n}\n', begin) + 3
            text = private[begin:end]
            text = text.replace('lsf_prepaid_device_' + name +
                '(struct lsf_device_registration_source source, ', name + '(')
            if name == 'send_sigio':
                text = text.replace('static void send_sigio(', 'void send_sigio(')
            guard = ('\tif (!lsf_factory_device_recipient_current(source, NULL))\n'
                '\t\treturn' + (' 0' if name == 'sigio_perm' else '') + ';\n')
            self.assertEqual(text.count(guard), 1)
            if name == 'sigio_perm':
                text = text.replace('\tint ret;\n\n' + guard, '\tint ret;\n')
            elif name == 'send_sigio_to_task':
                text = text.replace('\tint signum;\n\n' + guard + '\tsignum = READ_ONCE(fown->signum);\n',
                    '\tint signum = READ_ONCE(fown->signum);\n')
            elif name == 'send_sigio':
                text = text.replace('\tstruct pid *pid;\n\n' + guard, '\tstruct pid *pid;\n')
            else:
                self.assertEqual(text.index(guard), text.index('\n{\n') + 3)
                text = text.replace(guard, '')
            for callee in ('security_file_send_sigiotask', 'sigio_perm', 'do_send_sig_info',
                           'send_sigio_to_task', 'send_sigio', 'kill_fasync_rcu'):
                text = text.replace('lsf_prepaid_device_' + callee + '(source, ', callee + '(')
            self.assertEqual(text, self.raw(name))

    def test_selinux_permission_body_and_process_class_are_preserved(self):
        original = self.raw('selinux_file_send_sigiotask')
        text = security.private_selinux(original)
        end = text.index('\n}\n') + 3
        text = text[:end]
        text = text.replace('int lsf_prepaid_device_selinux_file_send_sigiotask(',
            'static int selinux_file_send_sigiotask(')
        text = text.replace(', const struct lsf_factory_blob *source)', ')')
        text = text.replace('\tu32 sid;\n', '\tu32 sid = task_sid_obj(tsk);\n')
        guard = ('\n\tif (!source || !lsf_factory_blob_shape(*source) ||\n'
            '\t    source->domain != LSF_FACTORY_OWNER_DEVICE ||\n'
            '\t    source->device.kind != LSF_DEVICE_RECIPIENT_KIND_WORK ||\n'
            '\t    !lsf_factory_device_recipient_current(source->device, NULL))\n'
            '\t\treturn -EOPNOTSUPP;\n\tsid = task_sid_obj(tsk);\n')
        self.assertEqual(text.count(guard), 1)
        text = text.replace(guard, '')
        text = text.replace('lsf_prepaid_avc_has_perm(', 'avc_has_perm(')
        text = text.replace('SECCLASS_PROCESS, perm, NULL, source);', 'SECCLASS_PROCESS, perm, NULL);')
        self.assertEqual(text, original)

    def test_security_dispatch_keeps_real_default_active_order_and_unknown_refusal(self):
        text = security.security_dispatch()
        self.assertIn('LSM_RET_DEFAULT(file_send_sigiotask)', text)
        self.assertEqual(text.count('lsm_for_each_hook(scall, file_send_sigiotask)'), 2)
        self.assertLess(text.index('lsf_prepaid_device_selinux_sigio_hook'),
            text.index('rc = lsf_prepaid_device_selinux_file_send_sigiotask'))
        preflight = text[text.index('lsf_prepaid_device_selinux_sigio_hook'):
            text.index('rc = lsf_prepaid_device_selinux_file_send_sigiotask')]
        self.assertIn('lsf_factory_device_uevent_poison();\n            return -EOPNOTSUPP;', preflight)
        self.assertIn('if (rc == -EOPNOTSUPP)\n            lsf_factory_device_uevent_poison();', text)
        self.assertIn('if (rc != LSM_RET_DEFAULT(file_send_sigiotask))\n            break;', text)
        self.assertNotIn('call_int_hook(', text.split('*/', 1)[-1])
        raw = self.raw('security_file_send_sigiotask')
        self.assertIn('return call_int_hook(file_send_sigiotask, tsk, fown, sig);', raw)
        self.assertIn('if (static_key_enabled(&scall->active->key))', self.raw('lsm_for_each_hook'))

    def test_device_cache_detach_keeps_original_application_cache_and_rcu_algorithms(self):
        names = {'net/factory-private.h': 'factory-private.h', 'net/factory.c': 'factory.c',
            'security/selinux/lsf_avc_private.c': 'avc-private.c',
            'security/selinux/ss/lsf_sidcache_private.c': 'sidcache-private.c',
            'security/selinux/ss/lsf_audit_string_private.c': 'audit-string-private.c'}
        outputs = {name: (security.OWNED / source).read_bytes() for name, source in names.items()}
        original = dict(outputs)
        security.device_cache_drains(outputs)
        for name in names:
            if name.startswith('security/'):
                self.assertTrue(outputs[name].startswith(original[name] + b'\n'))
        avc = outputs['security/selinux/lsf_avc_private.c'].decode()[
            len(original['security/selinux/lsf_avc_private.c']):]
        self.assertLess(avc.index('lsf_factory_device_security_candidate'),
            avc.index('spin_lock_irqsave'))
        self.assertLess(avc.index('spin_lock_irqsave'),
            avc.index('lsf_factory_device_security_current'))
        self.assertLess(avc.index('lsf_factory_device_security_current'), avc.index('avc_node_delete(address)'))
        sid = outputs['security/selinux/ss/lsf_audit_string_private.c'].decode()[
            len(original['security/selinux/ss/lsf_audit_string_private.c']):]
        self.assertLess(sid.index('rcu_read_lock()'), sid.index('policy->sidtab == anchor'))
        self.assertLess(sid.index('policy->sidtab == anchor'),
            sid.index('lsf_prepaid_device_sidcache_detach'))
        detach = outputs['security/selinux/ss/lsf_sidcache_private.c'].decode()[
            len(original['security/selinux/ss/lsf_sidcache_private.c']):]
        for statement in ('list_del(&cache->lru_member)', 'rcu_assign_pointer(cache->parent->cache, NULL)',
                          'table->cache_free_slots++', 'lsf_prepaid_sidcache_retire(cache, owned)'):
            self.assertIn(statement, detach)
        self.assertLess(detach.index('owned = lsf_factory_sidcache_queue(cache)'),
            detach.index('list_del(&cache->lru_member)'))
        self.assertLess(detach.index('spin_unlock_irqrestore'),
            detach.index('lsf_prepaid_sidcache_retire(cache, owned)'))
        self.assertIn('#else\nvoid lsf_prepaid_device_sidcache_detach', detach)
        release = security.function(outputs['net/factory.c'].decode(), 'static int lsf_factory_release(')
        self.assertLess(release.index('spin_unlock_irqrestore'), release.index('lsf_prepaid_device_sidcache_drain();'))
        self.assertLess(release.index('lsf_prepaid_device_sidcache_drain();'),
            release.index('/* Closing a descriptor is not final-free.'))

    def test_socket_async_keeps_actual_flags_rcu_and_signal_selection(self):
        originals = {'net/socket.c': self.raw('sock_wake_async').encode(),
            'include/net/sock.h': self.raw('sk_wake_async_rcu').encode()}
        result = security.private_socket_async(originals)
        socket = security.function(result, 'static int lsf_prepaid_device_sock_wake_async(')
        socket = socket.replace('static int lsf_prepaid_device_sock_wake_async('
            'struct lsf_device_registration_source source, ', 'int sock_wake_async(')
        guard = ('\tif (!lsf_factory_device_recipient_current(source, NULL))\n'
            '\t\treturn -EOPNOTSUPP;\n')
        self.assertEqual(socket.count(guard), 1)
        socket = socket.replace(guard, '')
        socket = socket.replace('lsf_prepaid_device_kill_fasync(source, ', 'kill_fasync(')
        self.assertEqual(socket, self.raw('sock_wake_async'))
        core = security.function(result, 'void lsf_prepaid_device_sk_wake_async_rcu(')
        self.assertLess(core.index('lsf_factory_device_recipient_current(source, sk)'),
            core.index('sock_flag(sk, SOCK_FASYNC)'))
        core = core.replace('void lsf_prepaid_device_sk_wake_async_rcu('
            'struct lsf_device_registration_source source, ', 'static inline void sk_wake_async_rcu(')
        null_guard = '\tif (!sk) {\n\t\tlsf_factory_device_uevent_poison();\n\t\treturn;\n\t}\n'
        self.assertEqual(core.count(null_guard), 1)
        self.assertLess(core.index(null_guard), core.index('sock_flag(sk, SOCK_FASYNC)'))
        core = core.replace(null_guard, '')
        core = core.replace('\tif (!lsf_factory_device_recipient_current(source, sk))\n\t\treturn;\n', '')
        core = core.replace('lsf_prepaid_device_sock_wake_async(source, ', 'sock_wake_async(')
        self.assertEqual(core, self.raw('sk_wake_async_rcu'))
        self.assertLess(result.index('static int lsf_prepaid_device_sock_wake_async('),
            result.index('void lsf_prepaid_device_sk_wake_async_rcu('))


if __name__ == '__main__':
    unittest.main()

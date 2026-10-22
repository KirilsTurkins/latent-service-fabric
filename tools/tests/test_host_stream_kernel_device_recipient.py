"""Maintain original signal semantics and refuse unauthenticated source."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_recipient as recipient


class KernelDeviceRecipientSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.actual_fixture = staticmethod(recipient.fixture)
        cls.value = recipient.fixture()

    def setUp(self):
        saved = patch.object(recipient, 'fixture', return_value=self.value)
        saved.start()
        self.addCleanup(saved.stop)

    def raw(self, name):
        return self.value['sections'][name]['text']

    def test_whole_parent_and_false_enablement_scope_are_preserved(self):
        parent = recipient.prior.fixture()
        self.assertEqual((len(self.value['source']), len(self.value['sections'])), (95, 146))
        for field in ('source', 'sections'):
            self.assertEqual({name: self.value[field][name] for name in parent[field]}, parent[field])
        self.assertEqual(set(self.value['source']) - set(parent['source']),
            {'kernel/signal.c', 'kernel/rcu/tree.c', 'include/linux/rcupdate.h'})
        self.assertTrue(all(self.value[name] is False for name in recipient.GATES))

    def test_changed_duplicate_crlf_and_unknown_definitions_refuse(self):
        for name in recipient.DEFINITIONS:
            raw = self.raw(name)
            self.assertEqual(recipient.section(raw, name), raw)
            for changed in ('', raw + raw, raw.replace('\n', '\r\n'), raw.replace('{', '{ ', 1)):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    recipient.section(changed, name)
        with self.assertRaises(KeyError):
            recipient.section('', 'foreign_allocator')
        with self.assertRaises(ValueError):
            recipient.authenticate({})

    def test_source_member_and_enablement_metadata_cannot_be_rehashed_away(self):
        variants = []
        for field in ('source', 'sections'):
            value = json.loads(json.dumps(self.value))
            value[field]['foreign'] = {}
            variants.append(value)
        for name in recipient.GATES:
            value = json.loads(json.dumps(self.value))
            value[name] = True
            variants.append(value)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.json'
            for value in variants:
                path.write_bytes(json.dumps(value).encode())
                with patch.object(recipient, 'FIXTURE', path), self.assertRaises(ValueError):
                    self.actual_fixture()

    def test_private_allocation_preserves_original_ucount_and_rlimit_algorithm(self):
        inputs = {'kernel/signal.c': ''.join(self.raw(name) for name in
            ('__sigqueue_alloc', '__send_signal_locked', 'send_signal_locked', 'do_send_sig_info')).encode()}
        text = recipient.private_signals(inputs)
        start = text.index('static struct sigqueue *\n')
        end = text.index('\n}\n', start) + 3
        raw = text[start:end]
        raw = raw.replace('lsf_prepaid_device_sigqueue_alloc(struct lsf_device_registration_source source, int sig,', '__sigqueue_alloc(int sig,')
        raw = raw.replace('\n\t/* Only the real non-preallocated SIGIO sender chain enters here. */\n'
            '\tif (sigqueue_flags || !lsf_factory_device_recipient_current(source, NULL))\n'
            '\t\treturn NULL;\n\t(void)gfp_flags;\n', '')
        raw = raw.replace('lsf_factory_device_recipient_signal_allocate(source)',
            'kmem_cache_alloc(sigqueue_cachep, gfp_flags)')
        self.assertEqual(raw, self.raw('__sigqueue_alloc'))

    def test_original_rt_overflow_signal_fallback_and_namespace_rewrite_are_exact(self):
        inputs = {'kernel/signal.c': ''.join(self.raw(name) for name in
            ('__sigqueue_alloc', '__send_signal_locked', 'send_signal_locked', 'do_send_sig_info')).encode()}
        text = recipient.private_signals(inputs)
        for name, private_name, signature in [
            ('__send_signal_locked', 'lsf_prepaid_device_send_signal_locked_inner', 'static int '),
            ('send_signal_locked', 'lsf_prepaid_device_send_signal_locked', 'static int '),
            ('do_send_sig_info', 'lsf_prepaid_device_do_send_sig_info', 'int ')]:
            begin = text.index(signature + private_name + '(')
            end = text.index('\n}\n', begin) + 3
            raw = text[begin:end]
            raw = raw.replace(signature + private_name + '(struct lsf_device_registration_source source, int sig,',
                ('static int ' if name.startswith('__') else 'int ') + name + '(int sig,')
            raw = raw.replace('lsf_prepaid_device_sigqueue_alloc(source, sig,', '__sigqueue_alloc(sig,')
            raw = raw.replace('lsf_prepaid_device_send_signal_locked_inner(source, sig,', '__send_signal_locked(sig,')
            raw = raw.replace('lsf_prepaid_device_send_signal_locked(source, sig,', 'send_signal_locked(sig,')
            raw = raw.replace('\n\tif (!lsf_factory_device_recipient_current(source, NULL))\n\t\treturn -EOPNOTSUPP;\n', '')
            self.assertEqual(raw, self.raw(name))

    def test_final_return_classifies_before_dereference_and_keeps_normal_body(self):
        original = self.raw('__sigqueue_free')
        text = recipient.final_signal_return(original)
        self.assertLess(text.index('lsf_factory_device_recipient_signal_birth'), text.index('q->flags'))
        self.assertLess(text.index('dec_rlimit_put_ucounts'), text.index('lsf_factory_device_recipient_signal_return'))
        # The unselected compilation is byte exact, including preallocated
        # signals, null ucounts and the original ordinary slab free.
        projected = []
        private = False
        for line in text.splitlines(keepends=True):
            if line == '#ifdef CONFIG_LSF_STREAM_FACTORY\n':
                self.assertFalse(private)
                private = True
            elif line == '#endif\n' and private:
                private = False
            elif not private:
                projected.append(line)
        self.assertFalse(private)
        self.assertEqual(''.join(projected), original)


if __name__ == '__main__':
    unittest.main()

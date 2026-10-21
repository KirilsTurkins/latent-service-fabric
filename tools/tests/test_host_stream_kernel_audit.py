"""Exact-source audit derivation and preservation of ordinary kernel paths."""
import hashlib
import unittest

from tools import host_stream_kernel_audit as audit


class KernelMandatoryAudit(unittest.TestCase):
    def test_original_whole_inputs_definitions_and_formatter_layout_are_bound(self):
        value = audit.fixture()
        self.assertEqual((len(value['source']), len(value['sections'])), (23, 12))
        self.assertEqual(sum(row['bytes'] for row in value['source'].values()), 1616007)
        self.assertEqual({name:value['source'][name] for name in audit.skb.fixture()['source']},
                         audit.skb.fixture()['source'])
        for name, row in value['sections'].items():
            self.assertEqual(audit.section(row['text'], name), row['text'])
            self.assertEqual(hashlib.sha256(row['text'].encode()).hexdigest(), row['sha256'])
        layout = value['auditBufferDefinition']
        self.assertEqual(hashlib.sha256(layout['text'].encode()).hexdigest(), layout['sha256'])

    def test_missing_changed_duplicate_and_crlf_preimages_cannot_emit_source(self):
        with self.assertRaises(ValueError):
            audit.authenticate({})
        for name, row in audit.fixture()['sections'].items():
            original = row['text']
            for changed in (original + original, original.replace('\n', '\r\n'),
                            original.replace('\n{\n', '\n{\n;\n')):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    audit.section(changed, name)

    def test_observed_formatter_functions_have_the_original_config_off_projection(self):
        for name in ('audit_buffer_free', 'audit_expand', 'audit_log_vformat'):
            original = audit.fixture()['sections'][name]['text']
            text = audit.observed(original, name)
            normal, selected = [], False
            for line in text.splitlines():
                if line == '#ifdef CONFIG_LSF_STREAM_FACTORY':
                    self.assertFalse(selected)
                    selected = True
                elif line == '#endif' and selected:
                    selected = False
                elif not selected:
                    normal.append(line)
            self.assertFalse(selected)
            with self.subTest(name=name):
                self.assertEqual(' '.join('\n'.join(normal).split()), ' '.join(original.split()))

    def test_unselected_function_derivation_and_malformed_declarations_refuse(self):
        value = audit.fixture()
        for name in ('audit_expand', 'audit_buffer_free', 'common_lsm_audit'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                audit.private(value['sections'][name]['text'], name)
        with self.assertRaises(ValueError):
            audit.observed(value['sections']['audit_log_start']['text'], 'audit_log_start')
        with self.assertRaises(ValueError):
            audit.argument('void broken(\n{\n}\n', ', int error')


if __name__ == '__main__':
    unittest.main()

"""Exact source migration guards; no Linux execution or retirement proof."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import host_stream_kernel_device_retirement as source


def raw_function(text, prefix):
    start = text.index(prefix)
    return text[start:text.index('\n}\n', start) + 3]


class KernelDeviceRetirementSource(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.value = source.preimages()

    def test_compact_preimages_bind_actual_parent_without_replacing_original_fixture_or_gates(self):
        self.assertEqual((len(self.value['selectedWholeDerivedFiles']), len(self.value['sections'])), (7, 11))
        parent = source.prior.fixture()
        self.assertEqual(source.fixture(), parent)
        self.assertEqual((len(parent['source']), len(parent['sections'])), (105, 189))
        self.assertEqual(source.GATES, source.prior.GATES)
        self.assertTrue(all(parent[key] is False for key in source.GATES))
        self.assertTrue(all(self.value[key] is False for key in ('kernelRuntimeExecuted',
            'physicalQueueQualified', 'productionInstallation', 'completeAllocationClosure')))

    def test_rehashed_or_oversized_unknown_capture_refuses_before_any_source_change(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Path(directory) / 'fixture.json'
            value = dict(self.value)
            value['parentObjectSourceCommit'] = '0' * 40
            fixture.write_text(json.dumps(value))
            with patch.object(source, 'FIXTURE', fixture), self.assertRaisesRegex(ValueError,
                    'device-retirement-fixed-derived-preimages'):
                source.preimages()
            fixture.write_bytes(b' ' * (256 * 1024 + 1))
            with patch.object(source, 'FIXTURE', fixture), self.assertRaises(ValueError):
                source.transform({})

    def test_every_complete_function_refuses_body_change_duplicate_crlf_and_unknown_prefix(self):
        for prefix, row in self.value['sections'].items():
            self.assertEqual(source.function(row['text'], prefix), row['text'])
            for wrong in ('', row['text'] + row['text'], row['text'].replace('\n', '\r\n'),
                    row['text'].replace('{', '{ /* unknown */', 1)):
                with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                    source.function(wrong, prefix)
        with self.assertRaises(KeyError):
            source.function('void unknown(void)\n{\n}\n', 'void unknown(void)\n')

    def test_whole_derived_preimage_refusal_precedes_mutation_and_resume(self):
        values = {name: b'unknown' for name in self.value['selectedWholeDerivedFiles']}
        before = dict(values)
        with self.assertRaisesRegex(ValueError, 'device-retirement-whole-derived-preimage'):
            source.transform(values)
        self.assertEqual(values, before)

    def test_scheduler_recovers_every_original_statement_and_checks_generation_before_lookup(self):
        prefix = 'static void lsf_factory_device_firmware_schedule(void)\n'
        old = self.value['sections'][prefix]['text']
        new = source.scheduler(old)
        self.assertLess(new.index('factory.device->key.generation != original_owner.generation'),
            new.index('    owned = lsf_factory_device_firmware_locked();', len(source.SNAPSHOT)))
        projected = new.removeprefix(source.SNAPSHOT)
        projected = projected.replace('static void lsf_factory_device_firmware_schedule(\n'
            '    struct lsf_prepaid_key original_owner, struct lsf_prepaid_ticket original_pci)\n', prefix)
        start = projected.index('    /* Stale final returns')
        end = projected.index('        goto out;\n', start)
        projected = projected[:start] + '    if (!factory.device || !factory.device->firmware.slot)\n' + projected[end:]
        projected = projected.replace('    if (owned->pci.slot != original_pci.slot || owned->pci.generation != original_pci.generation)\n'
            '        goto out;\n', '')
        self.assertEqual(projected, old)
        self.assertLess(new.index('lsf_factory_device_registration_pending_locked()'), new.index('lsf_device_queue('))
        self.assertLess(new.index('    spin_unlock_irqrestore(&pool_lock, flags);', len(source.SNAPSHOT)),
            new.index('lsf_prepaid_acpi_queue_reference_put(work)'))

    def test_all_eight_actual_existing_resume_callers_capture_under_original_lock_before_return(self):
        values = {name: '' for name in self.value['selectedWholeDerivedFiles']}
        for row in self.value['sections'].values():
            values[row['source']] += row['text'] + '\n'
        outputs = {name: raw.encode() for name, raw in values.items()}
        source.old_callers(outputs)
        selected = [prefix for prefix in self.value['sections'] if prefix not in (
            'static void lsf_factory_device_firmware_schedule(void)\n',
            'int lsf_factory_blob_finish(struct lsf_factory_blob copy, unsigned int kind)\n',
            'int lsf_factory_sidcache_destroy(const void *address)\n')]
        self.assertEqual(len(selected), 8)
        for prefix in selected:
            with self.subTest(prefix=prefix):
                row = self.value['sections'][prefix]
                raw = raw_function(outputs[row['source']].decode(), prefix)
                self.assertEqual(raw.count(source.CAPTURE.strip()), 1)
                capture = raw.index(source.CAPTURE.strip())
                self.assertLess(raw.index('spin_lock_irqsave(&pool_lock, flags);'), capture)
                self.assertLess(capture, raw.index('spin_unlock_irqrestore(&pool_lock, flags);', capture))
                self.assertLess(raw.index('spin_unlock_irqrestore(&pool_lock, flags);', capture), raw.index(source.RESUME))
                if 'lsf_device_finish(' in raw:
                    self.assertLess(capture, raw.index('lsf_device_finish('))
                self.assertNotIn('lsf_factory_device_firmware_schedule();', raw)

    def test_security_final_returns_resume_after_finish_and_unlock_and_preserve_application_paths(self):
        prefixes = ('int lsf_factory_blob_finish(struct lsf_factory_blob copy, unsigned int kind)\n',
            'int lsf_factory_sidcache_destroy(const void *address)\n')
        old = '\n'.join(self.value['sections'][prefix]['text'] for prefix in prefixes)
        new = source.security_final_returns(old)
        for prefix, normal in zip(prefixes, ('    context = lsf_factory_context_current(copy.context);\n',
                '    if (result == 1 &&\n')):
            original = raw_function(old, prefix)
            changed = raw_function(new, prefix)
            capture = changed.index(source.CAPTURE.strip())
            finish = changed.index('lsf_factory_device_security_finish_locked(', capture)
            unlock = changed.index('spin_unlock_irqrestore(&pool_lock, flags);', finish)
            self.assertLess(capture, finish)
            self.assertLess(finish, unlock)
            self.assertLess(unlock, changed.index(source.RESUME))
            self.assertEqual(changed[changed.index(normal):], original[original.index(normal):])


if __name__ == '__main__':
    unittest.main()

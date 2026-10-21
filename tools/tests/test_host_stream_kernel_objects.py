"""Refuse false object qualifications with disabled code or weakened security."""
import unittest
import hashlib
from pathlib import Path
import tempfile
from unittest.mock import patch

from tools import qualify_host_stream_kernel_objects as candidate


class KernelObjectSelection(unittest.TestCase):
    def baseline(self):
        return {**dict.fromkeys(candidate.REQUIRED, 'y'), candidate.SELECTED: 'n', 'CONFIG_MEMCG': 'y'}

    def test_exact_optin_preserves_every_original_config_including_memcg(self):
        before = self.baseline()
        candidate.selected_configuration(before, {**before, candidate.SELECTED: 'y'})
        for name in candidate.REQUIRED:
            with self.subTest(disabled=name), self.assertRaisesRegex(ValueError, 'security-or-inet-disabled'):
                candidate.selected_configuration(before, {**before, candidate.SELECTED: 'y', name: 'n'})
        with self.assertRaisesRegex(ValueError, 'unrelated-config-drift'):
            candidate.selected_configuration(before, {**before, candidate.SELECTED:'y', 'CONFIG_MEMCG':'n'})

    def test_disabled_or_previously_enabled_private_bodies_never_count_as_compile(self):
        before = self.baseline()
        for start, end in ((before,before), ({**before,candidate.SELECTED:'y'}, {**before,candidate.SELECTED:'y'})):
            with self.assertRaisesRegex(ValueError, 'private-code-not-selected'):
                candidate.selected_configuration(start,end)

    def test_config_parser_rejects_duplicate_malformed_empty_and_oversize_symbols(self):
        self.assertEqual(candidate.configuration(b'CONFIG_INET=y\n# CONFIG_UNUSED is not set\n'),
            {'CONFIG_INET':'y','CONFIG_UNUSED':'n'})
        for raw in (b'',b'CONFIG_INET=y\nCONFIG_INET=n\n',b'CONFIG_BAD\n',b'# CONFIG_BAD maybe\n', b'x'*(1024*1024+1)):
            with self.subTest(raw=raw[:32]), self.assertRaises(ValueError):
                candidate.configuration(raw)

    def test_actual_upstream_mixed_case_symbol_names_stay_exact_and_cannot_bypass_comparison(self):
        # These three lines are retained from the first actual defconfig.
        original=b'# CONFIG_SCSI_DC395x is not set\n# CONFIG_MT76x0U is not set\nCONFIG_FONT_8x16=y\n'
        values=candidate.configuration(original)
        self.assertEqual(values,{'CONFIG_SCSI_DC395x':'n','CONFIG_MT76x0U':'n','CONFIG_FONT_8x16':'y'})
        before={**self.baseline(),**values}
        candidate.selected_configuration(before,{**before,candidate.SELECTED:'y'})
        with self.assertRaisesRegex(ValueError,'unrelated-config-drift'):
            candidate.selected_configuration(before,{**before,candidate.SELECTED:'y','CONFIG_FONT_8x16':'n'})
        with self.assertRaisesRegex(ValueError,'configuration-duplicate'):
            candidate.configuration(original+b'CONFIG_FONT_8x16=n\n')

    def test_six_real_objects_require_private_constructor_and_blob_symbols(self):
        self.assertEqual(len(candidate.OBJECTS), 6)
        symbols = {name for names in candidate.OBJECTS.values() for name in names}
        self.assertTrue({'lsf_prepaid_sock_create','lsf_prepaid_inet_create','lsf_prepaid_sk_alloc',
            'lsf_prepaid_security_inode_alloc','lsf_prepaid_security_sk_alloc','lsf_factory_blob_finish'} <= symbols)
        self.assertIn('depends on INET && SECURITY && SECURITY_NETWORK', candidate.KCONFIG)
        self.assertIn('default n', candidate.KCONFIG)

    def test_local_execution_refuses_before_archive_read_or_build(self):
        with patch.dict(candidate.os.environ, {}, clear=True), patch.object(candidate.maintained, 'authenticate_archive') as read:
            with self.assertRaisesRegex(ValueError, 'hosted-linux-only'):
                candidate.run(None,None)
            read.assert_not_called()

    def test_archive_snapshot_authenticates_all_bytes_in_an_independent_fresh_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);source=root/'original';source.write_bytes(b'whole-source-archive')
            target=root/'private-copy'
            expected={'bytes':len(source.read_bytes()),'sha256':hashlib.sha256(source.read_bytes()).hexdigest()}
            candidate.snapshot_archive(source,target,expected)
            self.assertEqual(target.read_bytes(),source.read_bytes())
            self.assertNotEqual(target.stat().st_ino,source.stat().st_ino)
            with self.assertRaises(FileExistsError):candidate.snapshot_archive(source,target,expected)
            with self.assertRaisesRegex(ValueError,'snapshot-byte-identity'):
                candidate.snapshot_archive(source,root/'invalid-copy',{**expected,'sha256':'0'*64})
            # Windows temporary-directory cleanup needs writable files.
            target.chmod(0o600)

    def test_failed_owned_process_keeps_partial_streams_and_never_masks_primary_failure(self):
        from tools.owned_test_process import ProcessFailure,Result
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);capture=root/'capture';capture.mkdir()
            commands=candidate.Commands(root,capture,{})
            failure=ProcessFailure('timeout','original-command-timeout',Result(None,b'partial-output',stderr=b'original-compiler-error'))
            with patch.object(candidate,'run_owned',side_effect=failure):
                with self.assertRaises(ProcessFailure) as caught:commands.run('compile','compiler')
            self.assertIs(caught.exception,failure)
            self.assertEqual((capture/'logs/00-compile.stderr.txt').read_bytes(),b'original-compiler-error')
            self.assertEqual(commands.records[0]['category'],'timeout')
            with patch.object(candidate,'run_owned',side_effect=failure),patch.object(commands,'retain',side_effect=OSError('disk')):
                with self.assertRaises(ProcessFailure) as caught:commands.run('second','compiler')
            self.assertIs(caught.exception,failure)

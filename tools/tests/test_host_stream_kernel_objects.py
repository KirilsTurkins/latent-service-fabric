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


class KernelNetlabelObjectSelection(unittest.TestCase):
    def test_default_six_object_floor_is_identical_and_selector_accepts_only_real_boolean(self):
        self.assertEqual(candidate.object_selection(False), candidate.OBJECTS)
        for mode in ('true', 'false', 'netlabel', 0, 1, None, [], {}):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, 'closed-profile-selector'):
                candidate.object_selection(mode)

    def test_netlabel_twelve_objects_retain_all_old_symbols_and_require_all_twenty_one_new_globals(self):
        selected = candidate.object_selection(True)
        self.assertEqual(len(selected), 12)
        for name, symbols in candidate.OBJECTS.items():
            self.assertTrue(set(symbols) <= set(selected[name]))
        self.assertFalse(set(candidate.NETLABEL_OBJECTS) & set(candidate.OBJECTS))
        names = [name for symbols in selected.values() for name in symbols]
        self.assertEqual(len(names), 34)
        self.assertEqual(len(set(names)), 34)
        self.assertTrue({'lsf_prepaid_security_sid_to_secattr', 'lsf_prepaid_mls_export_cat',
            'lsf_prepaid_ebitmap_export', 'lsf_prepaid_cipso_sock_setattr',
            'lsf_prepaid_netlabel_source', 'lsf_factory_options_owned'} <= set(names))

    def test_netlabel_must_already_be_enabled_no_configuration_override_is_added(self):
        candidate.netlabel_configuration({'CONFIG_NETLABEL':'y'}, {'CONFIG_NETLABEL':'y'})
        for before, after in (({},{}),({'CONFIG_NETLABEL':'n'},{'CONFIG_NETLABEL':'y'}),
                               ({'CONFIG_NETLABEL':'y'},{'CONFIG_NETLABEL':'n'})):
            with self.assertRaisesRegex(ValueError,'netlabel-originally-disabled'):
                candidate.netlabel_configuration(before,after)
        self.assertNotIn('NETLABEL',candidate.KCONFIG)
        self.assertEqual(candidate.MAKEFILE, '\nobj-$(CONFIG_LSF_STREAM_FACTORY) += factory.o\n')

    def test_optin_object_profile_still_refuses_local_build_before_archive_access(self):
        with patch.dict(candidate.os.environ, {}, clear=True), patch.object(candidate.maintained, 'authenticate_archive') as read:
            with self.assertRaisesRegex(ValueError, 'hosted-linux-only'):
                candidate.run(None,None,netlabel=True)
            read.assert_not_called()


class KernelNetportObjectSelection(unittest.TestCase):
    def test_netport_is_exclusive_boolean_and_both_historical_selections_remain_exact(self):
        self.assertEqual(candidate.object_selection(False), candidate.OBJECTS)
        self.assertEqual(candidate.object_selection(True), candidate.object_selection(True, False))
        for value in ('true', 'false', 0, 1, None, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'closed-profile-selector'):
                candidate.object_selection(False, value)
        with self.assertRaisesRegex(ValueError, 'exclusive-profile-selector'):
            candidate.object_selection(True, True)

    def test_actual_netport_and_connect_hooks_compile_with_all_forty_private_globals(self):
        old = candidate.object_selection(True)
        selected = candidate.object_selection(False, True)
        self.assertEqual(len(selected), 14)
        for name, symbols in old.items():
            self.assertTrue(set(symbols) <= set(selected[name]))
        self.assertEqual(set(selected) - set(old), {'security/selinux/netport.o', 'security/selinux/hooks.o'})
        names = [name for symbols in selected.values() for name in symbols]
        self.assertEqual(len(names), 40)
        self.assertEqual(len(set(names)), 40)
        self.assertTrue({'lsf_prepaid_netport_sid', 'lsf_prepaid_netport_drain',
            'lsf_factory_netport_publish', 'lsf_factory_netport_current'} <= set(names))

    def test_netport_optin_refuses_local_build_before_any_source_acquisition(self):
        with patch.dict(candidate.os.environ, {}, clear=True), patch.object(candidate.maintained, 'authenticate_archive') as read:
            with self.assertRaisesRegex(ValueError, 'hosted-linux-only'):
                candidate.run(None, None, netport=True)
            read.assert_not_called()

    def test_mixed_profiles_refuse_before_linux_checks_archive_output_or_build(self):
        with patch.object(candidate.maintained, 'authenticate_archive') as read:
            with self.assertRaisesRegex(ValueError, 'exclusive-profile-selector'):
                candidate.run(None, None, netlabel=True, netport=True)
            read.assert_not_called()


class KernelSidcacheObjectSelection(unittest.TestCase):
    def test_fifteen_objects_keep_all_forty_netport_globals_and_add_twelve_real_definitions(self):
        old = candidate.object_selection(False, True)
        selected = candidate.object_selection(False, False, True)
        self.assertEqual(len(selected), 15)
        self.assertEqual(set(selected) - set(old), {'security/selinux/ss/sidtab.o'})
        for name, symbols in old.items():
            self.assertTrue(set(symbols) <= set(selected[name]))
        names = [name for values in selected.values() for name in values]
        self.assertEqual(len(names), 52)
        self.assertEqual(len(set(names)), 52)
        self.assertTrue({'lsf_prepaid_security_sid_to_context', 'lsf_prepaid_sid2str_put',
            'lsf_prepaid_sidcache_detach', 'lsf_factory_sidcache_destroy'} <= set(names))

    def test_only_one_real_boolean_profile_can_reach_source_or_build(self):
        for value in ('true', 'false', 0, 1, None, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'closed-profile-selector'):
                candidate.object_selection(False, False, value)
        for modes in ((True, False, True), (False, True, True), (True, True, True)):
            with self.subTest(modes=modes), patch.object(candidate.maintained, 'authenticate_archive') as read:
                with self.assertRaisesRegex(ValueError, 'exclusive-profile-selector'):
                    candidate.run(None, None, netlabel=modes[0], netport=modes[1], sidcache=modes[2])
                read.assert_not_called()

    def test_original_cache_256_entry_configuration_is_required_without_override(self):
        name = 'CONFIG_SECURITY_SELINUX_SID2STR_CACHE_SIZE'
        candidate.sidcache_configuration({name: '256'}, {name: '256'})
        for value in ('0', '1', '128', '512', None, 256):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'sidcache-original-256-entry-profile-required'):
                candidate.sidcache_configuration({name: value}, {name: '256'})
        self.assertNotIn('SID2STR', candidate.KCONFIG)
        with self.assertRaisesRegex(ValueError, 'sidcache-original-256-entry-profile-required'):
            candidate.sidcache_configuration({name: '256'}, {name: '512'})

    def test_sidcache_profile_refuses_local_build_before_any_archive_or_output(self):
        with patch.dict(candidate.os.environ, {}, clear=True), patch.object(candidate.maintained, 'authenticate_archive') as read:
            with self.assertRaisesRegex(ValueError, 'hosted-linux-only'):
                candidate.run(None, None, sidcache=True)
            read.assert_not_called()

    def test_focused_owning_job_preserves_original_time_tools_security_and_artifact_bounds(self):
        import yaml
        workflow = yaml.safe_load((candidate.ROOT/'.github/workflows/stream-kernel-objects.yml').read_bytes())
        events = workflow.get('on', workflow.get(True))
        self.assertEqual(events['workflow_dispatch']['inputs']['sidcache'], {
            'description': 'Compile the closed SID-cache and audit-string source profile',
            'type': 'boolean', 'default': False})
        self.assertEqual(workflow['permissions'], {'contents': 'read'})
        job = workflow['jobs']['sidcache-objects']
        self.assertEqual(job['timeout-minutes'], 20)
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        self.assertIn("assert values.count('true') <= 1", commands)
        self.assertIn("('NETLABEL_REQUEST', 'NETPORT_REQUEST', 'SIDCACHE_REQUEST')", commands)
        self.assertIn('--sidcache', commands)
        self.assertIn('gcc make flex bison bc libelf-dev libssl-dev', commands)
        self.assertNotIn('scripts/config', commands)
        artifact = job['steps'][-1]['with']
        self.assertIn('/objects/security/selinux/ss/sidtab.o', artifact['path'])
        self.assertIn('/FAILED.json', artifact['path'])
        self.assertEqual(artifact['retention-days'], 3)
        self.assertEqual(artifact['if-no-files-found'], 'warn')


class KernelAvcObjectSelection(unittest.TestCase):
    def test_sixteen_objects_preserve_all_fifty_two_sidcache_definitions_and_add_nine(self):
        old = candidate.object_selection(False, False, True)
        selected = candidate.object_selection(False, False, False, True)
        self.assertEqual(len(selected), 16)
        self.assertEqual(set(selected) - set(old), {'security/selinux/avc.o'})
        for name, symbols in old.items():
            self.assertTrue(set(symbols) <= set(selected[name]))
        names = [name for values in selected.values() for name in values]
        self.assertEqual(len(names), 61)
        self.assertEqual(len(set(names)), 61)
        self.assertTrue({'lsf_prepaid_avc_has_perm', 'lsf_prepaid_avc_drain',
            'lsf_factory_avc_replace', 'lsf_factory_avc_current'} <= set(names))

    def test_unknown_or_mixed_avc_profiles_refuse_before_acquisition(self):
        for value in ('true', 'false', 0, 1, None, [], {}):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'closed-profile-selector'):
                candidate.object_selection(False, False, False, value)
        for modes in ((True, False, False), (False, True, False), (False, False, True),
                      (True, True, True)):
            with self.subTest(modes=modes), patch.object(candidate.maintained, 'authenticate_archive') as read:
                with self.assertRaisesRegex(ValueError, 'exclusive-profile-selector'):
                    candidate.run(None, None, netlabel=modes[0], netport=modes[1], sidcache=modes[2], avc=True)
                read.assert_not_called()

    def test_avc_selection_refuses_local_build_before_archive_or_output(self):
        with patch.dict(candidate.os.environ, {}, clear=True), patch.object(candidate.maintained, 'authenticate_archive') as read:
            with self.assertRaisesRegex(ValueError, 'hosted-linux-only'):
                candidate.run(None, None, avc=True)
            read.assert_not_called()

    def test_exclusive_avc_job_uses_only_closed_inputs_and_original_build_bounds(self):
        import yaml
        workflow = yaml.safe_load((candidate.ROOT/'.github/workflows/stream-kernel-objects.yml').read_bytes())
        events = workflow.get('on', workflow.get(True))
        self.assertEqual(events['workflow_dispatch']['inputs']['avc'], {
            'description': 'Compile the closed AVC with SID-cache source profile',
            'type': 'boolean', 'default': False})
        job = workflow['jobs']['avc-objects']
        self.assertEqual(job['timeout-minutes'], 20)
        guard = next(step for step in job['steps'] if 'env' in step)
        self.assertEqual(set(guard['env']), {'NETLABEL_REQUEST', 'NETPORT_REQUEST', 'SIDCACHE_REQUEST', 'AVC_REQUEST'})
        self.assertIn("assert all(value in ('', 'true', 'false') for value in values)", guard['run'])
        self.assertIn("assert values.count('true') <= 1", guard['run'])
        commands = '\n'.join(step.get('run', '') for step in job['steps'])
        self.assertIn('--avc', commands)
        self.assertNotIn('${{ inputs.', commands)
        self.assertNotIn('scripts/config', commands)
        self.assertIn('gcc make flex bison bc libelf-dev libssl-dev', commands)
        artifact = job['steps'][-1]['with']
        for name in candidate.object_selection(False, False, False, True):
            self.assertIn('/objects/'+name, artifact['path'])
        self.assertIn('/FAILED.json', artifact['path'])
        self.assertEqual(artifact['retention-days'], 3)
        self.assertEqual(workflow['concurrency']['cancel-in-progress'], False)

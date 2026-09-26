"""Runner wiring and prepared-case contracts; synthetic fixtures are not LSF evidence."""
from contextlib import redirect_stdout
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from tools import prepared_test_harness as harness
from tools import run_angular_renderer_tests as angular
from tools import run_oci_registry_tests as oci
from tools.test_run import ProcessFailure, TestRun, contract
from tools.owned_test_process import Result
from tools.tests.test_owned_test_process import policy

ROOT = Path(__file__).resolve().parents[2]


class RunnerContractTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def test_inventory_contracts_reference_real_suites_and_pinned_services(self):
        for name in ('oci-registry', 'oci-web', 'angular-renderer'):
            selected, rows = contract(name)
            self.assertTrue(set(selected['suiteIds']) <= rows.keys())
            self.assertIn('owned-descendants', selected['prerequisites']['accounting'])
            self.assertIn('test-manifest', selected['prerequisites']['artifacts'])
            for service in selected['prerequisites']['services']:
                self.assertEqual(service['image'], oci.IMAGE)

    def test_preflight_reports_no_test_execution(self):
        for module, args in ((oci, ['--preflight']), (angular, ['--preflight'])):
            with self.subTest(module=module.__name__), redirect_stdout(io.StringIO()), \
                    patch.object(TestRun, 'source_identity'), patch.object(TestRun, 'prerequisites') as check, \
                    patch.object(module, 'execute') as execute:
                self.assertEqual(module.main([*args, '--diagnostic-root', str(self.root)]), 0)
                check.assert_called_once_with(before_build=True)
                execute.assert_not_called()
        for path in self.root.glob('*.json'):
            self.assertEqual(json.loads(path.read_text())['outcome'], 'preflight-passed')

    def test_oci_normal_and_fault_paths_always_retire_registry(self):
        for failure in (False, True):
            with self.subTest(failure=failure), redirect_stdout(io.StringIO()), \
                    patch.object(TestRun, 'source_identity'), patch.object(TestRun, 'prerequisites'), \
                    patch.object(oci, 'certificates'), patch.object(TestRun, 'artifact'), patch.object(oci, 'ready'), \
                    patch.object(oci.Registry, 'launch', return_value='https://127.0.0.1:1'), \
                    patch.object(oci.Registry, 'close') as close, patch.object(oci, 'execute') as execute:
                args = ['--check-fixture', '--diagnostic-root', str(self.root)]
                if failure:
                    with self.assertRaises(ProcessFailure) as error:
                        oci.main([*args, '--inject-failure', 'after-ready'])
                    self.assertEqual(error.exception.reason, 'injected-after-ready')
                else:
                    self.assertEqual(oci.main(args), 0)
                close.assert_called_once()
                execute.assert_not_called()
                self.assertIsNone(oci.ACTIVE_RUN.get())

    def test_oci_interrupted_launch_still_closes_owned_fixture(self):
        with redirect_stdout(io.StringIO()), patch.object(TestRun, 'source_identity'), \
                patch.object(TestRun, 'prerequisites'), patch.object(TestRun, 'artifact'), patch.object(oci, 'certificates'), \
                patch.object(oci.Registry, 'launch', side_effect=KeyboardInterrupt()), \
                patch.object(oci.Registry, 'close') as close:
            with self.assertRaises(KeyboardInterrupt):
                oci.main(['--check-fixture', '--diagnostic-root', str(self.root)])
            close.assert_called_once()
            self.assertIsNone(oci.ACTIVE_RUN.get())

    def test_oci_modes_execute_the_registered_prepared_cases(self):
        registry_case = 'real_tls_registry_roundtrips_tag_race_auth_and_referrers'
        provenance_case = 'real_observed_build_provenance_roundtrip'
        web_case = 'supply_chain::tests::web_catalog::registry::authenticated_web_registry_admission_roundtrip'
        manifest = self.root / 'inventory.json'
        cases = (
            ([], 'latent-oci.test.registry', [registry_case]),
            (['--provenance-input', str(self.root / 'provenance')],
             'latent-oci.test.registry', [provenance_case, registry_case]),
            (['--web-admission-component', str(self.root / 'web.wasm')],
             'latent-policy.lib.latent-policy', [web_case]),
        )
        for options, suite, selected in cases:
            with self.subTest(options=options), redirect_stdout(io.StringIO()), \
                    patch.object(TestRun, 'source_identity'), patch.object(TestRun, 'prerequisites'), \
                    patch.object(TestRun, 'artifact'), patch.object(oci, 'certificates'), \
                    patch.object(oci, 'ready'), patch.object(oci, 'wasm'), \
                    patch.object(oci, 'provenance_artifacts'), \
                    patch.object(oci.Registry, 'launch', return_value='https://127.0.0.1:1'), \
                    patch.object(oci.Registry, 'close') as close, patch.object(oci, 'execute') as execute:
                self.assertEqual(oci.main(['--test-manifest', str(manifest),
                                          '--diagnostic-root', str(self.root), *options]), 0)
                execute.assert_called_once()
                self.assertEqual(execute.call_args.args[1]['id'], suite)
                self.assertEqual(execute.call_args.args[2], manifest)
                self.assertEqual(execute.call_args.kwargs['selected'], selected)
                close.assert_called_once()
                self.assertIsNone(oci.ACTIVE_RUN.get())

    def test_registry_readiness_rejects_foreign_id_label_and_endpoint(self):
        registry = oci.Registry(self.root)
        registry.container_id = 'a' * 64
        record = dict(id=registry.container_id, labels={oci.LABEL: registry.token}, running=True,
                      ports={'5000/tcp': [dict(HostIp='127.0.0.1', HostPort='1234')]})
        def inspect(value):
            return patch.object(registry, 'inspect', return_value=subprocess.CompletedProcess([], 0, json.dumps(value), ''))
        with inspect(record):
            self.assertTrue(registry.alive('https://127.0.0.1:1234'))
        for value in (dict(record, id='b' * 64), dict(record, labels={oci.LABEL:'foreign'}),
                      dict(record, ports={'5000/tcp':[dict(HostIp='0.0.0.0',HostPort='1234')]})):
            with inspect(value), self.assertRaises(ProcessFailure):
                registry.alive('https://127.0.0.1:1234')
        with inspect(dict(record, running=False)):
            self.assertFalse(registry.alive('https://127.0.0.1:1234'))

    def test_registry_cleanup_does_not_unlink_replaced_foreign_state(self):
        state = self.root / 'state.json'
        registry = oci.Registry(self.root, state)
        registry.state_owned = True
        state.write_text(json.dumps(dict(name='another-run', token='other')))
        with self.assertRaises(ProcessFailure):
            registry.remove_state()
        self.assertTrue(state.exists())

    def test_active_commands_use_shared_owner_not_legacy_subprocess(self):
        owner = Mock(command=Mock(return_value=Result(0, b'bounded', cleaned=True)))
        token = oci.ACTIVE_RUN.set(owner)
        try:
            with patch.object(oci.subprocess, 'run') as legacy:
                self.assertEqual(oci.command(['docker', 'inspect']), 'bounded')
                legacy.assert_not_called()
            owner.command.assert_called_once_with(['docker', 'inspect'], timeout=30)
        finally:
            oci.ACTIVE_RUN.reset(token)

    def test_wasm_and_provenance_paths_fail_before_execution(self):
        owner = TestRun('synthetic', policy(), repo=ROOT, synthetic=True, diagnostic_root=self.root)
        path = self.root / 'bad.wasm'
        path.write_bytes(b'not wasm')
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), owner:
            harness.wasm(owner, 'component', path)
        for leaf in ('observation.json', 'sbom-inputs.json'):
            (self.root / leaf).write_text('{}')
        (self.root / 'package-source.json').write_text(json.dumps(dict(layers=[dict(source='../outside')])))
        owner = TestRun('synthetic', policy(), repo=ROOT, synthetic=True, diagnostic_root=self.root)
        with redirect_stdout(io.StringIO()), self.assertRaises(ProcessFailure), owner:
            oci.provenance_artifacts(owner, self.root)

    def test_renderer_requires_explicit_artifacts_without_building(self):
        with redirect_stdout(io.StringIO()), patch.object(TestRun, 'source_identity'), \
                patch.object(TestRun, 'prerequisites'), patch.object(angular, 'execute') as execute:
            with self.assertRaises(ProcessFailure):
                angular.main(['--diagnostic-root', str(self.root)])
            execute.assert_not_called()

    def test_broken_inventory_has_structured_failure_before_execution(self):
        from tools import test_run
        with redirect_stdout(io.StringIO()), patch.object(test_run, 'contract', side_effect=ProcessFailure('invalid-fixture','broken-inventory')):
            with self.assertRaises(ProcessFailure):
                angular.main(['--preflight','--diagnostic-root',str(self.root)])
        record=json.loads(next(self.root.glob('*.json')).read_text())
        self.assertEqual(record['reason'],'broken-inventory')
        self.assertEqual(record['outcome'],'failed')
        self.assertFalse(record['source']['observed'])

    def test_expected_fault_validator_rejects_stale_or_missing_cleanup(self):
        from tools.check_owned_diagnostics import check
        record=dict(schemaVersion='latent.test-run.v1',suite='angular-renderer',outcome='failed',
                    reason='injected-after-discovery',child=dict(cleanupAcknowledged=True),cleanupFailures=[],
                    reproduction=dict(fault='after-discovery'),source=dict(observed=True),fixtures=dict(component='sha256:abc'))
        path=self.root/'fault.json';path.write_text(json.dumps(record))
        with redirect_stdout(io.StringIO()):check(self.root,'angular-renderer','injected-after-discovery')
        for changes in (dict(child=dict(cleanupAcknowledged=False)),dict(cleanupFailures=['Timeout']),dict(fixtures={}),
                        dict(source=dict(observed=False)),dict(outcome='not-run'),dict(reason='different')):
            path.write_text(json.dumps(dict(record,**changes)))
            with self.assertRaises(ValueError):check(self.root,'angular-renderer','injected-after-discovery')
        path.write_text(json.dumps(record));(self.root/'old.json').write_text(json.dumps(record))
        with self.assertRaises(ValueError):check(self.root,'angular-renderer','injected-after-discovery')


class PreparedHarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = dict(id='synthetic.test.example', manifest='crate/Cargo.toml', source='tests/example.rs',
                        target='example', kind='test', mode='libtest', expectedIgnored=['first','second'],
                        recipe='workspace-all-features')
        for path in ('crate/tests', 'target/debug/deps'):
            (self.root / path).mkdir(parents=True)
        for path in ('crate/Cargo.toml', 'crate/tests/example.rs', 'target/debug/deps/example'):
            (self.root / path).write_text('fixture')
        self.binary = self.root / 'target/debug/deps/example'
        self.manifest = self.root / 'build.jsonl'
        self.manifest.write_text(json.dumps(dict(reason='compiler-artifact', manifest_path=str(self.root / 'crate/Cargo.toml'),
              profile=dict(test=True), target=dict(name='example', kind=['test'], src_path=str(self.root / 'crate/tests/example.rs')),
              executable=str(self.binary)))+'\n'+json.dumps(dict(reason='build-finished',success=True))+'\n')

    def execute(self, outputs, *, selected=None, fault=None):
        owner = TestRun('synthetic', policy(), repo=self.root, synthetic=True, diagnostic_root=self.root/'diagnostics')
        with redirect_stdout(io.StringIO()), patch.object(harness.artifacts, 'cargo_environment', return_value={}), \
                patch.object(owner, 'command', side_effect=outputs) as command, owner:
            harness.execute(owner, self.row, self.manifest, {}, selected=selected or ['first','second'], fault=fault)
        return owner, command

    def test_explicit_integration_target_runs_each_exact_case_once(self):
        outputs=[Result(0,b'first: test\nsecond: test\n\n2 tests, 0 benchmarks\n',cleaned=True)]
        outputs += [Result(0,b'test result: ok. 1 passed; 0 failed; 0 ignored;\n',cleaned=True)]*2
        owner, command = self.execute(outputs)
        self.assertEqual(command.call_count,3)
        self.assertIn('--exact',command.call_args.args[0])
        self.assertEqual(owner.reproduction['cases'],['first','second'])
        self.assertIn(self.row['id'],owner.fixture_ids)

    def test_missing_ignored_case_and_zero_execution_never_pass(self):
        for output in (b'0 tests, 0 benchmarks\n',b'first: test\n1 test, 0 benchmarks\n'):
            with self.assertRaises(ProcessFailure) as error:
                self.execute([Result(0,output,cleaned=True)])
            self.assertEqual(error.exception.category,'invalid-fixture')
        with self.assertRaises(ProcessFailure) as error:
            self.execute([Result(0,b'first: test\nsecond: test\n2 tests, 0 benchmarks\n',cleaned=True),
                          Result(0,b'test result: ok. 0 passed; 0 failed; 0 ignored;\n',cleaned=True)])
        self.assertEqual(error.exception.category,'assertion-failure')

    def test_fault_after_discovery_has_no_execution_or_retry(self):
        with self.assertRaises(ProcessFailure) as error:
            self.execute([Result(0,b'first: test\nsecond: test\n2 tests, 0 benchmarks\n',cleaned=True)],fault='after-discovery')
        self.assertEqual(error.exception.reason,'injected-after-discovery')

    def test_unknown_selection_rejected(self):
        with self.assertRaises(ProcessFailure):
            self.execute([],selected=['other'])


class NativeRunnerDemonstrations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if sys.platform != 'linux' or not Path(f'/proc/self/task/{os.getpid()}/children').is_file():
            if os.environ.get('LSF_REQUIRE_NATIVE_PROCESS_TESTS') == '1':
                raise AssertionError('required native runner demonstrations unavailable')
            raise unittest.SkipTest('native Linux owned-child accounting unavailable; NOT coverage')

    def test_renderer_runner_normal_and_fault_with_retired_pipe_descendants(self):
        # The real runner and artifact decoder execute; the generated libtests
        # below deliberately are synthetic, not Wasmtime/Angular qualification.
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            policy_data, rows=contract('angular-renderer')
            manifest=root/'build.jsonl'
            records=[]
            children=root/'children'
            for key in policy_data['suiteIds']:
                row=rows[key]
                package=root/Path(row['manifest']).parent
                (package/row['source']).parent.mkdir(parents=True,exist_ok=True)
                (package/row['source']).write_text('// synthetic libtest')
                (root/row['manifest']).write_text('synthetic')
                binary=root/'target/debug/deps'/row['target']
                binary.parent.mkdir(parents=True,exist_ok=True)
                code=(f'#!{sys.executable}\nimport os,sys,time\nfrom pathlib import Path\n'
                      f'names={row["expectedIgnored"]!r}\n'
                      'if "--list" in sys.argv:\n'
                      ' pid=os.fork()\n'
                      ' if pid==0:\n  os.setsid()\n  time.sleep(60)\n  os._exit(0)\n'
                      f' with Path({str(children)!r}).open("a") as s: s.write(str(pid)+"\\n")\n'
                      ' for name in names: print(name+": test")\n'
                      ' print(str(len(names))+" tests, 0 benchmarks")\n'
                      'else:\n assert sys.argv[1] in names and "--exact" in sys.argv\n'
                      ' print("test result: ok. 1 passed; 0 failed; 0 ignored;")\n')
                binary.write_text(code);binary.chmod(0o700)
                records.append(dict(reason='compiler-artifact',manifest_path=str(root/row['manifest']),
                                    target=dict(kind=[row['kind']],name=row['target'],src_path=str(package/row['source'])),
                                    profile=dict(test=True),executable=str(binary)))
            records.append(dict(reason='build-finished',success=True))
            manifest.write_text(''.join(json.dumps(row)+'\n' for row in records))
            component=root/'application.wasm';component.write_bytes(b'\0asm\x0d\0\x01\0')
            (root/'renderer.wasm').write_bytes(component.read_bytes())
            def factory(*args,**kwargs):
                kwargs['synthetic']=True
                return TestRun(*args,**kwargs)
            for fault in (False,True):
                diagnostics=Path(os.environ.get('LSF_OWNED_RENDERER_DEMO_DIAGNOSTICS',root/'diagnostics'))
                argv=['--test-manifest',str(manifest),'--component',str(component),'--diagnostic-root',str(diagnostics)]
                if fault:argv+=['--inject-failure','after-discovery']
                # Only the source-checkout and rustc-library query are mocked;
                # native ownership, exact discovery, execution and cleanup run.
                with redirect_stdout(io.StringIO()), patch.object(angular,'ROOT',root), \
                        patch.object(angular,'TestRun',side_effect=factory), patch.object(TestRun,'source_identity'), \
                        patch.object(harness.artifacts,'cargo_environment',side_effect=lambda repo,art,env,**kw:dict(env)), \
                        patch.dict(os.environ,{'CARGO_TARGET_DIR':str(root/'target')}):
                    if fault:
                        with self.assertRaises(ProcessFailure) as error:angular.main(argv)
                        self.assertEqual(error.exception.reason,'injected-after-discovery')
                    else:self.assertEqual(angular.main(argv),0)
                for pid in map(int,children.read_text().split()):
                    with self.assertRaises(ProcessLookupError):os.kill(pid,0)
            for record in diagnostics.glob('*.json'):
                data=json.loads(record.read_text())
                self.assertEqual(data['evidenceKind'],'synthetic-process-contract')
                self.assertTrue(data['child']['cleanupAcknowledged'])
                self.assertFalse(data['cleanupFailures'])
                self.assertGreaterEqual(data['elapsedMs'],0)

    @unittest.skipUnless(os.environ.get('LSF_LIVE_OCI_DEMO') == '1', 'explicit prepared Docker fixture only')
    def test_live_provider_normal_and_injected_failure_leave_no_owned_container(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for fault in (False,True):
                state=root/'registry.json'
                diagnostics=Path(os.environ.get('LSF_OWNED_DEMO_DIAGNOSTICS',root/'diagnostics'))
                argv=['--check-fixture','--state-file',str(state),'--diagnostic-root',str(diagnostics)]
                with redirect_stdout(io.StringIO()):
                    if fault:
                        with self.assertRaises(ProcessFailure) as error:
                            oci.main([*argv,'--inject-failure','after-ready'])
                        self.assertEqual(error.exception.reason,'injected-after-ready')
                    else:self.assertEqual(oci.main(argv),0)
                self.assertFalse(state.exists())
            self.assertGreaterEqual(len(list(diagnostics.glob('*.json'))),2)


if __name__ == '__main__':
    unittest.main()

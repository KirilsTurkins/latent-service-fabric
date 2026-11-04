"""Exact artifact/list contracts, deliberate ignores, and non-libtest harnesses."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import ci_suite_discovery as discovery, ci_suite_inventory as registry
from tools.phase3_security_artifacts import listing, read_inventory, validate_result, validate_custom
from tools.ci_rust_artifacts import ArtifactError


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.suite = {'id': 'one.lib.one', 'mode': 'libtest', 'ignoredLeaves': ['external'], 'expectedIgnored': ['tests::external']}
        self.selected = {'external': {'suite': self.suite['id'], 'names': ['tests::external'],
                                     'filter': 'tests::external', 'exact': True, 'ignored': True}}

    def test_registered_cases_and_ignore_state_match_exact_security_primitives(self):
        discovery.validate_cases(self.suite, frozenset({'tests::works', 'tests::external'}),
                                 frozenset({'tests::external'}), self.selected)

    def test_empty_renamed_missing_unexpected_ignored_and_ambiguous_selection_fail(self):
        discovery.validate_cases(self.suite, frozenset({'tests::renamed','tests::external'}),
                                 frozenset({'tests::external'}), self.selected)
        variants = [(set(),set()), ({'tests::works'},set()),
                    ({'tests::works','tests::external'},{'tests::works','tests::external'}),
                    ({'tests::works','tests::external'},set())]
        for available, ignored in variants:
            with self.subTest(available=available, ignored=ignored), self.assertRaises((ValueError, ArtifactError)):
                discovery.validate_cases(self.suite, frozenset(available), frozenset(ignored), self.selected)
        self.selected['external'].update(filter='tests::', exact=False)
        self.suite['ignoredLeaves'].append('works')
        with self.assertRaises(ValueError):
            discovery.validate_cases(self.suite, frozenset({'tests::works','tests::external'}),
                                     frozenset({'tests::works','tests::external'}), self.selected)

    def test_test_free_targets_are_explicit_not_passing_empty_suites(self):
        self.suite.update(mode='compile-only', expectedIgnored=[])
        discovery.validate_cases(self.suite, frozenset(), frozenset(), {})
        with self.assertRaises(ValueError): discovery.validate_cases(self.suite, frozenset({'new'}), frozenset(), {})

    def test_libtest_and_custom_result_contracts_are_not_interchangeable(self):
        self.assertEqual(listing(b'a: test\n\n1 test, 0 benchmarks\n'), {'a'})
        for raw in (b'', b'0 tests, 0 benchmarks\na: test\n', b'a: test\na: test\n2 tests, 0 benchmarks\n'):
            with self.assertRaises(ArtifactError): listing(raw)
        observed = (b'test tests::works ... ok\ntest tests::external ... ignored, needs fixture\n'
                    b'test result: ok. 1 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out;\n')
        self.assertEqual(discovery.execution_cases(observed, frozenset({'tests::works', 'tests::external'}),
                                                   frozenset({'tests::external'})),
                         (['tests::works'], ['tests::external']))
        for bad in (observed + observed, observed.replace(b' ... ok', b' ... ignored'),
                    observed.replace(b'test tests::works ... ok\n', b'')):
            with self.assertRaises(ValueError):
                discovery.execution_cases(bad, frozenset({'tests::works', 'tests::external'}),
                                          frozenset({'tests::external'}))
        receipt = {"schemaVersion": "latent.ci.discovery.v1", "sourceRevision": "a" * 40,
                   "suites": [{"id": "one", "artifact": "one-abc", "cases": ["a", "b"], "ignored": ["b"]},
                              {"id": "empty", "artifact": "empty-abc", "cases": [], "ignored": []},
                              {"id": "custom", "artifact": "custom-abc", "contract": "custom-no-list", "successMarker": "custom passed"}]}
        log = ("    Running unittests lib.rs (target/debug/deps/one-abc)\n"
               "running 2 tests\ntest a ... ok\ntest b ... ignored\n"
               "test result: ok. 1 passed; 0 failed; 1 ignored; 0 measured; 0 filtered out;\n"
               "    Running unittests empty.rs (target/debug/deps/empty-abc)\n"
               "running 0 tests\ntest result: ok. 0 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out;\n"
               "    Running custom.rs (target/debug/deps/custom-abc)\ncustom passed\n")
        report, errors = discovery.workspace_execution(receipt, log)
        self.assertEqual(errors, [])
        self.assertEqual(report['suites'][0]['executed'], ['a'])
        self.assertEqual(report['suites'][0]['skipped'], ['b'])
        nested = log.replace("test a ... ok\n", "test a ... ok\ntest a ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored;\n", 1)
        self.assertTrue(discovery.workspace_execution(receipt, nested)[1])
        receipt['suites'][0]['nestedCases'] = ['a']
        self.assertFalse(discovery.workspace_execution(receipt, nested)[1])
        self.assertTrue(discovery.workspace_execution(receipt, nested.replace('test a ... ok\n', 'test foreign ... ok\n', 1))[1])
        receipt['suites'][0].pop('nestedCases')
        for bad in (log.replace('test a ... ok', 'test a ... FAILED'),
                    log.replace('test a ... ok\n', ''), log + log,
                    log.replace('custom passed', 'custom omitted')):
            self.assertTrue(discovery.workspace_execution(receipt, bad)[1])
        with patch.object(discovery, 'run_owned', side_effect=[(0, b''), (0, b'')]):
            state = discovery.source_state(Path.cwd())
        self.assertFalse(state['workingTreeModified'])
        with patch.object(discovery, 'run_owned', return_value=(0, b'?? new.rs\0')):
            with self.assertRaisesRegex(ValueError, 'untracked-source-identity'):
                discovery.source_state(Path.cwd())
        validate_custom(b'custom passed\n', 'custom passed')
        with self.assertRaises(ArtifactError): validate_custom(b'0 tests, 0 benchmarks\n', 'custom passed')
        with self.assertRaises(ArtifactError): validate_result(b'test result: ok. 0 passed; 0 failed;', 'a')

    def test_explicit_doctests_and_compatibility_feature_must_execute_nonempty_cases(self):
        data = registry.load()
        doctests = ('   Doc-tests latent_admission\nrunning 1 test\n'
                    'test admission example ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored;\n'
                    '   Doc-tests latent_scheduler\nrunning 1 test\n'
                    'test scheduler example ... ok\ntest result: ok. 1 passed; 0 failed; 0 ignored;\n')
        signing_names = data['recipes']['signing-compatibility']['requiredCases']
        def signing(names):
            return ('   Running unittests src/lib.rs (target/debug/deps/latent_signing-abcd)\n'
                    + ''.join('test ' + name + ' ... ok\n' for name in names)
                    + f'test result: ok. {len(names)} passed; 0 failed; 0 ignored;\n')
        doctest_listing = ('   Doc-tests latent_admission\nadmission example: test\n1 test, 0 benchmarks\n'
                           '   Doc-tests latent_scheduler\nscheduler example: test\n1 test, 0 benchmarks\n')
        signing_listing = ('   Running unittests src/lib.rs (target/debug/deps/latent_signing-abcd)\n'
                           + ''.join(name + ': test\n' for name in signing_names)
                           + f'{len(signing_names)} tests, 0 benchmarks\n')
        discovery.validate_recipe_execution(data, 'explicit-doctests', doctests, doctest_listing)
        compile_fail = doctests.replace('admission example ... ok', 'admission example - compile fail ... ok')
        discovery.validate_recipe_execution(data, 'explicit-doctests', compile_fail, doctest_listing)
        with self.assertRaisesRegex(ValueError, 'discovery-execution-mismatch'):
            discovery.validate_recipe_execution(data, 'explicit-doctests',
                                                compile_fail.replace('admission example', 'other example'), doctest_listing)
        split_streams = ('running 1 test\ntest admission example ... ok\n'
                         'test result: ok. 1 passed; 0 failed; 0 ignored;\n'
                         'running 1 test\ntest scheduler example ... ok\n'
                         'test result: ok. 1 passed; 0 failed; 0 ignored;\n'
                         '   Doc-tests latent_admission\n   Doc-tests latent_scheduler\n')
        discovery.validate_recipe_execution(data, 'explicit-doctests', split_streams)
        discovery.validate_recipe_execution(data, 'signing-compatibility', signing(signing_names), signing_listing)
        with self.assertRaisesRegex(ValueError, 'discovery-execution-mismatch'):
            discovery.validate_recipe_execution(data, 'signing-compatibility', signing(signing_names),
                                                signing_listing.replace(signing_names[0] + ': test', 'other: test'))
        # Ordinary additions do not require another count or case-list edit.
        discovery.validate_recipe_execution(data, 'signing-compatibility', signing(signing_names + ['crypto::tests::new_case']))
        for recipe, bad in (('explicit-doctests', doctests.replace('1 passed', '0 passed', 1)),
                            ('explicit-doctests', doctests.replace('Doc-tests latent_scheduler', 'Doc-tests wrong')),
                            ('signing-compatibility', signing(signing_names[:-1])),
                            ('signing-compatibility', signing(signing_names).replace(' ... ok', ' ... ignored', 1))):
            with self.subTest(recipe=recipe), self.assertRaises(ValueError):
                discovery.validate_recipe_execution(data, recipe, bad)

    def test_custom_execution_requires_every_exact_marker_once(self):
        data = registry.load()
        markers = [s['successMarker'] for s in data['suites'] if s['mode']=='custom']
        from tools.run_aot_tests import SUPERVISOR_CASES
        cases = '\n'.join(f'LSF_AOT_CASE {outcome} {name}' for name in sorted(SUPERVISOR_CASES)
                          for outcome in ('started', 'passed'))
        complete = '\n'.join([*markers, cases])
        discovery.validate_custom_execution(data, complete)
        for raw in ('',markers[0], '\n'.join(markers+markers), '\n'.join(markers),
                    complete.replace('LSF_AOT_CASE passed oversized\n', ''),
                    complete + '\nLSF_AOT_CASE passed oversized'):
            with self.assertRaises(ValueError): discovery.validate_custom_execution(data, raw)

    def test_custom_listing_uses_its_exact_hyphenated_case_contract(self):
        from tools.run_aot_tests import SUPERVISOR_CASES
        names = sorted(SUPERVISOR_CASES)
        raw = ('\n'.join(name + ': test' for name in names) + '\n23 tests, 0 benchmarks\n').encode()
        discovery.validate_custom_listing(raw, names)
        for bad in (raw.replace(b'active-shutdown', b'unknown-case'), raw + b'oversized: test\n',
                    raw.replace(b'active-shutdown: test\n', b''), raw.replace(b'23 tests', b'0 tests')):
            with self.assertRaises(ArtifactError):
                discovery.validate_custom_listing(bad, names)


    def test_guest_sdk_retains_active_shared_nominal_fixture_and_thirteen_ignored_guests(self):
        data = registry.load()
        suite = next(row for row in data['suites'] if row['id'] == 'latent-wasmtime.test.guest-sdk')
        name = 'streaming::fixture::phase_nominal_owner_has_no_operational_binding_or_session'
        source = registry.ROOT / 'crates/latent-wasmtime/tests/guest_sdk/streaming.rs'
        shared = registry.ROOT / 'crates/latent-wasmtime/tests/streaming_http/fixture.rs'
        self.assertIn('#[path = "../streaming_http/fixture.rs"]\n#[allow(dead_code, unused_imports)]\nmod fixture;',
                      source.read_text(encoding='utf-8'))
        self.assertIn('#[tokio::test]\nasync fn ' + name.rsplit('::', 1)[-1] + '()',
                      shared.read_text(encoding='utf-8'))
        ignored = frozenset(suite['expectedIgnored'])
        available = ignored | {name}
        discovery.validate_cases(suite, available, ignored, data['selections'])
        self.assertIn(name, suite['requiredCases'])
        self.assertNotIn(name, ignored)
        discovery.validate_cases(suite, available | {'ordinary::addition'}, ignored, data['selections'])
        for discovered, skipped in ((ignored, ignored), (available, available)):
            with self.subTest(discovered=discovered, ignored=skipped), self.assertRaises(ValueError):
                discovery.validate_cases(suite, discovered, skipped, data['selections'])


class ArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.manifest = self.root/'crate/Cargo.toml'; self.manifest.parent.mkdir()
        self.manifest.write_text('[package]\nname="one"\n')
        self.source = self.root/'crate/lib.rs'; self.source.write_text('')
        self.exe = self.root/'target/debug/deps/one'; self.exe.parent.mkdir(parents=True); self.exe.write_bytes(b'x')
        self.group = discovery.Group('one.lib.one', 'crate/Cargo.toml', 'one', 'lib', 'lib.rs')
        self.row = {'reason':'compiler-artifact','manifest_path':str(self.manifest), 'package_id':'one',
                    'target':{'name':'one','kind':['lib'],'src_path':str(self.source)},
                    'profile':{'test':True}, 'executable':str(self.exe)}
        self.file = self.root/'cargo.jsonl'
        self.finish = {'reason':'build-finished','success':True}

    def save(self, records): self.file.write_text(''.join(json.dumps(r)+'\n' for r in records))
    def read(self): return read_inventory(self.file,self.root,(self.group,))

    def test_shared_exact_artifact_reader_rejects_missing_duplicate_wrong_owner_and_failed_build(self):
        self.save([self.row,self.finish]); self.assertEqual(self.read()[self.group.key].executable,self.exe)
        for records in ([self.finish],[self.row,self.row,self.finish],[self.row],
                        [self.row,{'reason':'build-finished','success':False}], [self.row,self.finish,{}]):
            self.save(records)
            with self.subTest(records=records), self.assertRaises(ArtifactError): self.read()
        for field,value in [('name','wrong'),('src_path',str(self.manifest)),('kind',['test'])]:
            row=copy.deepcopy(self.row);row['target'][field]=value;self.save([row,self.finish])
            with self.subTest(field=field),self.assertRaises(ArtifactError): self.read()

    def test_custom_harness_never_receives_libtest_list_arguments(self):
        self.save([self.row,self.finish])
        suite={'id':self.group.key,'manifest':self.group.manifest,'target':'one','kind':'lib','source':'lib.rs',
               'package':'one','mode':'custom','sourceSha256':hashlib.sha256(b'').hexdigest(),'successMarker':'done'}
        data={'suites':[suite], 'selections':{}}
        # A custom-only inventory is not enough correctness coverage, but its
        # executable must not have been probed while detecting that omission.
        with patch.object(discovery,'run_owned') as run,self.assertRaisesRegex(ValueError,'no-active'):
            discovery.discover(self.root,self.file,data)
        run.assert_not_called()

    def test_unregistered_executable_is_not_silently_dropped(self):
        extra=copy.deepcopy(self.row); extra['target']['name']='unregistered'
        self.save([self.row,extra,self.finish])
        suite={'id':self.group.key,'manifest':self.group.manifest,'target':'one','kind':'lib','source':'lib.rs','package':'one'}
        with self.assertRaisesRegex(ValueError,'unregistered'):
            discovery.discover(self.root,self.file,{'suites':[suite]})

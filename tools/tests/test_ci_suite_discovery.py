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
        self.suite = {'id': 'one.lib.one', 'mode': 'libtest', 'minimumCases': 1,
                      'ignoredLeaves': ['external'], 'expectedCases': ['tests::works', 'tests::external']}
        self.selected = {'external': {'suite': self.suite['id'], 'names': ['tests::external'],
                                     'filter': 'tests::external', 'exact': True, 'ignored': True}}

    def test_registered_cases_and_ignore_state_match_exact_security_primitives(self):
        discovery.validate_cases(self.suite, frozenset(self.suite['expectedCases']),
                                 frozenset({'tests::external'}), self.selected)

    def test_empty_renamed_missing_unexpected_ignored_and_ambiguous_selection_fail(self):
        variants = [(set(),set()), ({'tests::renamed','tests::external'},{'tests::external'}),
                    ({'tests::works','tests::external'},{'tests::works','tests::external'}),
                    ({'tests::works','tests::external'},set())]
        for available, ignored in variants:
            with self.subTest(available=available, ignored=ignored), self.assertRaises((ValueError, ArtifactError)):
                discovery.validate_cases(self.suite, frozenset(available), frozenset(ignored), self.selected)
        self.suite.pop('expectedCases')
        self.selected['external'].update(filter='tests::', exact=False)
        self.suite['ignoredLeaves'].append('works')
        with self.assertRaises(ValueError):
            discovery.validate_cases(self.suite, frozenset({'tests::works','tests::external'}),
                                     frozenset({'tests::works','tests::external'}), self.selected)

    def test_test_free_targets_are_explicit_not_passing_empty_suites(self):
        self.suite.update(mode='compile-only', expectedCases=[])
        discovery.validate_cases(self.suite, frozenset(), frozenset(), {})
        with self.assertRaises(ValueError): discovery.validate_cases(self.suite, frozenset({'new'}), frozenset(), {})

    def test_libtest_and_custom_result_contracts_are_not_interchangeable(self):
        self.assertEqual(listing(b'a: test\n\n1 test, 0 benchmarks\n'), {'a'})
        for raw in (b'', b'0 tests, 0 benchmarks\na: test\n', b'a: test\na: test\n2 tests, 0 benchmarks\n'):
            with self.assertRaises(ArtifactError): listing(raw)
        validate_custom(b'custom passed\n', 'custom passed')
        with self.assertRaises(ArtifactError): validate_custom(b'0 tests, 0 benchmarks\n', 'custom passed')
        with self.assertRaises(ArtifactError): validate_result(b'test result: ok. 0 passed; 0 failed;', 'a')

    def test_explicit_doctests_and_compatibility_feature_must_execute_nonempty_cases(self):
        data = registry.load()
        for recipe, counts in [('explicit-doctests', [1,1]), ('signing-compatibility', [5])]:
            raw = '\n'.join(f'test result: ok. {n} passed; 0 failed; 0 ignored;' for n in counts)
            discovery.validate_recipe_execution(data, recipe, raw)
            for bad in ('', raw.replace('1 passed', '0 passed').replace('5 passed', '0 passed'), raw + '\n' + raw):
                with self.subTest(recipe=recipe), self.assertRaises(ValueError):
                    discovery.validate_recipe_execution(data, recipe, bad)

    def test_custom_execution_requires_every_exact_marker_once(self):
        data = registry.load()
        markers = [s['successMarker'] for s in data['suites'] if s['mode']=='custom']
        discovery.validate_custom_execution(data, '\n'.join(markers))
        for raw in ('',markers[0], '\n'.join(markers+markers)):
            with self.assertRaises(ValueError): discovery.validate_custom_execution(data, raw)


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

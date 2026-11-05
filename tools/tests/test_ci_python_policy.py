from __future__ import annotations

import unittest
from tools.ci_python_policy import require_no_new_controls


class PythonSuppressionPolicyTests(unittest.TestCase):
    def test_ordinary_case_and_unrelated_helper_edits_do_not_require_a_catalogue(self):
        before = 'import unittest\nclass Cases(unittest.TestCase):\n def test_old(self): self.assertTrue(True)\ndef helper(): return 1\n'
        after = before.replace('test_old', 'test_new').replace('return 1', 'return 1 + 0')
        require_no_new_controls(before, after)

    def test_new_suppression_or_discovery_override_is_refused(self):
        before = 'import unittest\nclass Cases(unittest.TestCase):\n def test_one(self): pass\n'
        for addition in (" def test_two(self): self.skipTest('later')\n",
                         ' def run(self, result=None): return result\n',
                         'def load_tests(loader, tests, pattern): return unittest.TestSuite()\n',
                         ' __unittest_skip__ = True\n'):
            with self.subTest(addition=addition), self.assertRaisesRegex(ValueError, 'suppression'):
                require_no_new_controls(before, before + addition)

    def test_existing_exception_binding_and_condition_cannot_change_silently(self):
        before = "import unittest\nSKIP = False\nclass Cases(unittest.TestCase):\n @unittest.skipIf(SKIP, 'native')\n def test_one(self): pass\n"
        require_no_new_controls(before, before)
        with self.assertRaisesRegex(ValueError, 'suppression'):
            require_no_new_controls(before, before.replace('SKIP = False', 'SKIP = True'))
        with self.assertRaisesRegex(ValueError, 'suppression'):
            require_no_new_controls(before, before.replace("'native'", "'other'"))
        local = "import unittest\nclass Cases(unittest.TestCase):\n def test_one(self):\n  flag = False\n  if flag: self.skipTest('native')\n"
        with self.assertRaisesRegex(ValueError, 'suppression'):
            require_no_new_controls(local, local.replace('flag = False', 'flag = True'))
        aliased = before.replace('import unittest', 'import unittest\nfrom unittest import skip as suppress').replace('@unittest.skipIf(SKIP, \'native\')', '@suppress')
        with self.assertRaisesRegex(ValueError, 'suppression'):
            require_no_new_controls(before, aliased)

    def test_existing_skip_cannot_be_enabled_by_changing_a_predicate_helper(self):
        before = "import unittest\ndef available(): return False\ndef disabled(): return available()\nclass Cases(unittest.TestCase):\n def test_one(self):\n  if disabled(): self.skipTest('native')\n"
        require_no_new_controls(before, before)
        with self.assertRaisesRegex(ValueError, 'suppression'):
            require_no_new_controls(before, before.replace('return False', 'return True'))

class PythonExecutionReceiptTests(unittest.TestCase):
    def test_failed_subtests_account_for_the_discovered_parent_once(self):
        import io
        from tools.ci_python_policy import flatten_suite, recording_result_class, execution_receipt
        class Fixture(unittest.TestCase):
            def test_subtests(self):
                for value in (1, 2):
                    with self.subTest(value=value): self.fail('injected subtest failure')
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Fixture)
        discovered = flatten_suite(suite)
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=recording_result_class(lambda *_: False)).run(suite)
        receipt = execution_receipt(discovered, result, source_identity={'revision': 'a' * 40}, recipe_identity='test')
        self.assertEqual(receipt['failed'], discovered)
        self.assertIn('test-failure', receipt['errors'])
        self.assertNotIn('discovery-execution-mismatch', receipt['errors'])

    def test_discovery_execution_skips_and_failures_are_observed(self):
        import io
        from tools.ci_python_policy import flatten_suite, recording_result_class, execution_receipt
        class DiscoveryReceiptFixture(unittest.TestCase):
            def test_pass(self): pass
            @unittest.skip('optional')
            def test_skip(self): pass
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(DiscoveryReceiptFixture)
        discovered = flatten_suite(suite)
        runner = unittest.TextTestRunner(stream=io.StringIO(), resultclass=recording_result_class(lambda name, reason: False))
        result = runner.run(suite)
        receipt = execution_receipt(discovered, result, source_identity={'revision': 'a' * 40}, recipe_identity='test')
        self.assertEqual(len(receipt['executed']), 1)
        self.assertEqual(len(receipt['skipped']), 1)
        self.assertEqual(len(receipt['errors']), 1)
        self.assertTrue(receipt['errors'][0].startswith('skip:'))
        self.assertIn('discovery-execution-mismatch', execution_receipt(discovered + ['missing'], result, source_identity={'revision': 'a' * 40}, recipe_identity='test')['errors'])

    def test_expected_failure_and_duplicate_discovery_fail_closed(self):
        import io
        from tools.ci_python_policy import flatten_suite, recording_result_class, execution_receipt
        class Fixture(unittest.TestCase):
            @unittest.expectedFailure
            def test_expected_failure(self): self.fail('not a pass')
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Fixture)
        discovered = flatten_suite(suite)
        result = unittest.TextTestRunner(stream=io.StringIO(), resultclass=recording_result_class(lambda *_: True)).run(suite)
        self.assertIn('test-failure', execution_receipt(discovered, result, source_identity={'revision': 'a' * 40}, recipe_identity='test')['errors'])
        case = Fixture('test_expected_failure')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            flatten_suite(unittest.TestSuite([case, case]))

class PythonSkipAuthorizationTests(unittest.TestCase):
    def test_reason_must_belong_to_the_case_or_its_own_fixture(self):
        from tools.ci_python_policy import permitted_skip
        source = """import unittest
class Cases(unittest.TestCase):
 @unittest.skip('first reason')
 def test_first(self): pass
 def test_second(self): pass
 def setUp(self):
  if False: self.skipTest('fixture reason')
class Other(unittest.TestCase):
 @unittest.skip('other reason')
 def test_other(self): pass
"""
        self.assertTrue(permitted_skip(source, 'Cases', 'test_first', 'first reason'))
        self.assertTrue(permitted_skip(source, 'Cases', 'test_second', 'fixture reason'))
        self.assertFalse(permitted_skip(source, 'Cases', 'test_second', 'first reason'))
        self.assertFalse(permitted_skip(source, 'Cases', 'test_second', 'other reason'))
        self.assertFalse(permitted_skip(source, 'Missing', 'test_first', 'first reason'))
        dynamic = source.replace("self.skipTest('fixture reason')", "self.skipTest(f'fixture reason: {error}')")
        self.assertTrue(permitted_skip(dynamic, 'Cases', 'test_second', 'fixture reason: denied'))
        self.assertFalse(permitted_skip(dynamic, 'Cases', 'test_second', 'unrelated'))
        helper = "import unittest\ndef prerequisite(): raise unittest.SkipTest('missing native')\nclass Cases(unittest.TestCase):\n @classmethod\n def setUpClass(cls): prerequisite()\n def test_one(self): pass\n"
        self.assertTrue(permitted_skip(helper, 'Cases', None, 'missing native'))
        self.assertFalse(permitted_skip(helper.replace('def setUpClass(cls): prerequisite()', 'def setUpClass(cls): pass'), 'Cases', None, 'missing native'))
        same_class = "import unittest\nclass Cases(unittest.TestCase):\n def prerequisite(self): self.skipTest('missing frontend')\n def test_one(self): self.prerequisite()\n def test_other(self): pass\n"
        self.assertTrue(permitted_skip(same_class, 'Cases', 'test_one', 'missing frontend'))
        self.assertFalse(permitted_skip(same_class, 'Cases', 'test_other', 'missing frontend'))
        other_class = "import unittest\nclass Original(unittest.TestCase):\n @classmethod\n def setUpClass(cls): raise unittest.SkipTest('missing sandbox')\nclass Cases(unittest.TestCase):\n @classmethod\n def setUpClass(cls): Original.setUpClass()\n def test_one(self): pass\n"
        self.assertTrue(permitted_skip(other_class, 'Cases', None, 'missing sandbox'))
        external = "import unittest\nclass Cases(unittest.TestCase):\n @classmethod\n def setUpClass(cls):\n  from tools.tests.test_native_helper import prerequisite\n  prerequisite()\n def test_one(self): pass\n"
        sources = {'test_native_helper': "import unittest\ndef prerequisite(): raise unittest.SkipTest('missing host')\n"}
        self.assertTrue(permitted_skip(external, 'Cases', None, 'missing host', sources))
        instance = "class Cases:\n def test_one(self):\n  from tools.tests.test_native_helper import Native\n  Native().prerequisite()\n"
        sources = {'test_native_helper': "class Native:\n def prerequisite(self): self.skipTest('missing frontend')\n"}
        self.assertTrue(permitted_skip(instance, 'Cases', 'test_one', 'missing frontend', sources))
        self.assertFalse(permitted_skip(instance.replace('Native().prerequisite()', 'pass'), 'Cases', 'test_one', 'missing frontend', sources))

class PythonFixtureReceiptTests(unittest.TestCase):
    def test_authorized_class_skip_accounts_for_every_discovered_case(self):
        import io
        from tools.ci_python_policy import flatten_suite, recording_result_class, execution_receipt
        class Fixture(unittest.TestCase):
            @classmethod
            def setUpClass(cls): raise unittest.SkipTest('native prerequisite')
            def test_first(self): pass
            def test_second(self): pass
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(Fixture)
        discovered = flatten_suite(suite)
        runner = unittest.TextTestRunner(stream=io.StringIO(), resultclass=recording_result_class(lambda *_: True))
        receipt = execution_receipt(discovered, runner.run(suite), source_identity={'revision': 'a' * 40}, recipe_identity='test')
        self.assertEqual(receipt['skipped'], discovered)
        self.assertEqual(receipt['errors'], [])

class PythonOwnedExecutionTests(unittest.TestCase):
    def test_current_discovery_is_compared_to_execution_and_baseline_skip_reasons(self):
        import io
        from tools.ci_python_policy import run_discovered
        class Fixture(unittest.TestCase):
            def test_pass(self): pass
            @unittest.skip('approved native prerequisite')
            def test_skip(self): pass
        baseline = "import unittest\nclass Fixture(unittest.TestCase):\n @unittest.skip('approved native prerequisite')\n def test_skip(self): pass\n"
        def execute(sources):
            suite = unittest.defaultTestLoader.loadTestsFromTestCase(Fixture)
            return run_discovered(suite, baseline_sources=sources, current_sources=sources, source_identity={'revision': 'a' * 40}, recipe_identity='python', stream=io.StringIO())
        # Nested classes deliberately use a qualified owner and fail closed.
        receipt = execute({__name__: baseline})
        self.assertTrue(receipt['errors'])
        self.assertEqual(len(receipt['discovered']), 2)

class PythonSourcePolicyTests(unittest.TestCase):
    def test_imported_skip_predicate_cannot_be_enabled_through_a_helper_edit(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import subprocess
        from tools.ci_python_policy import imported_skip_predicates, verify_source_tree
        with TemporaryDirectory() as temporary:
            repo = Path(temporary)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=repo, stderr=subprocess.STDOUT, text=True).strip()
            git('init', '-q'); git('config', 'user.name', 'Fixture'); git('config', 'user.email', 'fixture@example.invalid')
            tests = repo / 'tools/tests'; tests.mkdir(parents=True)
            helper = repo / 'tools/checks.py'
            helper.write_text('FLAG = False\ndef disabled(): return available()\ndef available(): return FLAG\ndef unrelated(): return 1\n')
            (tests / 'test_demo.py').write_text("import unittest\nfrom tools.checks import disabled\nclass Cases(unittest.TestCase):\n def test_one(self):\n  if disabled(): self.skipTest('native')\n")
            self.assertEqual(imported_skip_predicates("from tools import checks as c\nimport unittest\n@unittest.skipIf(c.disabled(), 'native')\nclass Cases(unittest.TestCase): pass\n"), {('tools/checks.py', 'disabled')})
            self.assertEqual(imported_skip_predicates("from tools.checks import disabled\nclass Cases:\n def gate(self): return disabled()\n def test_one(self):\n  if self.gate(): self.skipTest('native')\n"), {('tools/checks.py', 'disabled')})
            git('add', '.'); git('commit', '-qm', 'baseline'); baseline = git('rev-parse', 'HEAD')
            original = helper.read_text()
            helper.write_text(original.replace('return 1', 'return 1 + 0'))
            verify_source_tree(repo, baseline)
            helper.write_text(original.replace('FLAG = False', 'FLAG = True'))
            with self.assertRaisesRegex(ValueError, 'suppression'):
                verify_source_tree(repo, baseline)

    def test_baseline_is_commit_bound_and_missing_history_fails(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        import subprocess
        from tools.ci_python_policy import source_pairs
        with TemporaryDirectory() as tmp:
            repo = Path(tmp)
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            tests = repo / 'tools/tests'
            tests.mkdir(parents=True)
            path = tests / 'test_demo.py'
            path.write_text('import unittest\nclass Cases(unittest.TestCase):\n def test_a(self): pass\n')
            subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
            subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'baseline'], cwd=repo, check=True)
            revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip()
            old = path.read_text()
            path.write_text(old.replace('test_a', 'test_b'))
            before, current = source_pairs(repo, revision, ['test_demo'])
            self.assertEqual(before['test_demo'], old)
            self.assertIn('test_b', current['test_demo'])
            with self.assertRaisesRegex(ValueError, 'baseline-unavailable'):
                source_pairs(repo, 'a' * 40, ['test_demo'])

class PythonIndependentAdditionsTests(unittest.TestCase):
    def test_independent_branch_additions_merge_and_execute_without_case_catalogue(self):
        import io
        import subprocess
        import sys
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from tools.ci_python_policy import execute_python
        with TemporaryDirectory() as temporary:
            repo = Path(temporary)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=repo, stderr=subprocess.STDOUT, text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (repo / '.gitignore').write_text('__pycache__/\n')
            tests = repo / 'tools/tests'
            tests.mkdir(parents=True)
            first, second = tests / 'test_lsf_policy_branch_a.py', tests / 'test_lsf_policy_branch_b.py'
            base_text = 'import unittest\nclass Cases(unittest.TestCase):\n def test_initial(self): self.assertTrue(True)\n'
            first.write_text(base_text); second.write_text(base_text)
            git('add', '.')
            git('commit', '-qm', 'baseline')
            base = git('rev-parse', 'HEAD')
            git('checkout', '-qb', 'first')
            first.write_text(base_text + ' def test_first(self): self.assertTrue(True)\n')
            git('commit', '-qam', 'first addition')
            git('checkout', '-qb', 'second', base)
            second.write_text(base_text + ' def test_second(self): self.assertTrue(True)\n')
            git('commit', '-qam', 'second addition')
            git('merge', '--no-edit', 'first')
            original_path = list(sys.path)
            try:
                receipt = execute_python(repo, base, stream=io.StringIO(), required_controls=frozenset())
                missing = execute_python(repo, base, stream=io.StringIO(), required_controls=frozenset({'required.missing'}))
                self.assertIn('missing-required-python-controls', missing['errors'])
            finally:
                sys.path[:] = original_path
                for name in ('test_lsf_policy_branch_a', 'test_lsf_policy_branch_b'):
                    sys.modules.pop(name, None)
            self.assertEqual(receipt['errors'], [])
            self.assertEqual(len(receipt['discovered']), 4)
            self.assertEqual(receipt['discovered'], receipt['executed'])
            self.assertTrue(any(name.endswith('.test_first') for name in receipt['executed']))
            self.assertTrue(any(name.endswith('.test_second') for name in receipt['executed']))

class PythonEventBaselineTests(unittest.TestCase):
    def test_only_explicit_event_boundaries_are_accepted(self):
        from tools.ci_python_policy import event_baseline
        a, b = 'a' * 40, 'b' * 40
        self.assertEqual(event_baseline('pull_request', {'pull_request': {'base': {'sha': a}}}, b), a)
        self.assertEqual(event_baseline('push', {'before': a}, b), a)
        self.assertEqual(event_baseline('workflow_dispatch', {}, b), b)
        for event, payload in [('pull_request', {}), ('push', {'before': '0' * 40}), ('other', {})]:
            with self.subTest(event=event), self.assertRaises(ValueError):
                event_baseline(event, payload, b)

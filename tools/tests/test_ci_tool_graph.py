import tempfile
from pathlib import Path
import unittest
from tools.ci_tool_graph import affected, observe


class ToolGraphTests(unittest.TestCase):
    def fixture(self, root):
        (root / 'tools/tests').mkdir(parents=True)
        (root / 'tools/__init__.py').write_text('')
        (root / 'tools/shared.py').write_text('VALUE = 1\n')
        (root / 'tools/tests/test_first.py').write_text('from tools import shared\n')
        (root / 'tools/tests/test_second.py').write_text('from tools.tests import test_first\n')

    def test_reverse_dependencies_and_old_new_union(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            old = observe(root)
            (root / 'tools/tests/test_second.py').write_text('from tools import shared\n')
            new = observe(root)
            owners, reason = affected((old, new), {'tools/tests/test_first.py'}, history_complete=True, regular_modes=True)
            self.assertEqual(reason, 'resolved')
            self.assertIn('tools/tests/test_second.py', owners)
            owners, reason = affected((old, new), {'tools/shared.py'}, history_complete=True, regular_modes=True)
            self.assertEqual(reason, 'resolved')
            self.assertEqual(owners, {'tools/shared.py', 'tools/tests/test_first.py', 'tools/tests/test_second.py'})

    def test_unknown_path_and_dynamic_import_never_narrow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            (root / 'tools/shared.py').write_text('import importlib\nimportlib.import_module(variable)\n')
            graph = observe(root)
            self.assertEqual(affected((graph,), {'tools/shared.py'}, history_complete=True, regular_modes=True)[1], 'full-unresolved-dynamic-import')
            self.assertEqual(affected((graph,), {'tools/not-present.py'}, history_complete=True, regular_modes=True)[1], 'full-unknown-path')

    def test_new_reverse_dependency_is_included_and_deletion_is_conservative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            (root / 'tools/tests/test_second.py').write_text('VALUE = 1\n')
            old = observe(root)
            (root / 'tools/tests/test_second.py').write_text('from tools.tests import test_first\n')
            new = observe(root)
            owners, reason = affected((old, new), {'tools/tests/test_first.py'}, history_complete=True, regular_modes=True)
            self.assertEqual(reason, 'resolved')
            self.assertIn('tools/tests/test_second.py', owners)
            (root / 'tools/tests/test_first.py').unlink()
            deleted = observe(root)
            self.assertEqual(affected((old, deleted), {'tools/tests/test_first.py'}, history_complete=True, regular_modes=True)[1], 'full-unknown-path')

    def test_shared_helper_acquiring_a_native_consumer_is_reachable(self):
        from tools.ci_tool_graph import forward_dependencies
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            native = root / 'tools/native_consumer.py'
            native.write_text('from tools import shared\n')
            graph = observe(root)
            native_closure = forward_dependencies(graph, {'tools/native_consumer.py'})
            self.assertIn('tools/shared.py', native_closure)
            self.assertTrue(graph.dependents({'tools/shared.py'}) & native_closure)

    def test_dynamic_script_or_unscoped_test_discovery_cannot_be_excluded(self):
        from tools.ci_tool_graph import qualification_roots
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            (root / 'sdk').mkdir()
            workflows = root / '.github/workflows'; workflows.mkdir(parents=True)
            names = ('c-guest-authoring.yml', 'java-guest-feasibility.yml', 'rust-capsule-authoring.yml')
            for name in names: (workflows / name).write_text('run: python3 tools/shared.py\n')
            graph = observe(root)
            for command in ('python3 -m unittest discover -s tools/tests', 'python3 "$SCRIPT"'):
                (workflows / names[0]).write_text('run: ' + command + '\n')
                with self.subTest(command=command), self.assertRaisesRegex(ValueError, 'unresolved'):
                    qualification_roots(root, graph)

    def test_aliased_dynamic_imports_never_narrow(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            (root / 'tools/shared.py').write_text('from importlib import import_module as load\nload(name)\n')
            graph = observe(root)
            self.assertEqual(affected((graph,), {'tools/shared.py'}, history_complete=True, regular_modes=True)[1], 'full-unresolved-dynamic-import')
            (root / 'tools/shared.py').write_text('import importlib\nloader = importlib.import_module\nloader(name)\n')
            graph = observe(root)
            self.assertEqual(affected((graph,), {'tools/shared.py'}, history_complete=True, regular_modes=True)[1], 'full-unresolved-dynamic-import')

    def test_fixture_inputs_select_their_owner_and_escape_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            (root / 'tools/tests/example.json').write_text('{}')
            graph = observe(root, {'tools/tests/test_first.py': {'tools/tests/example.json'}},
                            {'tools/tests/example.json'})
            owners, reason = affected((graph,), {'tools/tests/example.json'}, history_complete=True, regular_modes=True)
            self.assertEqual(reason, 'resolved')
            self.assertIn('tools/tests/test_first.py', owners)
            with self.assertRaisesRegex(ValueError, 'unsafe-tool-input'):
                observe(root, extra_inputs={'../outside'})

    def test_missing_history_or_ambiguous_mode_falls_back(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); self.fixture(root)
            graph = observe(root)
            self.assertEqual(affected((graph,), {'tools/shared.py'})[1], 'full-history-unavailable')
            self.assertEqual(affected((graph,), {'tools/shared.py'}, history_complete=True)[1], 'full-ambiguous-mode')

class IsolatedDocumentationTestTests(unittest.TestCase):
    def test_only_additive_pure_validator_assertions_are_eligible(self):
        from tools.ci_tool_graph import isolated_doc_test_additions
        before = 'import unittest\nclass DocumentationValidationTests(unittest.TestCase):\n def report(self): return validator.validate_docs(self.root, self.tracked, require_documents=False)\n def test_old(self): pass\n'
        good = before + " def test_new(self):\n  report = self.report()\n  self.assertEqual(report['errors'], [])\n"
        self.assertTrue(isolated_doc_test_additions(before, good))
        for bad in (good.replace("self.report()", "open('/etc/passwd')"),
                    good.replace('test_old', 'test_changed'),
                    good.replace('self.assertEqual', 'self.run'),
                    good + 'import subprocess\n', before):
            with self.subTest(source=bad): self.assertFalse(isolated_doc_test_additions(before, bad))

class DynamicLoaderControlTests(unittest.TestCase):
    def test_unrecognized_dynamic_owner_is_not_treated_as_resolved(self):
        from tools.ci_tool_graph import resolved_dynamic_exclusions
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); (root / 'tools').mkdir()
            (root / 'tools/compile_transaction_guests.py').write_text('import importlib\nimportlib.import_module(name)\n')
            self.assertEqual(resolved_dynamic_exclusions(root, 'tools/tests/test_validate_docs.py',
                                                         {'tools/compile_transaction_guests.py'}), set())

class WorkflowTriggerTests(unittest.TestCase):
    def test_path_filter_parser_rejects_unknown_and_does_not_trust_negation(self):
        from tools.ci_tool_graph import pull_request_paths, workflow_triggers_are_scoped
        self.assertEqual(pull_request_paths("on:\n  pull_request:\n    paths:\n      - 'tools/**'\n      - '!tools/tests/**'\njobs: {}\n"), ['tools/**', '!tools/tests/**'])
        self.assertIsNone(pull_request_paths('on:\n  pull_request:\njobs: {}\n'))
        with self.assertRaises(ValueError): pull_request_paths('on: [pull_request]\njobs: {}\n')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); directory = root / '.github/workflows'; directory.mkdir(parents=True)
            (directory / 'unexpected.yml').write_text('on:\n  pull_request:\n    paths:\n      - tools/**\n      - "!tools/tests/**"\njobs: {}\n')
            self.assertFalse(workflow_triggers_are_scoped(root, 'tools/tests/test_validate_docs.py'))
            (directory / 'unexpected.yml').write_text('on:\n  workflow_run:\n    workflows: [CI]\n    types: [completed]\njobs: {}\n')
            self.assertFalse(workflow_triggers_are_scoped(root, 'tools/tests/test_validate_docs.py'))

class ToolingProfileIntegrationTests(unittest.TestCase):
    def test_only_clean_single_additive_test_with_resolved_consumers_selects_docs(self):
        import subprocess
        from unittest import mock
        from tools import ci_profile
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def git(*args):
                return subprocess.check_output(['git', *args], cwd=root, stderr=subprocess.STDOUT, text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            target = root / 'tools/tests/test_validate_docs.py'
            target.parent.mkdir(parents=True)
            before = 'import unittest\nclass DocumentationValidationTests(unittest.TestCase):\n def report(self): return validator.validate_docs(self.root, self.tracked, require_documents=False)\n def test_old(self): pass\n'
            target.write_text(before)
            git('add', '.'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD')
            target.write_text(before + " def test_new(self):\n  report = self.report()\n  self.assertEqual(report['errors'], [])\n")
            git('add', '.'); git('commit', '-qm', 'test'); head = git('rev-parse', 'HEAD')
            event = {'pull_request': {'base': {'sha': base}, 'head': {'sha': head}}}
            with mock.patch('tools.ci_tool_graph.isolated_qualification_scope', return_value=(True, 'documentation-validator-tests')):
                selected = ci_profile.classify_event('pull_request', event, root)
                self.assertEqual((selected.profile, selected.reason), ('docs', 'isolated-tooling:documentation-validator-tests'))
                (root / 'unknown').write_text('unknown')
                self.assertEqual(ci_profile.classify_event('pull_request', event, root).profile, 'full')
                (root / 'unknown').unlink()
            with mock.patch('tools.ci_tool_graph.isolated_qualification_scope', return_value=(False, 'unresolved')):
                self.assertEqual(ci_profile.classify_event('pull_request', event, root).profile, 'full')

"""Only an explicit public-fixture selection changes the bounded Gradle flags."""
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from tools.java_guest import c_failure_context as context


class JavaTeavmFailureTrace(unittest.TestCase):
    def test_default_command_is_exact_and_public_fixture_adds_only_stacktrace(self):
        project = Path('owned-project')
        for offline in (False, True):
            for selected in ((), context.FIXTURE_SOURCES):
                compiler = SimpleNamespace(offline=offline, run=Mock(return_value='original-result'))
                self.assertEqual(context.teavm(compiler, project, selected), 'original-result')
                expected = ['java-to-c', 'gradle', '--no-daemon']
                if offline: expected.append('--offline')
                if selected: expected.append('--stacktrace')
                expected.append('generateC')
                compiler.run.assert_called_once_with(*expected, cwd=project)

    def test_original_failure_is_preserved_without_another_compile_attempt(self):
        original = RuntimeError('original-captured-compiler-failure')
        for selected in ((), context.FIXTURE_SOURCES):
            compiler = SimpleNamespace(offline=True, run=Mock(side_effect=original))
            with self.assertRaises(RuntimeError) as error:
                context.teavm(compiler, Path('owned-project'), selected)
            self.assertIs(error.exception, original)
            compiler.run.assert_called_once()

    def test_unknown_or_mutable_selection_refuses_before_any_command(self):
        for selected in (None, True, 'public', list(context.FIXTURE_SOURCES),
                ('../private.java',), (*context.FIXTURE_SOURCES, 'other.c')):
            compiler = SimpleNamespace(offline=True, run=Mock())
            with self.subTest(selected=selected), self.assertRaises(ValueError):
                context.teavm(compiler, Path('owned-project'), selected)
            compiler.run.assert_not_called()

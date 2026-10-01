"""Exact build-tool identity/profile approval is separate from capturing bytes."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from tools.application_dependency_approval import approve, request
from tools.application_dependencies import LOCK, MANIFEST, capture, prepare, verify_inputs
from tools.application_dependency_store import DependencyError
from tools.build_snapshot import canonical, digest


class ExecutionApproval(unittest.TestCase):
    def fixture(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        project, tool, work, output = (root / name for name in ('project', 'tool', 'work', 'output'))
        for path in (project, tool, work, output): path.mkdir()
        (tool / 'build.rs').write_bytes(b'fn main() {}')
        (project / MANIFEST).write_bytes(canonical({'formatVersion': 1, 'language': 'rust', 'selection': {'runtimeProfile': 'closed'},
            'nativeLocks': [], 'artifacts': [{'id': 'outside/build-script/1', 'role': 'build-tool', 'format': 'directory',
                'mount': 'dependencies/build-tool', 'source': {'path': str(tool)}, 'dependencies': [], 'metadata': {}}], 'transformations': []}))
        (project / LOCK).write_bytes(canonical(capture(project)))
        verified = verify_inputs(project, 'rust')
        isolation = Mock()
        isolation.workspace = root.resolve()
        isolation.receipt = {'profile': 'linux-captured-compiler-namespaces-v1', 'tools': {'compiler': digest(b'tool')}}
        return project, work, output, verified, isolation

    def test_exact_approval_allows_materialization_only_in_selected_isolated_stage(self):
        project, work, output, verified, isolation = self.fixture()
        specification = request(verified, isolation, digest(b'recipe'))
        approval = approve(verified, isolation, digest(b'recipe'), digest(canonical(specification)))
        closure = prepare(project, work, output, 'rust', execution_approval=approval)
        self.assertEqual(closure.identity, verified.identity)
        self.assertTrue((work / 'dependencies/build-tool/build.rs').is_file())
        isolation.check_unchanged.assert_called_once()

    def test_stale_compiler_profile_recipe_or_approval_digest_fails(self):
        _project, work, _output, verified, isolation = self.fixture()
        specification = request(verified, isolation, digest(b'recipe'))
        identity = digest(canonical(specification))
        with self.assertRaisesRegex(DependencyError, 'approval-mismatch'):
            approve(verified, isolation, digest(b'other-recipe'), identity)
        approval = approve(verified, isolation, digest(b'recipe'), identity)
        isolation.receipt['tools']['compiler'] = digest(b'changed')
        with self.assertRaisesRegex(DependencyError, 'stale'):
            approval.validate(verified, work)

    def test_namespace_outside_the_owned_build_cannot_consume_approval(self):
        _project, _work, _output, verified, isolation = self.fixture()
        specification = request(verified, isolation, digest(b'recipe'))
        approval = approve(verified, isolation, digest(b'recipe'), digest(canonical(specification)))
        with self.assertRaisesRegex(DependencyError, 'outside-isolation'):
            approval.validate(verified, isolation.workspace.parent)


if __name__ == '__main__':
    unittest.main()

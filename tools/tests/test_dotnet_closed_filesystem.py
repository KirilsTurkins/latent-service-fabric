"""Closed filesystem derivation and exact final CoreLib reference-chain controls."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from tools.dotnet_guest import closed_filesystem as porting, http_errors, task_wait
from tools.rust_capsule_project import ROOT, digest, read_file, write_json
from tools.tests import test_dotnet_task_wait as task_controls


class ClosedFilesystemPortTests(unittest.TestCase):
    def setUp(self):
        self.fixture = task_controls.TaskWaitPortTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.receipt = json.loads(read_file(ROOT / 'sdk/dotnet-guest/tests/fixtures/closed-filesystem-rewrite.json'))

    def run_tool(self, stage, *arguments):
        self.assertEqual(stage, 'closed-filesystem-rewrite')
        self.assertEqual(arguments[2], '--closed-filesystem')
        original, base, assembly, receipt = arguments[-4:]
        self.assertEqual(original, self.fixture.original)
        assembly.write_bytes(base.read_bytes() + b'-closed-filesystem')
        result = copy.deepcopy(self.receipt)
        result.update(baseDigest=digest(base.read_bytes()), outputDigest=digest(assembly.read_bytes()),
            unchangedBaseMethods=44744 if base == original else 44753)
        write_json(receipt, result)

    def prepare(self, joined=False):
        f = self.fixture
        intermediate = f.prepare() if joined else None
        selected = porting.prepare(f.sdk, f.tools, f.packages, f.root / 'dotnet', f.project, f.output,
            f.evidence, self.run_tool, task_wait_port=intermediate)
        return selected, intermediate

    def references(self, selected, intermediate=None):
        f = self.fixture
        selected.references.write_bytes((str(selected.assembly) + '\n').encode())
        if intermediate is not None:
            intermediate.references.write_bytes((str(intermediate.assembly) + '\n').encode())
        (f.project / 'obj').mkdir()
        (f.project / 'obj/compiler.rsp').write_bytes(('-r:' + str(selected.assembly) + '\n').encode())

    def test_pure_closed_profile_has_no_runtime_authority_or_task_wait_requirement(self):
        selected, intermediate = self.prepare()
        self.assertIsNone(intermediate)
        self.references(selected)
        result = selected.finish(self.fixture.project, self.fixture.evidence)
        self.assertEqual(result['requiredDeclarations'], [])
        self.assertFalse(result['filesystemAuthority'])
        self.assertIsNone(result['taskWaitIntermediate'])
        self.assertEqual(result['base']['digest'], digest(b'original-control'))
        self.assertEqual(result['nativeAotReferenceBinding']['selectedCoreLibDigest'], selected.identity['digest'])

    def test_task_wait_intermediate_stays_immutable_and_final_ilc_reference_is_explicit(self):
        selected, intermediate = self.prepare(joined=True)
        self.references(selected, intermediate)
        before = intermediate.assembly.read_bytes()
        selected.finish(self.fixture.project, self.fixture.evidence)
        result = intermediate.finish(self.fixture.project, self.fixture.evidence, corelib_port=selected)
        self.assertEqual(intermediate.assembly.read_bytes(), before)
        self.assertEqual(result['derived'], intermediate.identity)
        self.assertEqual(result['nativeAotReferenceBinding']['finalCoreLibDerivation'], {
            'profile': porting.PROFILE, 'intermediateDigest': intermediate.identity['digest'],
            'selectedDigest': selected.identity['digest']})
        self.assertEqual(selected.evidence['taskWaitIntermediate'], intermediate.identity)

    def test_final_port_cannot_hide_changed_task_wait_intermediate(self):
        selected, intermediate = self.prepare(joined=True)
        self.references(selected, intermediate)
        intermediate.assembly.write_bytes(b'changed-after-composition')
        with self.assertRaisesRegex(ValueError, 'task-wait-derived-CoreLib-changed'):
            selected.finish(self.fixture.project, self.fixture.evidence)

    def test_original_or_intermediate_reference_is_rejected_after_final_derivation(self):
        selected, intermediate = self.prepare(joined=True)
        self.references(selected, intermediate)
        for path in (selected.original, selected.base):
            with self.subTest(path=path):
                (self.fixture.project / 'obj/compiler.rsp').write_bytes(('-r:' + str(path) + '\n').encode())
                with self.assertRaisesRegex(ValueError, 'native-aot-reference-drift'):
                    selected.finish(self.fixture.project, self.fixture.evidence)
                with self.assertRaisesRegex(ValueError, 'task-wait-native-aot-reference-drift'):
                    intermediate.finish(self.fixture.project, self.fixture.evidence, corelib_port=selected)

    def test_foreign_final_port_or_wrong_task_wait_chain_is_refused(self):
        selected, intermediate = self.prepare(joined=True)
        self.references(selected, intermediate)
        with self.assertRaisesRegex(ValueError, 'authenticated-final-corelib-required'):
            intermediate.finish(self.fixture.project, self.fixture.evidence, corelib_port=object())
        with self.assertRaisesRegex(ValueError, 'foreign-task-wait-chain'):
            selected.final_for(object())

    def test_original_tool_target_and_both_final_copies_are_rechecked(self):
        selected, _ = self.prepare()
        for path in (selected.original, selected.source / 'ClosedFilesystem.cs', selected.targets,
                     selected.assembly, selected.retained):
            before = path.read_bytes()
            try:
                path.write_bytes(before + b'changed')
                with self.subTest(path=path.name), self.assertRaises(ValueError):
                    selected.recheck()
            finally:
                path.write_bytes(before)
        selected.recheck()

    def test_receipt_accepts_only_exact_two_methods_counts_types_and_base(self):
        original = self.receipt
        porting.validate_receipt(original, task_wait.SOURCE, False)
        changes = {'modifiedOriginalMethods': True, 'unchangedBaseMethods': 44753,
            'otherBaseBodiesUnchanged': False, 'publicWrappersUnchanged': False,
            'newHostImports': True, 'filesystemAuthority': True, 'baseDigest': digest(b'foreign'),
            'originalMethodBodies': {**porting.METHODS, 'foreign': 'a'*64}, 'extra': False}
        for key, value in changes.items():
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'rewrite-receipt'):
                porting.validate_receipt({**original, key: value}, task_wait.SOURCE, False)

    def test_missing_or_duplicate_final_native_binding_cannot_issue_completed_receipt(self):
        selected, _ = self.prepare()
        self.references(selected)
        response = self.fixture.project / 'obj/compiler.rsp'
        body = response.read_bytes()
        response.write_bytes(b'-r:Other.dll\n')
        with self.assertRaisesRegex(ValueError, 'reference-not-observed'):
            selected.finish(self.fixture.project, self.fixture.evidence)
        response.write_bytes(body)
        (response.parent / 'duplicate.rsp').write_bytes(body)
        with self.assertRaisesRegex(ValueError, 'reference-not-observed'):
            selected.finish(self.fixture.project, self.fixture.evidence)

    def test_targets_depend_on_original_task_binding_and_refuse_foreign_corelib(self):
        source = read_file(ROOT / 'sdk/dotnet-guest/tools/http-errors/ClosedFilesystem.targets').decode()
        self.assertIn('DependsOnTargets="$(LsfClosedFilesystemDependencies)"', source)
        self.assertIn('AfterTargets="ComputeIlcCompileInputs;LsfBindActualTaskWait"', source)
        self.assertIn('Exclude="$(LsfClosedFilesystemBase)"', source)
        self.assertIn('Overwrite="false"', source)
        selected, intermediate = self.prepare(joined=True)
        project = read_file(self.fixture.project / 'Capsule.csproj').decode()
        self.assertIn('LsfBindActualTaskWait', project)
        self.assertIn(str(intermediate.assembly), project)
        self.assertIn(str(selected.assembly), project)

    def test_http_and_task_wait_bind_the_same_authenticated_final_corelib(self):
        from tools.tests import test_dotnet_http_errors as http_controls
        fixture = http_controls.HttpSyncReadPortTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        http = fixture.prepare()
        def run(stage, *arguments):
            original, base, assembly, receipt = arguments[-4:]
            assembly.write_bytes(base.read_bytes() + b'-closed-filesystem')
            result = {**self.receipt, 'cecilDigest': http_errors.CECIL_DIGEST,
                'baseDigest': digest(base.read_bytes()), 'outputDigest': digest(assembly.read_bytes()),
                'unchangedBaseMethods': 44753}
            write_json(receipt, result)
        selected = porting.prepare(fixture.http.sdk, fixture.http.tools, fixture.core.packages,
            fixture.http.root / 'dotnet', fixture.http.project, fixture.http.output, fixture.http.evidence,
            run, task_wait_port=fixture.core_port)
        response = fixture.references(http)
        values = [str(http.assembly), str(selected.assembly)]
        response.write_bytes(('\n'.join('-r:' + value for value in values) + '\n').encode())
        selected.references.write_bytes(('\n'.join(values) + '\n').encode())
        filesystem = selected.finish(fixture.http.project, fixture.http.evidence)
        http_result = http.finish(fixture.http.project, fixture.http.evidence, corelib_port=selected)
        task = fixture.core_port.finish(fixture.http.project, fixture.http.evidence, corelib_port=selected)
        for result in (filesystem, http_result, task):
            self.assertEqual(result['nativeAotReferenceBinding']['responseFiles'][0]['digest'], digest(response.read_bytes()))
        self.assertEqual(task['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest'], selected.identity['digest'])
        selected.assembly.write_bytes(b'changed-final-corelib')
        with self.assertRaisesRegex(ValueError, 'derived-corelib-changed'):
            http.finish(fixture.http.project, fixture.http.evidence, corelib_port=selected)


if __name__ == '__main__':
    unittest.main()

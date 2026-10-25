"""Normal selection/receipt fences; actual NativeAOT execution is a separate gate."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.dotnet_guest import aggregate_task_wait, closed_filesystem, runtime, task_wait
from tools.rust_capsule_project import ROOT, digest, write_json
from tools.tests import test_dotnet_task_wait as controls

FIXTURE = ROOT / 'sdk/dotnet-guest/tests/fixtures/aggregate-task-wait-rewrite.json'
DECLARATIONS = [runtime.CLOCK, runtime.ACTIVATION, runtime.WALL, runtime.RANDOM]


class AggregateTaskWaitPortTests(unittest.TestCase):
    def receipt(self):
        return json.loads(FIXTURE.read_bytes())

    def test_authenticated_receipt_refuses_every_missing_or_cross_typed_aggregate_identity(self):
        original = self.receipt()
        task_wait.validate_receipt(original, finite=True, managed=True, aggregate=True)
        before = copy.deepcopy(original)
        changes = []
        for key in original['aggregateTaskWait']:
            value = copy.deepcopy(original)
            del value['aggregateTaskWait'][key]
            changes.append(value)
        for key in ('originalMethods', 'originalRemainders', 'rewrittenBodies'):
            value = copy.deepcopy(original)
            target = value['aggregateTaskWait'][key]
            if type(target) is list:
                target[0]['token'] = True
            else:
                target[next(iter(target))] = '0' * 64
            changes.append(value)
        for key, replacement in (('generatedHelperCount', True), ('unchangedOriginalMethods', 44719),
                                 ('outputDigest', 'not-a-digest')):
            changes.append({**original, key: replacement})
        value = copy.deepcopy(original)
        value['managedAcceptedWork']['modifiedOriginalMethods'].popitem()
        changes.append(value)
        for value in changes:
            with self.subTest(value=value), self.assertRaises(ValueError):
                task_wait.validate_receipt(value, finite=True, managed=True, aggregate=True)
        self.assertEqual(original, before)

    def test_legacy_receipts_and_authority_selections_cannot_impersonate_aggregate(self):
        original = self.receipt()
        legacy = copy.deepcopy(original)
        del legacy['aggregateTaskWait']
        legacy.update(generatedHelperCount=91, unchangedOriginalMethods=44719)
        task_wait.validate_receipt(legacy, finite=True, managed=True)
        for value, flags in ((legacy, (True, True, True)), (original, (True, True, False)),
                             (original, (True, False, True)), (original, (False, True, True)),
                             (original, (True, True, 1))):
            with self.subTest(flags=flags), self.assertRaises(ValueError):
                task_wait.validate_receipt(value, finite=flags[0], managed=flags[1], aggregate=flags[2])
        self.assertFalse(task_wait.selected(DECLARATIONS, None))
        self.assertFalse(task_wait.selected(DECLARATIONS[1:], {'profile': 'unused'}))

    def test_normal_managed_selection_preserves_exact_final_corelib_chain_and_rejects_drift(self):
        control = controls.TaskWaitPortTests()
        control.setUp()
        self.addCleanup(control.doCleanups)
        control.declared = DECLARATIONS
        def rewrite(stage, *arguments):
            self.assertEqual(stage, 'task-wait-rewrite')
            self.assertEqual(arguments[2], '--aggregate-task-wait')
            arguments[-2].write_bytes(b'aggregate-control')
            write_json(arguments[-1], {**self.receipt(), 'outputDigest': digest(b'aggregate-control')})
        control.run_tool = rewrite
        intermediate = control.prepare(managed=True)
        self.assertEqual(intermediate.validated_helper_count(), 95)
        def filesystem(stage, *arguments):
            self.assertEqual(stage, 'closed-filesystem-rewrite')
            original, base, assembly, receipt = arguments[-4:]
            self.assertEqual(original, control.original)
            self.assertEqual(base, intermediate.assembly)
            assembly.write_bytes(b'final-filesystem-control')
            value = json.loads((ROOT / 'sdk/dotnet-guest/tests/fixtures/closed-filesystem-rewrite.json').read_bytes())
            value.update(baseDigest=intermediate.identity['digest'], outputDigest=digest(assembly.read_bytes()),
                         unchangedBaseMethods=44839)
            write_json(receipt, value)
        final = closed_filesystem.prepare(control.sdk, control.tools, control.packages, control.root/'dotnet',
            control.project, control.output, control.evidence, filesystem, task_wait_port=intermediate)
        intermediate.references.write_text(str(intermediate.assembly)+'\n')
        final.references.write_text(str(final.assembly)+'\n')
        (control.project/'obj').mkdir()
        response = control.project/'obj/compiler.rsp'
        response.write_text('-r:'+str(final.assembly)+'\n')
        final.finish(control.project, control.evidence)
        result = intermediate.finish(control.project, control.evidence, corelib_port=final)
        self.assertEqual(result['selection']['requiredDeclarations'], sorted(DECLARATIONS))
        self.assertEqual(result['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest'], final.identity['digest'])
        self.assertEqual(result['aggregateTaskWait'], aggregate_task_wait.EXPECTED)
        self.assertEqual(intermediate.assembly.read_bytes(), b'aggregate-control')
        response.write_text('-r:'+str(intermediate.assembly)+'\n')
        with self.assertRaisesRegex(ValueError, 'native-aot-reference-drift'):
            intermediate.finish(control.project, control.evidence, corelib_port=final)

    def test_both_node_modes_keep_the_actual_fresh_directory_owner_callable(self):
        from tools import dotnet_finite_wait_node as node
        class BeforeNative(Exception):
            pass
        for aggregate in (False, True):
            with self.subTest(aggregate=aggregate), patch.object(node, 'fresh', side_effect=BeforeNative) as fresh:
                with self.assertRaises(BeforeNative):
                    node.run(Path('unused-component'), {}, Path('owned-output'), aggregate=aggregate)
                fresh.assert_called_once_with(Path('owned-output'))

    def test_rehashed_build_cannot_hide_changed_aggregate_selection_or_final_helper_chain(self):
        from tools import qualify_dotnet_finite_waits as qualification
        from tools.phase2_operator_process import WorkflowError
        from tools.tests.test_dotnet_finite_wait_programme import FiniteWaitProgramme
        old = FiniteWaitProgramme()
        self.addCleanup(old.doCleanups)
        with tempfile.TemporaryDirectory() as temporary, patch.object(qualification, 'package_identity', return_value={}):
            root = Path(temporary)
            docs, refresh = old.build(root)
            before = docs['task-wait-port.json']
            extra = {'profile', 'frameworkInput', 'tool', 'derived', 'sourceCaptureDigest', 'targetsDigest',
                'nativeAotReferenceBinding', 'selection'}
            docs['task-wait-port.json'] = {**self.receipt(), **{key: before[key] for key in extra},
                'outputDigest': before['outputDigest']}
            docs['closed-filesystem-port.json']['unchangedBaseMethods'] = 44839
            docs['runtime-profile.json']['profile'] = 'runtime-managed'
            selection = docs['compiler-patches.json']['patches'][0]['selection']
            selection.update(generatedHelperCount=95, aggregateTaskWait=self.receipt()['aggregateTaskWait'])
            def publish(selected):
                for name, value in selected.items():
                    (root/name).write_bytes((json.dumps(value)+'\n').encode('utf-8'))
                refresh()
            publish(docs)
            qualification.build_evidence(root, aggregate=True)
            for kind in ('preimage', 'selection', 'final-helper-count', 'wrong-runtime-profile'):
                selected = copy.deepcopy(docs)
                if kind == 'preimage':
                    selected['task-wait-port.json']['aggregateTaskWait']['originalMethods'][0]['ilSha256'] = 'sha256:'+'0'*64
                elif kind == 'selection':
                    selected['compiler-patches.json']['patches'][0]['selection']['aggregateTaskWait']['productionSelected'] = True
                elif kind == 'final-helper-count':
                    selected['closed-filesystem-port.json']['unchangedBaseMethods'] = 44835
                else:
                    selected['runtime-profile.json']['profile'] = 'runtime'
                publish(selected)
                with self.subTest(kind=kind), self.assertRaises((ValueError, WorkflowError)):
                    qualification.build_evidence(root, aggregate=True)

    def test_public_evidence_gate_excludes_private_workspaces_and_reserves_admission_bytes(self):
        from tools import qualify_dotnet_aggregate_waits as owner
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            public = root/'programme/FAILED.json'
            public.parent.mkdir()
            public.write_bytes(b'{}\n')
            private = root/'programme/project/private-token.json'
            private.parent.mkdir()
            private.write_bytes(b'private-sentinel-not-public')
            result = owner.admit_evidence(root)
            self.assertEqual(set(result['files']), {'programme/FAILED.json'})
            self.assertEqual(result['payloadBytes'], 3)
            self.assertNotIn(b'private-sentinel', (root/'evidence-admission.json').read_bytes())
            with patch.object(owner, 'MAX_PUBLIC', owner.MAX_DOCUMENT+2):
                with self.assertRaisesRegex(ValueError, 'evidence-total'):
                    owner.admit_evidence(root)
            self.assertEqual(json.loads((root/'evidence-admission.json').read_bytes())['status'], 'failed')
            workflow = (ROOT/'.github/workflows/dotnet-aggregate-task-waits.yml').read_text()
            self.assertEqual({line.strip().split('/dotnet-aggregate/', 1)[1]
                for line in workflow.splitlines() if line.strip().startswith('${{ runner.temp }}/dotnet-aggregate/')},
                {*owner.PUBLIC_PATTERNS, 'evidence-admission.json'})


if __name__ == '__main__':
    unittest.main()

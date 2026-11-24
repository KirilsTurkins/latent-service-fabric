"""Controller boundary controls; actual JDK/compiler/component execution is separate."""
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools import java_dependency_checkpoint_fixture as fixture, java_dependency_checkpoint_node as node
from tools import qualify_java_dependency_checkpoints as programme
from tools.dev_workflow.common import DevError
from tools.java_capsule_build import write_completion
from tools.qualify_java_dependency_checkpoints import build_evidence
from tools.phase3_resource_identity import file_identity
from tools.rust_capsule_project import digest, write_json
from tools.phase2_operator_process import WorkflowError


class JavaDependencyCheckpointTests(unittest.TestCase):
    def test_large_compiler_classpaths_keep_full_records_and_fit_the_native_signer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            row = {'stage': 'model', 'command': ['java', '-cp', 'a' * 70000], 'exitCode': 0, 'seconds': 1.5}
            marker = {'commands': [row, {'stage': 'package', 'exitCode': 0}]}
            logs = root / 'compiler-logs'
            logs.mkdir()
            original = logs / '0-model.command.json'
            write_json(original, row)
            with self.assertRaisesRegex(ValueError, 'retained command differs'):
                write_completion(root, {'commands': [{**row, 'exitCode': 1}]})
            self.assertFalse((root / 'BUILD-COMPLETE.json').exists())
            write_completion(root, marker)
            completed = (root / 'BUILD-COMPLETE.json').read_bytes()
            self.assertLessEqual(len(completed), 65536)
            first, second = json.loads(completed)['commands']
            reference = first.pop('commandRecord')
            raw = (root / reference['path']).read_bytes()
            self.assertEqual((digest(raw), len(raw)), (reference['digest'], reference['size']))
            self.assertEqual(json.loads(raw), row)
            self.assertEqual(first, {key: value for key, value in row.items() if key != 'command'})
            self.assertEqual(second, marker['commands'][1])

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            small = {'commands': [{'stage': 'version', 'command': ['java', '-version'], 'exitCode': 0}]}
            write_completion(root, small)
            self.assertEqual(json.loads((root / 'BUILD-COMPLETE.json').read_bytes()), small)

    def test_current_native_products_are_rechecked_and_a_missing_archive_cannot_select_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            for name in programme.PRODUCTS:
                (directory / name).write_bytes(name.encode())
            receipt = directory / 'native-tuple.json'
            write_json(receipt, {
                'status': 'passed', 'features': [], 'tupleRole': 'ordinary-defaults',
                'hostAbiProfile': 'lsf-host-abi-phase3-v5', 'wasmtimeVersion': '48.0.9',
                'head': '1' * 40, 'tree': '2' * 40,
                'binaries': {name: file_identity(directory / name) for name in programme.PRODUCTS},
            })
            commands = SimpleNamespace(environment={})
            with patch.object(programme, 'build_default_products', return_value=(directory, receipt)) as build:
                binaries, origin, verify = programme.select_native(None, commands, directory)
                self.assertEqual(verify(), origin)
                binaries['latent'].write_bytes(b'changed')
                with self.assertRaisesRegex(DevError, 'native-product-mismatch'):
                    verify()
                missing = SimpleNamespace(verify_prepared=Mock(side_effect=FileNotFoundError), native_products=Mock())
                with patch.dict(sys.modules, {'tools.rust_thread_native_products': missing}), \
                        self.assertRaises(FileNotFoundError):
                    programme.select_native(directory, commands, directory)
                missing.native_products.assert_not_called()
                build.assert_called_once()

    def test_original_project_has_only_explicit_runtime_clocks_and_unchanged_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            app=fixture.project(Path(temporary)/'application')
            import json
            descriptor=json.loads((app/'capsule-project.json').read_text())
            self.assertEqual(descriptor['limits']['memoryBytes'],67108864)
            self.assertEqual(descriptor['limits']['cpuFuel'],1000000000)
            world=(app/'wit/world.wit').read_text()
            self.assertIn('greet: async func(',world)
            self.assertIn('import '+fixture.ACTIVATION+';',world)
            self.assertNotIn('http',world)
            self.assertEqual((app/'src/dev/latent/app/Capsule.java').read_bytes(),
                (fixture.ROOT/fixture.SOURCE).read_bytes())

    def test_configuration_refuses_missing_optional_duplicate_and_network_imports(self):
        capsule={'imports':[{'contract':name,'optional':False} for name in (*fixture.CLOCKS,fixture.ACTIVATION)]}
        for changed in (capsule['imports'][:-1],capsule['imports']+[capsule['imports'][0]],
                [*capsule['imports'][:-1],{'contract':'latent:http/client@0.2.0','optional':False}],
                [*capsule['imports'][:-1],{'contract':fixture.ACTIVATION,'optional':True}]):
            with self.subTest(changed=changed),self.assertRaises(WorkflowError):
                node.configuration({}, {'imports':changed})

    @staticmethod
    def row():
        revision={'releaseDigest':'sha256:'+'a'*64}
        return revision,{'processReaped':True,'exitCode':0,
            'decoded':[{'ok':fixture.EXPECTED['dependency']}],
            'response':{'outcomeKnown':True,'data':{'resolvedRevision':revision,'consumption':{
                'cpuFuel':17,'peakMemoryBytes':65536,**{name:0 for name in ('childCalls','outboundRequests',
                    'logBytes','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')}}}}}

    def test_signed_case_requires_exact_result_identity_known_outcome_and_physical_reap(self):
        revision,row=self.row()
        def invoke(value):
            with patch.object(node,'selected_revision',return_value=revision),patch.object(node,'call',return_value=value):
                return node.invoke(None,None,'dependency','case',revision['releaseDigest'])
        self.assertEqual(invoke(row),row)
        for key in ('processReaped',):
            bad=copy.deepcopy(row);bad[key]=False
            with self.assertRaises(WorkflowError):invoke(bad)
        bad=copy.deepcopy(row);bad['decoded']=[{'ok':'fake-completed-task'}]
        with self.assertRaises(WorkflowError):invoke(bad)
        bad=copy.deepcopy(row);bad['decoded']=[{'err':'checkpoint-failure|root=8|error=monitor-state|child=7|child-error=none'}]
        with self.assertRaises(WorkflowError):invoke(bad)
        bad=copy.deepcopy(row);bad['response']['outcomeKnown']=False
        with self.assertRaises(WorkflowError):invoke(bad)
        bad=copy.deepcopy(row);bad['response']['data']['resolvedRevision']={'releaseDigest':'foreign'}
        with self.assertRaises(WorkflowError):invoke(bad)

    def test_original_memory_fuel_and_no_effect_boundaries_remain_required(self):
        revision,row=self.row()
        for key,value in (('cpuFuel',1000000001),('peakMemoryBytes',67108865),('outboundRequests',1),('logBytes',1)):
            bad=copy.deepcopy(row);bad['response']['data']['consumption'][key]=value
            with self.subTest(key=key),patch.object(node,'selected_revision',return_value=revision),\
                    patch.object(node,'call',return_value=bad),self.assertRaises(WorkflowError):
                node.invoke(None,None,'dependency','case',revision['releaseDigest'])

    def test_missing_build_proof_cannot_become_runtime_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory=Path(temporary)
            write_json(directory/'BUILD-COMPLETE.json',{'packageAssembled':True})
            with self.assertRaises((ValueError,FileNotFoundError,WorkflowError)):
                build_evidence(directory)

        # Synthetic files exercise custody/refusal only; they are never actual
        # generated C or compiler/runtime qualification evidence.
        from types import SimpleNamespace
        from tools.java_guest import c_failure_context as context
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary).resolve();source=root/'compiled';output=root/'evidence';output.mkdir()
            java=source/'project/src/main/java/dev/latent/app/Capsule.java'
            java.parent.mkdir(parents=True);java.write_bytes((fixture.ROOT/fixture.SOURCE).read_bytes())
            generated=source/'project/build/teavm-c/c'
            for name in context.CHECKPOINT_SOURCES:
                path=generated/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'/* fixed mechanism */\n')
            compiler=SimpleNamespace(records=[{'stage':'c-to-wasm','exitCode':0}])
            context.retain_component_inputs(compiler,source,output,context.CHECKPOINT_SOURCES)
            import json
            record=json.loads((output/'checkpoint-generated.json').read_bytes())
            self.assertFalse(record['qualification'])
            self.assertEqual(set(record['files']),set(context.CHECKPOINT_SOURCES))
            for name in context.CHECKPOINT_SOURCES:
                self.assertEqual((output/'checkpoint-generated'/name).read_bytes(),(generated/name).read_bytes())
            for refusal in ('source','file-bound','aggregate-bound'):
                refused=root/refusal;refused.mkdir()
                if refusal=='source':java.write_bytes(b'foreign Java source')
                else:
                    java.write_bytes((fixture.ROOT/fixture.SOURCE).read_bytes())
                    size=context.CHECKPOINT_MAX_FILE+(1 if refusal=='file-bound' else 0)
                    for name in context.CHECKPOINT_SOURCES:
                        (generated/name).write_bytes(b'x'*size)
                context.retain_component_inputs(compiler,source,refused,context.CHECKPOINT_SOURCES)
                self.assertTrue((refused/'checkpoint-generated-refused.json').is_file())
                self.assertFalse((refused/'checkpoint-generated').exists())


if __name__=='__main__':unittest.main()

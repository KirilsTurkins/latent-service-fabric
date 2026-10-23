"""Controller boundary controls; actual JDK/compiler/component execution is separate."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import java_checkpoint_gc_fixture as fixture, java_checkpoint_gc_node as node
from tools.qualify_java_checkpoint_gc import build_evidence, generated_mechanism
from tools.rust_capsule_project import write_json
from tools.phase2_operator_process import WorkflowError


class JavaCheckpointGcTests(unittest.TestCase):
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
            'decoded':[{'ok':fixture.EXPECTED['gc']}],
            'response':{'outcomeKnown':True,'data':{'resolvedRevision':revision,'consumption':{
                'cpuFuel':17,'peakMemoryBytes':65536,**{name:0 for name in ('childCalls','outboundRequests',
                    'logBytes','effectCount','stateReadBytes','stateWriteBytes','blobReadBytes','blobWriteBytes')}}}}}

    def test_signed_case_requires_exact_result_identity_known_outcome_and_physical_reap(self):
        revision,row=self.row()
        def invoke(value):
            with patch.object(node,'selected_revision',return_value=revision),patch.object(node,'call',return_value=value):
                return node.invoke(None,None,'gc','case',revision['releaseDigest'])
        self.assertEqual(invoke(row),row)
        for key in ('processReaped',):
            bad=copy.deepcopy(row);bad[key]=False
            with self.assertRaises(WorkflowError):invoke(bad)
        bad=copy.deepcopy(row);bad['decoded']=[{'ok':'fake-completed-task'}]
        with self.assertRaises(WorkflowError):invoke(bad)
        bad=copy.deepcopy(row);bad['decoded']=[{'err':'checkpoint-gc-failure|root=3|child=2|child-failed=false'}]
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
                node.invoke(None,None,'gc','case',revision['releaseDigest'])

    def test_gc_case_does_not_accept_fresh_or_one_collection_or_ignored_error(self):
        revision,row=self.row()
        for payload in ({'ok':fixture.EXPECTED['fresh']},
                {'ok':fixture.EXPECTED['gc'].replace('collections=root:child','collections=root')},
                {'err':'checkpoint-gc-failure|root=3|child=2|child-failed=false'}):
            bad=copy.deepcopy(row);bad['decoded']=[payload]
            with self.subTest(payload=payload),patch.object(node,'selected_revision',return_value=revision),\
                    patch.object(node,'call',return_value=bad),self.assertRaises(WorkflowError):
                node.invoke(None,None,'gc','case',revision['releaseDigest'])

    def test_generated_mechanism_refuses_missing_collector_getter_or_child_resume(self):
        # Synthetic text exercises the controller gate only, never GC evidence.
        bodies={
            'c/o/t/r/GC.c':'void meth_otr_GC_collectGarbageImpl() {\n'
                'meth_otr_GC_mark(); reference->object = NULL; meth_otr_GC_sweep();\n}\n'
                'void meth_otr_GC_mark() {\n}\nvoid meth_otr_GC_sweep() {\n}\n',
            'c/j/l/r/WeakReference.c':'teavm_reference_init(); teavm_reference_get();',
            'c/j/l/System.c':'void meth_jl_System_gc() {\nmeth_otr_GC_collectGarbageImpl();\n}\n',
            'c/d/l/a/Capsule.c':'void meth_dla_Capsule_checked() {\n'
                'WeakReference_get(); meth_jl_System_gc(); '
                'meth_otr_Fiber_isSuspending(); meth_otr_Fiber_push(); meth_otr_Fiber_pop();\n}\n',
            'c/d/l/a/Capsule@d1.c':'void meth_dla_Capsule_1_initialize() {\n'
                'WeakReference_get(); meth_jl_System_gc(); '
                'meth_otr_Fiber_isSuspending(); meth_otr_Fiber_push(); meth_otr_Fiber_pop();\n}\n'}
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            for name,body in bodies.items():
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(body)
            self.assertFalse(generated_mechanism(root)['runtimeCollectionObserved'])
            for name,needle in (('c/o/t/r/GC.c','meth_otr_GC_mark();'),
                    ('c/j/l/r/WeakReference.c','teavm_reference_get()'),
                    ('c/j/l/System.c','meth_otr_GC_collectGarbageImpl();'),
                    ('c/d/l/a/Capsule@d1.c','meth_otr_Fiber_pop()'),
                    ('c/o/t/r/GC.c','reference->object = NULL;')):
                (root/name).write_text(bodies[name].replace(needle,'omitted'))
                with self.subTest(name=name),self.assertRaises(WorkflowError):generated_mechanism(root)
                (root/name).write_text(bodies[name])

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
            for name in context.GC_ROOT_SOURCES:
                path=generated/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'/* fixed mechanism */\n')
            compiler=SimpleNamespace(records=[{'stage':'c-to-wasm','exitCode':0}])
            context.retain_component_inputs(compiler,source,output,context.GC_ROOT_SOURCES)
            import json
            record=json.loads((output/'gc-root-generated.json').read_bytes())
            self.assertFalse(record['qualification'])
            self.assertEqual(set(record['files']),set(context.GC_ROOT_SOURCES))
            self.assertEqual(len(record['files']),24)
            self.assertEqual(record['fixtureDigest'],context.GC_ROOT_JAVA)
            for name in context.GC_ROOT_SOURCES:
                self.assertEqual((output/'gc-root-generated'/name).read_bytes(),(generated/name).read_bytes())
            for refusal in ('source','file-bound','aggregate-bound','anonymous-missing','before-clang'):
                refused=root/refusal;refused.mkdir()
                if refusal=='source':java.write_bytes(b'foreign Java source')
                elif refusal in ('file-bound','aggregate-bound'):
                    java.write_bytes((fixture.ROOT/fixture.SOURCE).read_bytes())
                    size=context.CHECKPOINT_MAX_FILE+(1 if refusal=='file-bound' else 0)
                    for name in context.GC_ROOT_SOURCES:
                        (generated/name).write_bytes(b'x'*size)
                else:
                    java.write_bytes((fixture.ROOT/fixture.SOURCE).read_bytes())
                    for name in context.GC_ROOT_SOURCES:(generated/name).write_bytes(b'/* fixed mechanism */\n')
                    if refusal=='anonymous-missing':(generated/'c/d/l/a/Capsule@d1.c').unlink()
                    else:compiler.records=[]
                context.retain_component_inputs(compiler,source,refused,context.GC_ROOT_SOURCES)
                self.assertTrue((refused/'gc-root-generated-refused.json').is_file())
                self.assertFalse((refused/'gc-root-generated').exists())


if __name__=='__main__':unittest.main()

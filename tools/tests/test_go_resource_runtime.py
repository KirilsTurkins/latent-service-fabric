"""Keep Go's exact typed/profile boundary in the shared resource controller."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import resource_runtime_node as runtime, go_resource_runtime_fixture as fixture
from tools import guest_runtime_receipts
from tools.dev_workflow.common import DevError, encode
from tools.go_node_stop_probe import OWNER_LIMITS
from tools.go_resource_runtime_build import build_evidence
from tools.phase2_operator_process import WorkflowError
from tools.qualify_typescript_resource_runtime import checked_release
from tools.rust_capsule_node import configure
from tools.rust_capsule_project import digest, inventory


class GoResourceRuntime(unittest.TestCase):
    @staticmethod
    def capsule():
        return {'execution':{'limits':{'memoryBytes':67108864}},
                'imports':[{'contract':name,'optional':False} for name in
                    (*runtime.SCALARS,'latent:random/random@0.1.0',runtime.ACTIVATION)]}

    def test_go_keeps_original_owner_limits_scalar_imports_and_separate_activation_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);node=root/'node';node.mkdir();signed=root/'signed';signed.mkdir()
            (signed/'policy.json').write_bytes(b'{}\n')
            _path,settings=configure(node,signed,12345,language='go');before=copy.deepcopy(settings)
            runtime.configure(settings,self.capsule(),language='go')
            self.assertEqual(settings['workers'],before['workers']);self.assertEqual(settings['cells'],before['cells'])
            self.assertEqual(settings['providers']['activationRuntime']['limits'],OWNER_LIMITS)
            self.assertEqual(OWNER_LIMITS,{'tasks':16,'executors':2,'queuedWork':2,'waits':4,
                                         'timers':2,'results':2,'nativeOwners':2})
            self.assertEqual(settings['providers']['activationRuntime']['identity']['service'],'activation-host')
            self.assertEqual(settings['providers']['clockWall']['identity']['service'],'runtime-host')
            self.assertEqual(len(settings['providers']['bindings']),11)
            self.assertEqual(len(settings['providers']['scalarAliases']),5)
            selected,scalars,limits,template,function,prefix=runtime.selection('go')
            self.assertIs(selected,fixture);self.assertEqual(limits,OWNER_LIMITS)
            self.assertEqual(set(scalars),set(runtime.SCALARS)|{'latent:random/random@0.1.0'})
            self.assertEqual((template,function,prefix),('greeting','greet','resource-runtime:'))

    def test_callback_facilities_are_ordinary_and_random_bytes_are_not_logged_or_returned(self):
        source=fixture.LIBRARY_SOURCE
        self.assertIn(b'"crypto/rand"',source)
        self.assertIn(b'n, err := rand.Read(entropy[:]); n != 8 || err != nil',source)
        self.assertIn(b'time.Now().UnixMilli() <= 1<<32',source)
        self.assertIn(b'logged("resource-go:callback:"+label+":entropy=8:wall64=1")',source)
        self.assertNotIn(b'hex.EncodeToString(entropy',source)
        self.assertNotIn(b'logged(string(entropy',source)
        self.assertIn('|entropy=16|wall64=1|fresh=1',fixture.EXPECTED['parallel'])

    def test_missing_random_optional_import_or_foreign_language_fails_before_configuration(self):
        for change in ('missing-random','optional','duplicate','language'):
            capsule=self.capsule();settings={}
            if change=='missing-random':capsule['imports'].pop(-2)
            elif change=='optional':capsule['imports'][-1]['optional']=True
            elif change=='duplicate':capsule['imports'][-2]=capsule['imports'][0]
            with self.subTest(change=change),self.assertRaises(WorkflowError):
                runtime.configure(settings,capsule,language='rust' if change=='language' else 'go')
            self.assertEqual(settings,{})

    def test_go_original_world_result_namespace_and_component_are_not_ts_projection(self):
        component='sha256:'+'a'*64;world='examples:greeting/service@1.0.0'
        release={'name':'my-greeting','service':'my-greeting','world':world,'componentDigest':component}
        capsule={'metadata':{'name':'examples/my-greeting','tenant':'examples'},
            'component':{'world':world,'digest':component},'exports':['examples:greeting/api@1.0.0']}
        self.assertEqual(checked_release(release,capsule,{'component':{'sha256':component}},language='go'),release)
        for language in ('typescript','rust'):
            with self.subTest(language=language),self.assertRaises(WorkflowError):
                checked_release(release,capsule,{'component':{'sha256':component}},language=language)

    @staticmethod
    def build(root):
        files={'vendor/lsf/sdk/go-guest/runtime-source':b'controlled source',
            'wit/world.wit':b'package controlled:app;',
            'latent.dependencies.lock.json':encode({'selection':{'runtimeProfile':fixture.PROFILE},'artifacts':[]})}
        source=inventory(files);component=b'controlled test component, not executable qualification'
        for name,raw in {'component.wasm':component,'source-inputs.json':source,'recipe-inputs.json':b'[]',
                'capsule.json':b'{}','go-runtime-transformations.json':b'[]','application-dependencies.json':b'{}',
                'compiler-containment.json':b'{}','go-module-build-inputs.json':b'{}'}.items():(root/name).write_bytes(raw)
        (root/'package-source.json').write_bytes(encode({'layers':[{'source':'capsule.json'}]}))
        package=inventory({name:(root/name).read_bytes() for name in ('package-source.json','capsule.json')})
        (root/'package-inputs.json').write_bytes(package)
        material_names={'build-recipe':'recipe-inputs.json','package-inputs':'package-inputs.json',
            'go-runtime-transformations':'go-runtime-transformations.json','application-dependencies':'application-dependencies.json',
            'compiler-containment':'compiler-containment.json','go-module-build-inputs':'go-module-build-inputs.json'}
        materials=[{'name':name,'digest':digest((root/path).read_bytes()),'size':len((root/path).read_bytes())}
                   for name,path in material_names.items()]
        selected=guest_runtime_receipts.emit(root,'go',fixture.PROFILE,files,source,component,materials,
            graph=json.loads(files['latent.dependencies.lock.json']),binding_digest=digest(b'controlled binding'),configuration={})
        observation={'componentDigest':digest(component),'componentSize':len(component),'materials':materials+[selected],
            'parameters':{'goPackage':'my-greeting','compiler':'componentize-go','target':'wasm32-wasip1',
                          'runtime':fixture.PROFILE,'locked':True,'ambientWasi':False}}
        (root/'build-observation.json').write_bytes(encode(observation))
        complete={'packageAssembled':True,'componentDigest':digest(component),'sourceDigest':digest(source),
                  'observationDigest':digest((root/'build-observation.json').read_bytes())}
        (root/'BUILD-COMPLETE.json').write_bytes(encode(complete))
        return complete,observation

    def test_fresh_go_build_requires_v5_current_material_bindings_and_original_package_inventory(self):
        for change in ('none','component','runtime','material','package'):
            with tempfile.TemporaryDirectory() as temporary,self.subTest(change=change):
                root=Path(temporary);complete,observation=self.build(root)
                if change=='component':(root/'component.wasm').write_bytes(b'foreign component')
                elif change=='runtime':observation['parameters']['runtime']='go-component-async-v1'
                elif change=='material':observation['materials'][0]['digest']='sha256:'+'b'*64
                elif change=='package':(root/'capsule.json').write_bytes(b'{"changed":true}')
                if change in ('runtime','material'):
                    (root/'build-observation.json').write_bytes(encode(observation))
                    complete['observationDigest']=digest((root/'build-observation.json').read_bytes())
                    (root/'BUILD-COMPLETE.json').write_bytes(encode(complete))
                if change=='none':self.assertEqual(build_evidence(root)['component']['sha256'],complete['componentDigest'])
                else:
                    with self.assertRaises((WorkflowError,DevError)):build_evidence(root)


if __name__=='__main__':unittest.main()

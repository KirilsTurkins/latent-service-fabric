"""Finite Java resource/facility authority uses the existing fiber-I/O bounds."""
import copy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch

from tools import java_resource_runtime_node as runtime
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_node import configure
from tools.rust_capsule_project import read_json


class JavaJoinedRuntime(unittest.TestCase):
    @staticmethod
    def capsule():
        return {'execution':{'limits':{'memoryBytes':67108864}},'imports':[
            {'contract':name,'optional':False} for name in runtime.fixture.CAPABILITIES]}

    def test_original_fiber_io_capacity_two_tenant_aliases_and_no_implicit_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);(root/'node').mkdir();(root/'signed').mkdir()
            (root/'signed/policy.json').write_bytes(b'{}\n')
            _path,settings=configure(root/'node',root/'signed',12345,language='java')
            before=copy.deepcopy(settings);runtime.configure(settings,self.capsule())
            self.assertEqual(settings['workers'],before['workers'])
            self.assertEqual(settings['cells'],before['cells'])
            self.assertEqual(settings['providers']['http'],before['providers']['http'])
            self.assertTrue(settings['engine']['javaGuest'])
            self.assertEqual(settings['providers']['activationRuntime']['limits'],
                {'tasks':8,'executors':2,'queuedWork':8,'waits':16,'timers':8,'results':8,'nativeOwners':8})
            self.assertEqual(len(settings['providers']['bindings']),11)
            self.assertEqual(len(settings['providers']['scalarAliases']),5)
            self.assertEqual(settings['providers']['scalarAliases'][-1]['identity']['tenant'],'foreign')
            self.assertNotIn('grants',settings['providers']['activationRuntime'])

    def test_missing_optional_duplicate_or_foreign_imports_refuse_before_configuration(self):
        for kind in ('missing','optional','duplicate','foreign'):
            capsule=self.capsule()
            if kind=='missing':capsule['imports'].pop()
            elif kind=='optional':capsule['imports'][0]['optional']=True
            elif kind=='duplicate':capsule['imports'][-1]=copy.deepcopy(capsule['imports'][0])
            else:capsule['imports'][0]['contract']='foreign:runtime/entry@1.0.0'
            with self.subTest(kind=kind),self.assertRaisesRegex(WorkflowError,'exact-imports'):
                runtime.configure({},capsule)

    def test_java_secure_random_grants_only_bytes_and_retains_original_scalar_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            client=SimpleNamespace(directory=Path(temporary),call=Mock())
            node=SimpleNamespace(startup_record={'providers':[{'id':'random','tenant':'examples',
                'service':'runtime-host','capability':runtime.RANDOM,'profile':'system-random-v1',
                'configurationEpoch':'1','configurationDigest':'sha256:'+'a'*64}]})
            target={'service':'my-greeting','generation':'3','grants':[{'capability':runtime.CLOCK,'policy':'clock-owned'}]}
            with patch.object(runtime,'deploy',return_value=target) as deployment:
                runtime._grant(client,node,None,'publication-owned',target,'examples',
                    capability=runtime.RANDOM,name='random',profile='system-random-v1',kind='random',
                    operations=('bytes',),service='runtime-host')
            binding=read_json(client.directory/'random-examples-installed.json')
            policy=read_json(client.directory/'resource-random-examples.json')['rules'][0]
            self.assertEqual(binding['restriction']['operations'],['bytes'])
            self.assertEqual(policy['operations'],['bytes'])
            self.assertEqual(policy['ceiling'],{'operations':4096,'inputBytes':8,'outputBytes':32768,'wallTimeMillis':5000})
            self.assertEqual(deployment.call_args.kwargs['grants'],[*target['grants'],
                {'capability':runtime.RANDOM,'policy':'resource-random-examples'}])
            self.assertEqual([args[-1] for args,kwargs in client.call.call_args_list],['0','0'])


if __name__=='__main__':unittest.main()

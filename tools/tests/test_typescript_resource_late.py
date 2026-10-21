"""Adverse completion/authority controls; these are not signed guest evidence."""
import copy
from pathlib import Path
import tempfile
import unittest

from tools import resource_runtime_node as runtime
from tools import typescript_resource_late as late
from tools import typescript_resource_runtime_fixture as fixture
from tools.phase2_operator_process import WorkflowError
from tools.rust_capsule_node import configure


class TypeScriptLateFacilities(unittest.TestCase):
    def test_root_result_or_root_log_alone_cannot_qualify_the_callback(self):
        revision = {'releaseDigest':'sha256:'+'a'*64,'publicationId':'p'}
        budget = {'cpuFuel':1000,'memoryBytes':1000,'logBytes':16384}
        usage = {k:0 for k in ('outboundRequests','childCalls','effectCount','stateReadBytes',
            'stateWriteBytes','blobReadBytes','blobWriteBytes')}
        usage.update(cpuFuel=1,peakMemoryBytes=1,logBytes=late.log_charge('test'))
        row = {'activation':'test','exitCode':0,'processReaped':True,'decoded':[late.EXPECTED],
            'response':{'outcomeKnown':True,'requestDispatched':True,
                'data':{'resolvedRevision':revision,'consumption':usage}}}
        late.accepted(row,budget,revision,revision['releaseDigest'],late.EXPECTED)
        for change in ('root-log','extra-log','no-reap','wrong-revision','wrong-result','outbound','fuel','memory'):
            bad = copy.deepcopy(row)
            u = bad['response']['data']['consumption']
            if change == 'root-log':u['logBytes'] = late.log_charge('test',(late.ROOT_LOG,))
            elif change == 'extra-log':u['logBytes'] += 1
            elif change == 'no-reap':bad['processReaped'] = False
            elif change == 'wrong-revision':bad['response']['data']['resolvedRevision']['publicationId'] = 'other'
            elif change == 'wrong-result':bad['decoded'] = ['root-only']
            elif change == 'outbound':u['outboundRequests'] = 1
            elif change == 'fuel':u['cpuFuel'] = 1001
            else:u['peakMemoryBytes'] = 1001
            with self.subTest(change=change),self.assertRaises(WorkflowError):
                late.accepted(bad,budget,revision,revision['releaseDigest'],late.EXPECTED)

    def test_explicit_random_contract_keeps_original_runtime_and_cell_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            app,_record = fixture.project(root/'project',root/'outside',late_completion=True)
            world = (app/'wit/world.wit').read_bytes()
            self.assertIn(b'import latent:random/random@0.1.0;',world)
            actual = (root/'outside/library/index.mjs').read_bytes()
            self.assertEqual(actual,late.library_source(fixture.LIBRARY))
            self.assertEqual(actual.count(late.CALLBACK_LOG.encode()),1)
            (root/'signed').mkdir();(root/'signed/policy.json').write_bytes(b'{}\n')
            (root/'node').mkdir()
            _path,settings = configure(root/'node',root/'signed',12345,language='typescript')
            original = copy.deepcopy(settings)
            scalars = runtime.selection('typescript',standard_entropy=True)[1]
            capsule = {'execution':{'limits':{'memoryBytes':134217728}},
                'imports':[{'contract':name,'optional':False} for name in (*scalars,runtime.ACTIVATION)]}
            runtime.configure(settings,capsule,standard_entropy=True)
            self.assertEqual(settings['cells'],original['cells'])
            self.assertEqual(settings['providers']['activationRuntime']['limits'],runtime.LIMITS)
            self.assertEqual(len(settings['providers']['bindings']),11)
            with self.assertRaises(WorkflowError):runtime.configure({},capsule)
        for value in (1,'yes',None):
            with self.assertRaises(WorkflowError):runtime.selection('typescript',standard_entropy=value)
        with self.assertRaises(WorkflowError):runtime.selection('go',standard_entropy=True)


if __name__ == '__main__':unittest.main()

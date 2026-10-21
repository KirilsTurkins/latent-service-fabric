"""Controls for independent admission before Go scheduler allocation.

These controls qualify selection and source ordering, not signed execution.
"""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.go_guest import activation, managed_idle, queues, runtime
from tools.tests.test_go_managed_idle import bridge_sources


def managed_sources():
    sources = bridge_sources()
    sources['runtime/proc.go'] += '\tnewg.lsfOwner = lsfOwner\n'
    sources['runtime/runtime2.go'] = 'type g struct {\n\tlsfOwner [2]uint64\n}\n'
    managed_idle.runtime_sources(sources, runtime.ROOT / 'sdk/go-guest')
    return sources


class QueuedWork(unittest.TestCase):
    def test_normal_project_capture_and_selection_is_explicit(self):
        from tools.go_capsule_project import create, snapshot, validate
        from tools.go_application_dependencies import selection
        from tools.go_capsule_build import RECIPE
        self.assertEqual(selection()['runtimeProfile'], 'go-component-async-v1')
        self.assertIn(queues.PROFILE, activation.MANAGED_PROFILES)
        self.assertIn(queues.PROFILE, activation.INITIALIZER_PROFILES)
        self.assertIn('tools/go_guest/queues.py', RECIPE)
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / 'app', 'greeting', runtime_profile=queues.PROFILE)
            files = snapshot(project)
            selected, _, _ = validate(files)
            self.assertEqual(selected['runtimeProfile'], queues.PROFILE)
            self.assertIn('vendor/lsf/sdk/go-guest/runtime/queue_bridge.go.in', files)
            self.assertIn(b'import latent:runtime/activation@0.1.0;', files['wit/world.wit'])
        for profile in ('go-component-activation-v7', queues.PROFILE + '-extra'):
            with self.assertRaisesRegex(ValueError, 'profile-not-installed'):
                selection({'runtimeProfile': profile})

    def test_admission_precedes_publication_and_rolls_back_only_unpublished_task(self):
        sources = managed_sources()
        queues.runtime_sources(sources, runtime.ROOT / 'sdk/go-guest')
        proc, bridge = sources['runtime/proc.go'], sources['runtime/os_wasip1.go']
        task = bridge.split('func lsfNewTask(', 1)[1].split('\n}', 1)[0]
        self.assertLess(task.index('lsfRegister(0,'), task.index('lsfReserveQueue('))
        self.assertLess(task.index('lsfReserveQueue('), task.index('lsfActivationTasks++'))
        self.assertIn('queue[0], queue[1]', task)
        self.assertIn('newg.lsfQueue = [2]uint64{lsfOwner[2], lsfOwner[3]}', proc)
        reserve = bridge.split('func lsfReserveQueue(', 1)[1].split('\n}', 1)[0]
        self.assertIn('lsfRegister(3, 1, int64(parent[0]), int64(parent[1])', reserve)
        self.assertIn('if rollbackTask {', reserve)
        self.assertIn('if settled.tag != 0 { lsfFail(', reserve)
        self.assertNotIn('make(', reserve)
        self.assertNotIn('new(', reserve)

    def test_queue_identity_survives_park_wake_and_precedes_task_retirement(self):
        sources = managed_sources()
        queues.runtime_sources(sources, runtime.ROOT / 'sdk/go-guest')
        bridge = sources['runtime/os_wasip1.go']
        for name in ('lsfTaskPark', 'lsfTaskWake'):
            body = bridge.split('func ' + name + '(', 1)[1].split('\n}', 1)[0]
            self.assertNotIn('lsfReserveQueue', body)
            self.assertNotIn('lsfReleaseQueue', body)
            self.assertNotIn('gp.lsfQueue =', body)
        destroyed = bridge.split('func lsfTaskDestroyed(', 1)[1].split('\n}', 1)[0]
        self.assertLess(destroyed.index('lsfReleaseQueue(gp.lsfQueue)'),
                        destroyed.index('lsfSettle(int64(gp.lsfOwner[0])'))
        self.assertLess(destroyed.index('lsfReleaseQueue(gp.lsfQueue)'),
                        destroyed.rindex('gp.lsfQueue = [2]uint64{}'))
        release = bridge.split('func lsfReleaseQueue(', 1)[1].split('\n}', 1)[0]
        self.assertIn('owner[1] == 0', release)
        self.assertIn('if result.tag != 0 { lsfFail(', release)

    def test_gc_capacity_is_prepaid_and_retirement_keeps_the_resume_fence(self):
        sources = managed_sources()
        queues.runtime_sources(sources, runtime.ROOT / 'sdk/go-guest')
        bridge = sources['runtime/os_wasip1.go']
        prepare = bridge.split('func lsfPrepareManagedIdle(', 1)[1].split('\n}', 1)[0]
        self.assertLess(prepare.index('lsfManagedQueues[index] = lsfReserveQueue('),
                        prepare.index('lsfManagedPrepared = true'))
        for name in ('lsfTakeManagedAdmission', 'lsfTakeManagedOwner'):
            body = bridge.split('func ' + name + '(', 1)[1].split('\n}', 1)[0]
            self.assertNotIn('lsfRegister(', body)
            self.assertNotIn('lsfSettle(', body)
            self.assertNotIn('make(', body)
        retire = bridge.split('func lsfRetireManagedIdle(', 1)[1].split('\n}', 1)[0]
        self.assertLess(retire.index('status != _Gwaiting'), retire.index('lsfReleaseQueue('))
        self.assertLess(retire.index('lsfReleaseQueue('), retire.index('lsfSettle('))
        self.assertNotIn('lsfManagedOwners[index] =', retire)
        self.assertIn('!lsfManagedPrepared', bridge.split('func lsfManagedBeforeRun(', 1)[1].split('\n}', 1)[0])

    def test_missing_or_duplicate_hooks_refuse_instead_of_silently_dropping_accounting(self):
        original = managed_sources()
        for filename, marker in (
                ('runtime/runtime2.go', '\tlsfOwner [2]uint64\n'),
                ('runtime/proc.go', '\tnewg.lsfOwner = lsfOwner\n'),
                ('runtime/os_wasip1.go', 'func lsfNewTask(fn *funcval, parent *g) [2]uint64 {'),
                ('runtime/os_wasip1.go', '\tfor _, owner := range lsfManagedOwners {')):
            for replacement in ('changed hook', marker + marker):
                sources = copy.deepcopy(original)
                sources[filename] = sources[filename].replace(marker, replacement)
                with self.subTest(filename=filename, replacement=replacement), \
                        self.assertRaisesRegex(ValueError, 'overlay-contract-drift'):
                    queues.runtime_sources(sources, runtime.ROOT / 'sdk/go-guest')
        self.assertEqual(original, managed_sources())

    def test_queue_case_oracle_rejects_preentry_failures_wrong_revision_and_early_success(self):
        from tools.go_queue_node import outcome
        from tools.go_resource_runtime_fixture import EXPECTED
        target = {'budget':{'cpuFuel':100,'memoryBytes':200,'logBytes':300}}
        revision = {'releaseDigest':'controlled-component'}
        usage = dict(cpuFuel=1,peakMemoryBytes=1,logBytes=1,outboundRequests=0,childCalls=0,
                     effectCount=0,stateReadBytes=0,stateWriteBytes=0,blobReadBytes=0,blobWriteBytes=0)
        row = {'processReaped':True,'exitCode':0,'decoded':[{'ok':EXPECTED['fresh']}],
               'response':{'outcomeKnown':True,'data':{'resolvedRevision':revision,'consumption':usage}}}
        outcome(row,target,revision,'fresh',False)
        denied = copy.deepcopy(row)
        denied['exitCode'] = 4
        denied['response']['error'] = {'code':'guest-trap'}
        denied['response']['data']['consumption']['logBytes'] = 0
        outcome(denied,target,revision,'parallel',True)
        for path, value in ((('processReaped',),False),(('response','outcomeKnown'),False),
                (('response','data','resolvedRevision'),{}),(('response','data','consumption','cpuFuel'),0),
                (('response','data','consumption','peakMemoryBytes'),0),
                (('response','data','consumption','outboundRequests'),1)):
            altered = copy.deepcopy(denied)
            cursor = altered
            for key in path[:-1]:cursor = cursor[key]
            cursor[path[-1]] = value
            with self.subTest(path=path), self.assertRaises((ValueError,RuntimeError)):
                outcome(altered,target,revision,'parallel',True)
        for code in ('permission-denied','admission-rejected','resource-exhausted','cancelled'):
            altered = copy.deepcopy(denied)
            altered['response']['error']['code'] = code
            with self.subTest(code=code), self.assertRaises((ValueError,RuntimeError)):
                outcome(altered,target,revision,'parallel',True)
        with self.assertRaises((ValueError,RuntimeError)):
            outcome(row,target,revision,'parallel',True)
        with self.assertRaises((ValueError,RuntimeError)):
            outcome(denied,target,revision,'fresh',False)

    def test_queue_only_profile_keeps_other_original_limits_and_rejects_open_selector(self):
        from tools import resource_runtime_node as node
        from tools.go_node_stop_probe import OWNER_LIMITS
        # Selection stays the v5 default; only the new explicit programme can
        # ask configure to select one of the three fixed queue differential caps.
        self.assertEqual(node.selection('go')[2],OWNER_LIMITS)
        with self.assertRaisesRegex(RuntimeError,'closed-Go-queue-ceiling'):
            node.configure({}, {}, language='go', go_queue_ceiling=True)
        with self.assertRaisesRegex(RuntimeError,'closed-Go-queue-ceiling'):
            node.configure({}, {}, language='typescript', go_queue_ceiling=9)

    def test_capture_binds_selected_v6_profile_before_compilation_and_preserves_v5_default(self):
        from types import SimpleNamespace
        from tools import go_resource_runtime_fixture as fixture
        from tools import go_native_authoring as native, go_dependency_authoring as review
        from tools import go_application_dependencies as dependencies
        from tools.dev_workflow.common import encode
        for profile in (fixture.PROFILE,queues.PROFILE):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                app,outside = root/'app',root/'outside'
                app.mkdir();outside.mkdir()
                (app/'sdk-lock.json').write_bytes(b'unchanged-sdk')
                (app/'capsule-project.json').write_bytes(encode({'runtimeProfile':profile}))
                (app/fixture.LOCK).write_bytes(b'accepted-controlled-lock')
                for name in ('library','data'):(outside/name).mkdir()
                lock = {'artifacts':[
                    {'id':'library','metadata':{'module':fixture.PACKAGES[0],'version':'v0.0.0'},
                     'role':'application','dependencies':['data']},
                    {'id':'data','metadata':{'module':fixture.PACKAGES[1],'version':'v0.0.0'},
                     'role':'application','dependencies':[]}], 'executableInputs':[]}
                def resolve(_app,candidate,**_kwargs):
                    candidate.write_bytes(encode(lock))
                    return lock
                verified = SimpleNamespace(lock={'selection':{'runtimeProfile':profile}},identity='controlled')
                with patch.object(native,'edit'), patch.object(native,'create_lock'), \
                        patch.object(dependencies,'resolve',side_effect=resolve),patch.object(review,'review'), \
                        patch.object(fixture,'verify_inputs',return_value=verified):
                    if profile == queues.PROFILE:
                        with self.assertRaisesRegex(RuntimeError,'capture-project-profile'):
                            fixture.capture(app,outside,root/'not-executed-go')
                        self.assertTrue((outside/'library').exists())
                        result = fixture.capture(app,outside,root/'not-executed-go',runtime_profile=profile)
                    else:
                        result = fixture.capture(app,outside,root/'not-executed-go')
                    self.assertTrue(result['outsideOriginalsRemoved'])
                    self.assertFalse((outside/'library').exists())
                    self.assertFalse((outside/'data').exists())
                    self.assertEqual((app/'sdk-lock.json').read_bytes(),b'unchanged-sdk')

    def test_queue_reports_retain_each_invocation_before_validation_and_retirement(self):
        from tools import go_queue_node as node
        from tools.rust_capsule_project import read_json
        clients = {tenant:object() for tenant in ('examples','foreign')}
        targets = {tenant:object() for tenant in clients}
        for ceiling,count in ((8,2),(9,6)):
            with self.subTest(ceiling=ceiling), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary)
                with patch.object(node,'selected_revision',return_value={'releaseDigest':'original'}), \
                        patch.object(node,'call',return_value={'controlledInvocation':True}), \
                        patch.object(node,'outcome'),patch.object(node,'retire',return_value={'controlledRetirement':True}):
                    result = node.programme(clients,targets,None,output,'original',ceiling)
                invoked = sorted(output.glob('queue-*-invoked.json'))
                retired = sorted(output.glob('queue-*-retired.json'))
                self.assertEqual((len(invoked),len(retired)),(count,count))
                self.assertEqual(result['status'],'passed')
                for path in invoked:
                    self.assertNotIn('retirement',read_json(path)['cases'][-1])
                for path in retired:
                    self.assertEqual(read_json(path)['cases'][-1]['retirement'],{'controlledRetirement':True})
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            with patch.object(node,'selected_revision',return_value={'releaseDigest':'original'}), \
                    patch.object(node,'call',return_value={'controlledInvocation':True}), \
                    patch.object(node,'outcome',side_effect=RuntimeError('refused')),patch.object(node,'retire') as retire:
                with self.assertRaisesRegex(RuntimeError,'refused'):
                    node.programme(clients,targets,None,output,'original',8)
                retire.assert_not_called()
            self.assertEqual(len(list(output.glob('queue-*-invoked.json'))),1)
            self.assertEqual(len(list(output.glob('queue-*-retired.json'))),0)
            self.assertEqual(read_json(output/'queue-FAILED.json')['status'],'failed')

    def test_incomplete_overlay_refuses_before_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            goroot = root / 'goroot'
            goroot.mkdir()
            for value in (True, 1, 'yes'):
                output = root / 'overlay'
                with patch.object(runtime, 'checked_sources', return_value={}), \
                        self.assertRaisesRegex(ValueError, 'queued-work-requires-complete'):
                    runtime.overlay(goroot, output, queued_work=value)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

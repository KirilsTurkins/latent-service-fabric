"""Exact transitive capture, clock parsing, actual-result and retirement fences."""
import ast
import copy
import json
from pathlib import Path
import struct
import hashlib
import tempfile
import unittest
from unittest.mock import patch
import yaml

from tools import java_resource_fixture as fixture, java_resource_probe as probe
from tools import qualify_java_resources as qualification
from tools import application_dependencies as dependencies
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_project import ROOT, digest, read_file
from tools.tests.test_sdk_scratch_probe import invocation

WALL = 1_800_000_000_000
BEFORE = WALL-1
AFTER = WALL+1


class JavaResourceConformance(unittest.TestCase):
    def test_normal_unknown_transitive_capture_binds_exact_data_and_removes_originals(self):
        class Javac:
            def run(self, stage, tool, *args):
                assert (stage,tool) == ('outside-resource-javac','javac')
                assert args[:5] == ('--release','25','-proc:none','-encoding','UTF-8')
                output = Path(args[6])
                for name in ('outside/resources/Library.class','outside/resourcechild/Data.class'):
                    target = output/name; target.parent.mkdir(parents=True,exist_ok=True)
                    target.write_bytes(b'\xca\xfe\xba\xbe'+struct.pack('>HH',0,69)+b'controlled-javac-boundary')
        with tempfile.TemporaryDirectory() as directory:
            app, receipt = fixture.capture(Path(directory),Javac())
            actual = dependencies.verify_inputs(app,'java')
            self.assertEqual(actual.identity,receipt['capturedInputIdentity'])
            by_id = {row['id']:row for row in actual.lock['artifacts']}
            self.assertIn(fixture.CHILD,by_id[fixture.PARENT]['dependencies'])
            self.assertEqual(receipt['resources'],{name:{'digest':digest(raw),'size':len(raw)} for name,raw in fixture.DATA.items()})
            self.assertFalse((Path(directory)/'outside-originals').exists())
            self.assertFalse(receipt['catalogueRegistration'])
            self.assertEqual((app/'src/dev/latent/app/Capsule.java').read_bytes(),read_file(ROOT/fixture.EXAMPLE/'Capsule.java'))
            self.assertEqual(set(fixture.DATA.values()),{'Gr\u00fc\u00dfe\0\u96ea\n'.encode(),bytes((0,255,128,65,13,10)),b''})

    def test_clock_parser_requires_actual_full_width_wall_and_ordered_bounded_monotonic(self):
        result = probe.clock_values([{'ok':f'clock|wall={WALL}|first=7|second=8|fresh=1'}],BEFORE,AFTER)
        self.assertTrue(result['wallExceedsU32'])
        self.assertFalse(result['monotonicSampleExceedsU32'])
        self.assertFalse(result['providerSleepOrClockOverride'])
        for text in (f'clock|wall={WALL}|first=9|second=8|fresh=1',
                f'clock|wall={WALL}|first=8|second={2**63}|fresh=1',
                'clock|wall=3|first=7|second=8|fresh=1',
                f'clock|wall={WALL+2}|first=7|second=8|fresh=1',
                f'clock|wall={WALL}|first=-1|second=8|fresh=1', 'unknown'):
            with self.subTest(text=text),self.assertRaisesRegex(RuntimeError,'java-resource-clock'):
                probe.clock_values([{'ok':text}],BEFORE,AFTER)
        for value in (None,[],[{'error':'clock'}],[{'ok':42}],[{'ok':'x','extra':'x'}]):
            with self.subTest(value=value),self.assertRaisesRegex(RuntimeError,'result-shape'):
                probe.clock_values(value,BEFORE,AFTER)

    def execute(self, mutation=None, grants=None):
        rows = [invocation(value) for value in fixture.EXPECTED.values()]
        rows += [invocation(f'clock|wall={WALL}|first=7|second=8|fresh=1'),invocation(trap=True),
            invocation(fixture.EXPECTED['binary'])]
        if mutation: mutation(rows)
        result = {'invocations':[],'providerIdle':[],'samples':[]}
        idle = {'unavailable':[],'counters':{name:'0' for name in ACTIVE_COUNTERS}}
        target = {'grants':grants if grants is not None else [
            {'capability':'latent:clock/monotonic@0.1.0'},{'capability':'latent:clock/wall@0.1.0'}],
            'budget':{'cpuFuel':1000,'memoryBytes':8192}}
        def exact(_client,row,value):
            if row['decoded'] != value or row['exitCode'] != 0: raise RuntimeError('controlled-result-mismatch')
        with patch('tools.rust_capsule_node.call',side_effect=rows) as calls, \
                patch('tools.rust_capsule_node.assert_value',side_effect=exact), \
                patch('tools.rust_capsule_node.provider_idle',return_value=idle) as retired, \
                patch('tools.rust_capsule_node.sample',return_value={'physical':True}) as physical, \
                patch.object(probe.time,'time_ns',side_effect=[BEFORE*1_000_000,AFTER*1_000_000]):
            probe.probe(object(),target,object(),result,5)
        return result,calls,retired,physical

    def test_ten_calls_require_exact_resources_trap_fresh_and_actual_retirement_after_each(self):
        result,calls,idle,physical = self.execute()
        self.assertEqual([row.args[4][0] for row in calls.call_args_list],
            ['resources:'+mode for mode in (*fixture.EXPECTED,'clock','trap','binary')])
        self.assertEqual((len(result['invocations']),idle.call_count,physical.call_count),(10,10,10))
        self.assertFalse(result['javaResourceConformance']['fullTicketQualification'])
        self.assertFalse(result['javaResourceConformance']['crossTenantQualification'])

    def test_unknown_outcomes_wrong_bytes_side_effects_or_wrong_trap_cannot_qualify(self):
        for mutation in (lambda rows:rows[0].update(processReaped=False),
                lambda rows:rows[1]['response'].update(outcomeKnown=False),
                lambda rows:rows[1]['response']['data']['consumption'].update(effectCount=1),
                lambda rows:rows[1]['response']['data']['consumption'].update(cpuFuel=1001),
                lambda rows:rows[1].update(decoded=[{'ok':'replacement'}]),
                lambda rows:rows[-2]['response']['error'].update(code='guest-runtime-error'),
                lambda rows:rows[-1].update(decoded=[{'ok':'stale-state'}])):
            with self.subTest(mutation=mutation),self.assertRaises(RuntimeError): self.execute(mutation)
        with self.assertRaisesRegex(RuntimeError,'clock-authority-only'):
            self.execute(grants=[{'capability':'latent:random/random@0.1.0'}])

    def node(self):
        value = self.execute()[0]
        value.update(status='passed',language='java',nodeShutdown={'reaped':True,'record':{'clean':True}})
        value['invocations'] = [invocation('original') for _ in range(29)]+value['invocations']
        value['samples'] += [{} for _ in range(26)]
        value['providerIdle'] += [{'unavailable':[],'counters':{name:'0' for name in ACTIVE_COUNTERS}} for _ in range(6)]
        return value

    def test_report_requires_original29_data_clock_and_owner_zero_without_count_relaxation(self):
        node = self.node()
        proof = qualification.observation(node)
        self.assertEqual((proof['totalInvocations'],proof['physicalSamples'],proof['zeroActiveOwnerSamples']),(39,36,16))
        for mutate in (lambda value:value['invocations'].pop(),
                lambda value:value['javaResourceConformance']['cases'][0]['invocation'].update(decoded=[{'ok':'not-data'}]),
                lambda value:value['providerIdle'][0]['counters'].update({ACTIVE_COUNTERS[0]:'1'}),
                lambda value:value['nodeShutdown']['record'].update(clean=False),
                lambda value:value['javaResourceConformance']['clock'].update(wallUnixMillis=3)):
            changed = copy.deepcopy(node); mutate(changed)
            with self.subTest(mutate=mutate),self.assertRaises(RuntimeError): qualification.observation(changed)

    def test_selector_is_boolean_java_only_and_cannot_replace_scratch_programme(self):
        from tools.run_rust_capsule_workflow import run
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'not-created'
            for selected in ({'language':'java','java_resource_conformance':1},
                    {'language':'go','java_resource_conformance':True},
                    {'language':'java','java_resource_conformance':True,'standard_scratch_refusal':True}):
                with self.subTest(selected=selected),self.assertRaisesRegex(RuntimeError,'java-resource-conformance-selection'):
                    run(Path('cli'),Path('node'),Path('signed'),output,**selected)
                self.assertFalse(output.exists())

    def test_original_shared_runner_ast_is_preserved_after_only_new_selector_guard_and_branch(self):
        current = ast.parse(read_file(ROOT/'tools/run_rust_capsule_workflow.py').decode())
        class Project(ast.NodeTransformer):
            def visit_FunctionDef(self,node):
                if node.name == 'run':
                    self_outer = node.args.kwonlyargs.pop(); node.args.kw_defaults.pop()
                    if self_outer.arg != 'java_resource_conformance': raise AssertionError('selector-order')
                    node.body.pop(0)
                return self.generic_visit(node)
            def visit_If(self,node):
                if isinstance(node.test,ast.Name) and node.test.id == 'java_resource_conformance': return None
                return self.generic_visit(node)
        self.assertEqual(hashlib.sha256(ast.dump(Project().visit(current),include_attributes=False).encode()).hexdigest(),
            '717ee343cfdced134f3cd0660e750dd7e80ea39484f75cd50e1c671a32634fcc')

    def test_resource_child_preserves_all_original_jobs_commands_and_deadlines(self):
        path = '.github/workflows/java-guest-feasibility.yml'
        current = yaml.safe_load(read_file(ROOT/path))
        def normalized(value):
            if isinstance(value,dict): return {str(key):normalized(item) for key,item in value.items()}
            if isinstance(value,list): return [normalized(item) for item in value]
            return value
        def fingerprint(value):
            return hashlib.sha256(json.dumps(normalized(value),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(fingerprint({key:value for key,value in current.items() if key != 'jobs'}),
            'af0a544a198c8b85f77c03c40b2791512abfc246ecd90800c0b92b0e0e02cf32')
        expected = {'compiler-component': '218d365d543d4ca4f1b872aba93c6efaa1f73fd3272ef07ec1f0a1bc0b2878d6', 'dependency-ingestion': '321f9faceccf9dbd41a552de077947e9858e665f2ee4cc3322cf5ca4b27c9811', 'scratch-refusals': '5191c7232f3b9f822ebbd43f9abae51b8f058820e3665bfba571b68ba4a49b72'}
        self.assertEqual({name:fingerprint(current['jobs'][name]) for name in expected},expected)
        job = current['jobs']['resource-conformance']
        self.assertEqual((job['needs'],job['timeout-minutes']),('compiler-component',20))
        commands = '\n'.join(row.get('run','') for row in job['steps'])
        self.assertIn('tools/qualify_java_resources.py',commands)
        self.assertNotIn('cargo ',commands)
        self.assertNotIn('qualify_java_capsules.py',commands)


if __name__ == '__main__': unittest.main()

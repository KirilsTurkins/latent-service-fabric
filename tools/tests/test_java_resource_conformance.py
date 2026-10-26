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
from tools.tests.test_java_scratch_wiring import original_compiler_parent

WALL = 1_800_000_000_000
BEFORE = WALL-1
AFTER = WALL+1


class JavaResourceConformance(unittest.TestCase):
    def test_downloaded_native_modes_validate_then_execute_and_refuse_tamper(self):
        import os
        import sys
        if sys.platform != 'linux':
            self.skipTest('requires real Linux executable modes/process ownership')
        from tools.tests.test_sdk_scratch_qualification import ordinary, replace_json
        from tools import qualify_sdk_scratch as scratch
        from tools.build_process import BuildProcessError, run_bounded_result
        from tools.phase3_resource_identity import file_identity

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            # Controlled source/normal qualification fixture; no Java build.
            receipt = ordinary(root)
            receipt['schemaVersion'] = 'latent.java-capsule.qualification.v1'
            node = json.loads((root/'node/workflow.json').read_bytes())
            node['language'] = 'java'
            node['invocations'] = [{'original': index} for index in range(29)]
            replace_json(root/'node/workflow.json', node)
            receipt['node']['receiptDigest'] = file_identity(root/'node/workflow.json')['sha256']
            for name in scratch.PRODUCTS:
                path = root/'native-binaries'/name.replace('/', '-')
                path.write_bytes(b'#!/usr/bin/env python3\nprint("resource-native-ready")\n')
                path.chmod(0o644)
                receipt['binaries'][name] = file_identity(path)
            replace_json(root/'qualification.json', receipt)
            source = json.loads((root/'source-inputs.json').read_bytes())
            unrelated = root/'unrelated'; unrelated.write_bytes(b'not a product'); unrelated.chmod(0o644)
            contracts = root/'native-binaries/examples-capsule_contracts'
            with self.assertRaisesRegex(BuildProcessError, 'command-failed'):
                run_bounded_result([str(contracts)], cwd=root, env=dict(os.environ), timeout_seconds=5, max_output_bytes=1024)
            # Keep real receipt/companion/product validation. Only the selected
            # source fixture replaces repository inputs; chmod/exec are real.
            def prepared(directory, language):
                return scratch._prepared_with_inputs(directory, language, source)
            with patch.object(qualification, 'prepared', side_effect=prepared):
                binaries, _, _ = qualification.prepared_executables(root)
            self.assertEqual({name:file_identity(path) for name,path in binaries.items()}, receipt['binaries'])
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o700 for path in binaries.values()))
            self.assertEqual(unrelated.stat().st_mode & 0o777, 0o644)
            result = run_bounded_result([str(contracts)], cwd=root, env=dict(os.environ), timeout_seconds=5, max_output_bytes=1024)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, b'resource-native-ready\n', b''))
            for path in binaries.values(): path.chmod(0o644)
            binaries['latent'].write_bytes(b'changed after original observation')
            with patch.object(qualification, 'prepared', side_effect=prepared), \
                    self.assertRaisesRegex(RuntimeError, 'scratch-original-native-tuple-mismatch'):
                qualification.prepared_executables(root)
            self.assertTrue(all(path.stat().st_mode & 0o777 == 0o644 for path in binaries.values()))

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
                    for expected in ('embedded_resource_conformance', 'java_resource_conformance'):
                        argument, default = node.args.kwonlyargs.pop(), node.args.kw_defaults.pop()
                        if argument.arg != expected or not isinstance(default, ast.Constant) or default.value is not False:
                            raise AssertionError('selector-order-or-default')
                        guard = node.body.pop(0)
                        if not isinstance(guard, ast.Expr) or expected not in ast.unparse(guard):
                            raise AssertionError('selector-guard-order')
                return self.generic_visit(node)
            def visit_If(self,node):
                if isinstance(node.test,ast.Name) and node.test.id in {'java_resource_conformance', 'embedded_resource_conformance'}: return None
                return self.generic_visit(node)
        self.assertEqual(hashlib.sha256(ast.dump(Project().visit(current),include_attributes=False).encode()).hexdigest(),
            '717ee343cfdced134f3cd0660e750dd7e80ea39484f75cd50e1c671a32634fcc')

    def test_resource_child_preserves_all_original_jobs_commands_and_deadlines(self):
        path = '.github/workflows/java-guest-feasibility.yml'
        current = yaml.safe_load(read_file(ROOT/path))
        private = current[True]['workflow_dispatch']['inputs'].pop('public_fiber_private_scalar_llvm')
        self.assertEqual(private['type'], 'boolean');self.assertIs(private['default'], False)
        clause = " && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_private_scalar_llvm)"
        for name in ('compiler-component', 'dependency-ingestion', 'http-public-spi'):
            self.assertEqual(current['jobs'][name]['if'].count(clause), 1)
            current['jobs'][name]['if'] = current['jobs'][name]['if'].replace(clause, '', 1)
        self.assertEqual(current['jobs']['public-fiber-assembly']['if'],
            "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm || inputs.public_fiber_private_scalar_llvm) }}")
        current['jobs']['public-fiber-assembly']['if'] = "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm) }}"
        derived = current[True]['workflow_dispatch']['inputs'].pop('public_fiber_derived_llvm')
        self.assertEqual(derived['type'], 'boolean');self.assertIs(derived['default'], False)
        for name, clause in (
                ('compiler-component', " && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_derived_llvm)"),
                ('dependency-ingestion', " && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_derived_llvm)"),
                ('http-public-spi', ' && !inputs.public_fiber_derived_llvm')):
            self.assertEqual(current['jobs'][name]['if'].count(clause), 1)
            current['jobs'][name]['if'] = current['jobs'][name]['if'].replace(clause, '', 1)
        self.assertEqual(current['jobs']['public-fiber-assembly']['if'],
            "${{ github.event_name == 'workflow_dispatch' && (inputs.public_fiber_assembly || inputs.public_fiber_derived_llvm) }}")
        current['jobs']['public-fiber-assembly']['if'] = "${{ github.event_name == 'workflow_dispatch' && inputs.public_fiber_assembly }}"
        public = current[True]['workflow_dispatch']['inputs'].pop('public_fiber_assembly')
        self.assertEqual(public['type'], 'boolean');self.assertIs(public['default'], False)
        assembly = current['jobs'].pop('public-fiber-assembly')
        self.assertEqual(assembly['if'],
            "${{ github.event_name == 'workflow_dispatch' && inputs.public_fiber_assembly }}")
        self.assertEqual(current['jobs']['compiler-component']['if'],
            "${{ (github.event_name != 'workflow_dispatch' || !inputs.java_http_spi) && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_assembly) }}")
        current['jobs']['compiler-component']['if'] = "${{ github.event_name != 'workflow_dispatch' || !inputs.java_http_spi }}"
        for name, clause in (
                ('dependency-ingestion', " && (github.event_name != 'workflow_dispatch' || !inputs.public_fiber_assembly)"),
                ('http-public-spi', ' && !inputs.public_fiber_assembly')):
            self.assertEqual(current['jobs'][name]['if'].count(clause), 1)
            current['jobs'][name]['if'] = current['jobs'][name]['if'].replace(clause, '', 1)
        flag = current[True]['workflow_dispatch']['inputs'].pop('java_http_spi')
        self.assertEqual(flag['type'], 'boolean'); self.assertIs(flag['default'], False)
        spi = current['jobs'].pop('http-public-spi')
        focused = yaml.safe_load(read_file(ROOT/'.github/workflows/java-http-fiber-lifecycle.yml'))
        self.assertEqual(spi, focused['jobs']['http-public-spi'])
        parent = original_compiler_parent(self, current['jobs']['compiler-component'])
        current['jobs']['compiler-component'] = parent
        self.assertEqual(parent.pop('if'), "${{ github.event_name != 'workflow_dispatch' || !inputs.java_http_spi }}")
        dependency = current['jobs']['dependency-ingestion']
        self.assertEqual(dependency['if'], "${{ (github.event_name != 'workflow_dispatch' || !inputs.qualify-scratch-refusals) && (github.event_name != 'workflow_dispatch' || !inputs.java_http_spi) }}")
        dependency['if'] = "${{ github.event_name != 'workflow_dispatch' || !inputs.qualify-scratch-refusals }}"
        steps = parent['steps']
        retained = next(step for step in steps if step.get('name') ==
            'Retain diagnostics, generated source and component candidates')
        added = '${{ runner.temp }}/java-activation-fibers/build/component-inputs/**'
        self.assertEqual(retained['with']['path'].splitlines().count(added), 1)
        retained['with']['path'] = retained['with']['path'].replace(added + '\n', '', 1)
        index = next(i for i, step in enumerate(steps) if step.get('name') ==
            'Export only exact normal public prerequisites for the separate Java scratch packet')
        qualified = next(i for i, step in enumerate(steps) if step.get('name') ==
            'Qualify standalone Java projects, nine SDK components, signed node and printed guide')
        self.assertEqual(index, qualified + 1)
        self.assertEqual(steps[index + 1]['name'], 'Retain verified normal Java products without keys or compiler caches')
        moved = steps[index:index + 2]; del steps[index:index + 2]; steps.extend(moved)
        def normalized(value):
            if isinstance(value,dict): return {str(key):normalized(item) for key,item in value.items()}
            if isinstance(value,list): return [normalized(item) for item in value]
            return value
        def fingerprint(value):
            return hashlib.sha256(json.dumps(normalized(value),sort_keys=True,separators=(',',':')).encode()).hexdigest()
        self.assertEqual(fingerprint({key:value for key,value in current.items() if key != 'jobs'}),
            'af0a544a198c8b85f77c03c40b2791512abfc246ecd90800c0b92b0e0e02cf32')
        expected = {'compiler-component': 'ac1715b0d2b3ccca17b2cd6d25f1f35a18efc32080454bfcd15aeda634617a5f', 'dependency-ingestion': '463d271323baf0deb4d186634df15160d1a9e13163545004a0273236e9ba083b', 'scratch-refusals': 'a8adfc51cf6132b942270f477b9999bdefbd7845f164e3b04ec84f355e44884c'}
        self.assertEqual({name:fingerprint(current['jobs'][name]) for name in expected},expected)
        job = current['jobs']['resource-conformance']
        self.assertEqual((job['needs'],job['timeout-minutes']),('compiler-component',20))
        commands = '\n'.join(row.get('run','') for row in job['steps'])
        self.assertIn('tools/qualify_java_resources.py',commands)
        self.assertNotIn('cargo ',commands)
        self.assertNotIn('qualify_java_capsules.py',commands)


if __name__ == '__main__': unittest.main()

"""Bounded reader/controller controls; synthetic carriers never execute LLVM/JVM."""
from contextlib import ExitStack
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from tools.java_guest import wineh_ir as ir, public_wineh as old, wineh_filter as pipe
from tools.java_guest import wineh_preclang as pre
from tools.java_guest import llvm_ssa_consumer_inputs as inputs
from tools.java_guest.compiler import Compiler
from tools.rust_capsule_project import ROOT, canonical, digest
from tools.tests import test_java_llvm_ssa_consumer as carrier_fixtures


IR = (f'*** IR Dump Before {ir.PASS} ***\ndefine ptr @{ir.FUNCTION}() {{\n'
      'entry:\n  %v = phi i32 [ 1, %a ], [ 2, %b ]\n'
      '  %cs = catchswitch within none [label %handler] unwind to caller\n}\n'
      f'*** IR Dump After {ir.PASS} ***\ndefine ptr @{ir.FUNCTION}() {{\n'
      'entry:\n  %slot = alloca i32\n  store i32 %v, ptr %slot, align 4\n'
      '  store i32 %v, ptr %slot, align 4\n  store i32 %other, ptr %slot, align 4\n'
      '  store volatile i32 %v, ptr %slot, align 4\n  ret ptr null\n}\n').encode()


class JavaPublicWinEHPreClang(unittest.TestCase):
    def test_counter_bounds_hashes_and_catchswitch_phi_counts_are_syntactic_only(self):
        value = ir.observe(IR)
        self.assertEqual(value['status'], 'observed')
        self.assertEqual(value['snapshots']['before']['catchswitchPhi'], 1)
        self.assertEqual(value['snapshots']['before']['catchswitchPhiIncoming'], 2)
        after = value['snapshots']['after']
        self.assertEqual((after['simpleSsaStores'], after['simpleSsaStorePatterns'],
                          after['simpleSsaRepeatedStores'], after['volatileStore']), (3, 2, 1, 1))
        ir.validate_patterns(value['syntacticStorePatterns'], value['snapshots'])
        self.assertNotIn('%slot', canonical(value).decode())
        self.assertNotIn('%other', canonical(value).decode())
        self.assertEqual(value['syntacticStorePatterns']['claim'], ir.PATTERN_CLAIM)
        self.assertEqual(value['syntacticStorePatterns']['coverage'],
                         {'before': 'complete', 'after': 'complete'})
        # Valid LLVM store forms outside the direct-SSA pattern classifier must
        # not truncate the independent complete before/after phase counters.
        extra = (b'  store %named zeroinitializer, ptr %destination, align 4\n'
                 b'  store i32 %v, ptr getelementptr (i32, ptr @global, i32 0), align 4\n')
        partial = ir.observe(IR.replace(b'  %cs = catchswitch', extra + b'  %cs = catchswitch')
                             .replace(b'  ret ptr null', extra + b'  ret ptr null'))
        self.assertEqual(partial['status'], 'observed')
        self.assertFalse(partial['prefixOnly'])
        self.assertEqual(partial['snapshots']['before']['store'], 2)
        self.assertEqual(partial['snapshots']['after']['store'], 6)
        for phase in ('before', 'after'):
            self.assertEqual(partial['snapshots'][phase]['instructions'],
                             value['snapshots'][phase]['instructions'] + 2)
            self.assertEqual(partial['snapshots'][phase]['unclassifiedSsaStoreCandidates'], 2)
            for key in ('phi', 'phiIncoming', 'catchswitchPhi', 'catchswitchPhiIncoming',
                        'simpleSsaStores', 'simpleSsaStorePatterns', 'simpleSsaRepeatedStores'):
                self.assertEqual(partial['snapshots'][phase][key], value['snapshots'][phase][key])
        self.assertEqual(partial['syntacticStorePatterns']['coverage'],
                         {'before': 'partial', 'after': 'partial'})
        ir.validate_patterns(partial['syntacticStorePatterns'], partial['snapshots'])
        forged = copy.deepcopy(partial['syntacticStorePatterns'])
        forged['coverage']['after'] = 'complete'
        with self.assertRaisesRegex(ValueError, 'store-pattern-summary'):
            ir.validate_patterns(forged, partial['snapshots'])
        for bad in (2.0, True, 7):
            snapshots = copy.deepcopy(partial['snapshots'])
            snapshots['after']['unclassifiedSsaStoreCandidates'] = bad
            with self.assertRaisesRegex(ValueError, 'store-pattern-summary'):
                ir.validate_patterns(partial['syntacticStorePatterns'], snapshots)
        self.assertEqual(ir.observe(IR.replace(b'ret ptr null', b'unknown i32 %v'))['reason'],
                         'instruction-opcode')
        self.assertEqual(value['catchswitchPhiIncomingShapes']['phases']['before']['opaque'], 1)
        rows = [
            '%same = phi i32 [ %v, %a ], [ %v, %b ]',
            '%u = phi i32 [ %u, %a ], [ %v, %b ], [ undef, %c ]',
            '%p = phi i32 [ %v, %a ], [ poison, %b ]',
            '%up = phi i32 [ %v, %a ], [ undef, %b ], [ poison, %c ]',
            '%multi = phi i32 [ %v, %a ], [ %other, %b ], [ %third, %c ]',
            '%self = phi i32 [ %self, %a ], [ undef, %b ], [ poison, %c ]',
            '%constant = phi i32 [ 1, %a ], [ 2, %b ]',
            '%aggregate = phi { i32, i32 } [ %v, %a ], [ %other, %b ]',
            '%metadata = phi i32 [ %v, %a ], [ %v, %b ], !dbg !42',
        ]
        def shapes(lines):
            return ir.observe((f'*** IR Dump Before {ir.PASS} ***\n'
                f'define ptr @{ir.FUNCTION}() {{\nentry:\n  ' + '\n  '.join(lines)
                + '\n  %cs = catchswitch within none [label %handler] unwind to caller\n}\n'
                + f'*** IR Dump After {ir.PASS} ***\ndefine ptr @{ir.FUNCTION}() {{\n'
                + 'entry:\n  ret ptr null\n}\n').encode())
        classified = shapes(rows)
        self.assertEqual(classified['status'], 'observed')
        self.assertEqual(classified['snapshots']['before']['catchswitchPhi'], 9)
        view = classified['catchswitchPhiIncomingShapes']
        self.assertEqual(view['phases']['before'], {
            'singleSSAOnly': 1, 'singleSSAWithUndef': 1, 'singleSSAWithPoison': 1,
            'singleSSAWithUndefAndPoison': 1, 'multipleSSA': 1, 'noNonSelfSSA': 1, 'opaque': 3})
        self.assertEqual(sum(view['phases']['after'].values()), 0)
        ir.validate_phi_shapes(view, classified['snapshots'])
        self.assertNotIn('%third', canonical(view).decode())
        separated = shapes(['%ignored = phi i32 [ 0, %a ], [ 1, %b ]',
                            'br label %dispatch', 'dispatch:', *rows])
        self.assertEqual(separated['snapshots']['before']['phi'], 10)
        self.assertEqual(separated['catchswitchPhiIncomingShapes'], view)
        opaque = shapes(['%mixed = phi i32 [ %v, %a ], [ %other, %b ], [ 0, %c ]'])
        self.assertEqual(opaque['catchswitchPhiIncomingShapes']['phases']['before']['opaque'], 1)
        # Byte bounds apply independently to the result and first incoming name.
        for name in ('%' + 'a' * 511, '%"' + '\u00e9' * 254 + '"'):
            self.assertEqual(shapes([f'%out = phi ptr [ {name}, %a ], [ {name}, %b ]'])
                             ['catchswitchPhiIncomingShapes']['phases']['before']['singleSSAOnly'], 1)
            self.assertEqual(shapes([f'{name} = phi ptr [ %v, %a ], [ %v, %b ]'])
                             ['catchswitchPhiIncomingShapes']['phases']['before']['singleSSAOnly'], 1)
        for name in ('%' + 'a' * 512, '%"' + '\u00e9' * 255 + '"'):
            for line in (f'%out = phi ptr [ {name}, %a ], [ {name}, %b ]',
                         f'{name} = phi ptr [ %v, %a ], [ %v, %b ]'):
                bounded = shapes([line])
                self.assertEqual(bounded['status'], 'observed')
                self.assertEqual(bounded['catchswitchPhiIncomingShapes']['phases']['before']['opaque'], 1)
        for bad in (True, 1.0, -1, 10):
            forged = copy.deepcopy(view)
            forged['phases']['before']['singleSSAOnly'] = bad
            with self.assertRaisesRegex(ValueError, 'phi-shape-summary'):
                ir.validate_phi_shapes(forged, classified['snapshots'])
        forged = copy.deepcopy(view); forged['phases']['before']['singleSSAOnly'] = 0
        with self.assertRaisesRegex(ValueError, 'phi-shape-summary'):
            ir.validate_phi_shapes(forged, classified['snapshots'])
        forged = copy.deepcopy(view); forged['maximumRetainedIdentities'] = 2.0
        with self.assertRaisesRegex(ValueError, 'phi-shape-summary'):
            ir.validate_phi_shapes(forged, classified['snapshots'])
        counter = ir.Counter()
        for start in range(0, len(IR), 7):
            counter.feed(IR[start:start + 7])
        self.assertEqual(counter.finish(), value)
        for key, replacement in [('maximumKeys', 8192.0), ('maximumTokenBytes', True)]:
            changed = copy.deepcopy(value['syntacticStorePatterns']); changed[key] = replacement
            with self.assertRaisesRegex(ValueError, 'store-pattern-summary'):
                ir.validate_patterns(changed, value['snapshots'])
        with mock.patch.object(ir, 'MAX_PATTERN_KEYS', 1):
            self.assertEqual(ir.observe(IR)['reason'], 'store-pattern-limit')
        oversized = IR.replace(b'%other,', b'%' + b'a' * 513 + b',')
        self.assertEqual(ir.observe(oversized)['reason'], 'store-pattern-token-limit')

    def test_real_pinned_negative_baseline_and_full_inventory_are_required(self):
        reference = pre.baseline()
        self.assertEqual(reference['source'], 'e782a6e476c6c17783a682718f9cdfe15c9a1d5d')
        self.assertEqual(reference['originalStatus'], 'FAILED-copy-cost-not-improved-before-c-to-wasm')
        self.assertEqual(reference['generatedInventory']['files'], 650)
        generated = {'a.c': {'digest': digest(b'closed synthetic tree'), 'size': 21}}
        identity = {'trees': {'generated': generated}}
        small = {**reference, 'generatedInventory': {'files': 1, 'bytes': 21,
                 'digest': digest(canonical(generated))}}
        value = {'schemaVersion': 'latent.java.public-copy-cost-candidate.v1',
            'qualification': False, 'improved': False, 'reason': 'candidate-not-improved',
            'clangDecision': 'refused-not-invoked', 'shape': reference['shape'],
            'trace': reference['trace'], 'inputIdentity': identity}
        with mock.patch.object(pre, 'baseline', return_value=small):
            pre.require_baseline(value, identity)
            for field, replacement in [('qualification', True), ('improved', 0),
                    ('reason', 'success'), ('clangDecision', 'admitted-pending-original-command'),
                    ('shape', {**reference['shape'], 'poolsBytes': 1}),
                    ('shape', {**reference['shape'], 'poolsBytes': float(reference['shape']['poolsBytes'])}),
                    ('trace', {**reference['trace'], 'newCopiedNodes': 9}),
                    ('trace', {**reference['trace'], 'hookCount': True})]:
                with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'baseline-match'):
                    pre.require_baseline({**value, field: replacement}, identity)
            changed = copy.deepcopy(identity)
            changed['trees']['generated']['unconsumed.h'] = {'digest': digest(b'extra'), 'size': 5}
            with self.assertRaisesRegex(ValueError, 'baseline-match'):
                pre.require_baseline({**value, 'inputIdentity': changed}, changed)
        with mock.patch.object(pre.old.paths, 'read', return_value=b'{}'):
            with self.assertRaisesRegex(ValueError, 'baseline-source'):
                pre.baseline()
        # Drive the real normal prepare facade up to its constructor boundary.
        # All old accepted flag modes keep their original compiler selection;
        # only the newly explicit combination selects the diagnostic subclass.
        from tools import qualify_java_fibers as qualifier
        from tools.java_guest import llvm_ssa_consumer as derived
        class StopBeforeCompiler(Exception):
            pass
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();sdk=root/'sdk';sdk.mkdir()
            for index,(observe,selected_derived,expected) in enumerate(((False,False,'normal'),
                    (True,False,'historical'),(False,True,'derived'),(True,True,'diagnostic'))):
                factories={name:mock.Mock(side_effect=StopBeforeCompiler(name))
                    for name in ('normal','historical','derived','diagnostic')}
                with mock.patch.object(qualifier,'Compiler',factories['normal']), \
                        mock.patch.object(old,'PublicWinEHCompiler',factories['historical']), \
                        mock.patch.object(derived,'CopyCostPublicCompiler',factories['derived']), \
                        mock.patch.object(derived,'CopyCostWinEHDiagnosticCompiler',factories['diagnostic']), \
                        mock.patch.object(derived,'deadline',return_value=time.monotonic()+100), \
                        mock.patch.object(inputs,'prepare',return_value=SimpleNamespace(sdk=sdk)) as acquisition, \
                        self.assertRaises(StopBeforeCompiler):
                    qualifier.prepare(root/str(index),sdk,observe_public_wineh=observe,
                        derived_llvm_public=selected_derived)
                self.assertEqual({name:factory.call_count for name,factory in factories.items()},
                    {name:int(name==expected) for name in factories})
                self.assertEqual(acquisition.call_count,int(selected_derived))

    def fixture(self, root, stack):
        # Exercise the unchanged real R7 carrier/SDK readers on the existing
        # SMALL SYNTHETIC carrier fixture, not an acquired or executable SDK.
        case = carrier_fixtures.LlvmSsaConsumer('runTest')
        self.addCleanup(case.doCleanups)
        archive, pin, own = case.fixture(root)
        stack.enter_context(mock.patch.object(inputs, 'QUALIFIED', pin))
        stack.enter_context(mock.patch.dict(os.environ, {'RUNNER_TEMP': str(root)}))
        directory = root/'java-llvm-public-inputs';directory.mkdir()
        admitted = inputs.decode(archive, directory, time.monotonic()+60)
        output = root/'java-activation-fibers';output.mkdir()
        for target, original in [('src/Capsule.java','Capsule.java'),
                ('build/project/src/main/java/Capsule.java','Capsule.java'),
                ('wit/service.wit','service.wit'),('build/wit/service.wit','service.wit')]:
            path = output/target;path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((ROOT/'sdk/java-guest/fibers/conformance'/original).read_bytes())
        generated = output/'build/project/build/teavm-c/c/c/d/l/a/Capsule.c'
        generated.parent.mkdir(parents=True);generated.write_bytes(b'void* meth_dla_Capsule_pools() {\n    return 0;\n}\n')
        (output/'build/bindings').mkdir()
        (output/'build/bindings/bridge.h').write_bytes(b'closed synthetic binding')
        roots = {'wasi-sdk': admitted.sdk, 'jdk': root/'jdk', 'gradle': root/'gradle'}
        for name in ('jdk','gradle'):
            roots[name].mkdir();(roots[name]/'input').write_bytes(b'never executed')
        compiler = SimpleNamespace(directory=output/'compiler', sdk=ROOT/'sdk/java-guest',
            paths={'clang': admitted.sdk/'bin/clang-21'}, tool_roots=roots,
            environment={'PATH':'closed-test-context'}, materials=[],
            original_sdk=old.sdk_snapshot(ROOT/'sdk/java-guest'), compiler_inputs=old.tool_inventory(roots),
            records=[{'stage':'java-to-c','exitCode':0}], deadline=time.monotonic()+1195)
        compiler.directory.mkdir()
        compiler.check_unchanged=lambda: Compiler.check_unchanged(compiler)
        identity=old.input_identity(compiler,output)
        reference=pre.baseline();reference={**reference,'shape':pre.c_shape(generated.read_bytes()),
            'generatedInventory':{'digest':digest(canonical(identity['trees']['generated'])),
            'files':len(identity['trees']['generated']),
            'bytes':sum(row['size'] for row in identity['trees']['generated'].values())}}
        stack.enter_context(mock.patch.object(pre,'baseline',return_value=reference))
        stack.enter_context(mock.patch.object(pre,'BASELINE',reference['shape']))
        value={'schemaVersion':'latent.java.public-copy-cost-candidate.v1','qualification':False,
            'improved':False,'reason':'candidate-not-improved','clangDecision':'refused-not-invoked',
            'shape':reference['shape'],'trace':reference['trace'],'inputIdentity':identity}
        (compiler.directory/'public-copy-cost-candidate.json').write_bytes(canonical(value))
        source={'repository':inputs.REPOSITORY,'revision':'a'*40,'event':'workflow_dispatch',
            'workflowRef':inputs.REPOSITORY+'/.github/workflows/java-guest-feasibility.yml@refs/heads/'+inputs.CONSUMER_BRANCH,
            'maintainedFiles':{}}
        stack.enter_context(mock.patch.object(old,'hosted_source',return_value=source))
        return compiler,output,identity

    def test_one_owned_diagnostic_child_uses_original_environment_and_never_parent_compile(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            compiler,output,identity=self.fixture(Path(tmp).resolve(),stack)
            calls=[]
            def filtered(command,cwd,environment,**limits):
                calls.append((command,cwd,environment,limits))
                data=io.BytesIO()
                collected={'status':'observed','childStarted':True,'childExitCode':0,
                    'stdoutBytes':0,'stdoutDigest':digest(b''),'stderrBytes':len(IR),'stderrDigest':digest(IR),
                    'rawTransitMaximum':old.RAW_TRANSIT_BUDGET,'observation':ir.observe(IR),'pipeEOFComplete':True}
                with mock.patch.object(pipe.sys,'argv',command[3:]), \
                        mock.patch.object(pipe.sys,'platform','linux'), \
                        mock.patch.dict(os.environ,environment,clear=True), \
                        mock.patch.object(pipe.os,'getpgrp',return_value=1,create=True), \
                        mock.patch.object(pipe.os,'getpid',return_value=1), \
                        mock.patch.object(pipe.os,'getsid',return_value=1,create=True), \
                        mock.patch.object(pipe.Path,'cwd',return_value=cwd), \
                        mock.patch.object(pipe.sys,'stdout',SimpleNamespace(buffer=data)), \
                        mock.patch.object(pipe.subprocess,'Popen',return_value=object()) as spawn, \
                        mock.patch.object(pipe,'collect',return_value=collected):
                    code=pipe.main()
                self.assertEqual(code,0)
                spawn.assert_called_once()
                self.assertEqual(spawn.call_args.kwargs['env'],compiler.environment)
                self.assertNotIn('RUNNER_TEMP',spawn.call_args.kwargs['env'])
                return subprocess.CompletedProcess(command,code,data.getvalue(),b'')
            with mock.patch.object(pre,'run_bounded_result',side_effect=filtered), \
                    mock.patch.object(Compiler,'run') as parent:
                pre.observe(compiler,output,old.expected_command(compiler,output),identity)
            parent.assert_not_called()
            self.assertEqual(len(calls),1)
            self.assertLessEqual(calls[0][3]['timeout_seconds'],595)
            report=json.loads((compiler.directory/pre.RESULT).read_bytes())
            self.assertEqual(report['status'],'observed')
            self.assertFalse(report['qualification'])
            self.assertTrue(report['originalNoImprovement'])
            self.assertFalse(report['ordinaryCToWasmInvoked'])
            self.assertFalse(report['componentNewInvoked'])
            self.assertEqual(report['filter']['observation']['source'],'pinned-llvm-text-only')
            self.assertEqual(compiler.records,[{'stage':'java-to-c','exitCode':0}])
            # Exercise the actual mixin cutpoint too: an observed diagnostic
            # returns no authority and cannot continue into the normal parent.
            from tools.java_guest.copy_cost_observation import PublicCopyCostObservationMixin, ObservationStopped
            parent_calls=[]
            class Parent:
                def run(self,*args,**kwargs):
                    parent_calls.append(args)
                    raise AssertionError('normal parent must never run')
            class Selected(PublicCopyCostObservationMixin,Parent):
                _public_wineh_preclang=True
            selected=Selected.__new__(Selected);selected.__dict__.update(compiler.__dict__)
            selected._observe_public_copy_cost=True;selected._copy_gate_reached=False
            selected._copy_trace=pre.baseline()['trace'];selected._copy_trace_log_digest=digest(IR)
            (compiler.directory/'public-copy-cost-candidate.json').unlink()
            original=old.expected_command(compiler,output)
            with mock.patch.object(pre,'observe') as diagnostic, self.assertRaisesRegex(ObservationStopped,'copy-cost-not-improved'):
                selected.run('c-to-wasm','clang',*original[1:])
            diagnostic.assert_called_once_with(selected,output,original,identity)
            self.assertEqual(parent_calls,[])
            # Even a supposedly improved row cannot escape this diagnostic-only
            # mode into ordinary compilation or a different public baseline.
            (compiler.directory/'public-copy-cost-candidate.json').unlink()
            (compiler.directory/'public-copy-cost-Capsule.c').unlink()
            selected._copy_gate_reached=False
            selected._copy_trace={**selected._copy_trace,'newDecisionSha256':'b'*64}
            with mock.patch.object(pre,'observe') as diagnostic, self.assertRaisesRegex(ObservationStopped,'diagnostic-baseline-mismatch'):
                selected.run('c-to-wasm','clang',*original[1:])
            diagnostic.assert_not_called()
            self.assertEqual(parent_calls,[])

    def test_closed_ticket_refuses_retargeting_extra_flags_tree_or_environment_before_spawn(self):
        with tempfile.TemporaryDirectory() as tmp, ExitStack() as stack:
            compiler,output,identity=self.fixture(Path(tmp).resolve(),stack)
            with mock.patch.object(pre,'run_bounded_result',side_effect=RuntimeError('closed fixture stop')):
                pre.observe(compiler,output,old.expected_command(compiler,output),identity)
            ticket_path=output/'build/wineh-observer/request.json';raw=ticket_path.read_bytes()
            environment={**compiler.environment,'RUNNER_TEMP':str(output.parent)}
            old.load_ticket(output,digest(raw).removeprefix('sha256:'),environment,deadline=time.monotonic()+30)
            for kind in ('extra-field','extra-flag','normal-ticket','tree','environment','compiler-receipt','numeric','duplicate'):
                ticket_path.write_bytes(raw);value=json.loads(raw);env=dict(environment)
                if kind=='extra-field':value['arbitrary']=True
                elif kind=='extra-flag':value['diagnosticCommand'].append('-O0')
                elif kind=='normal-ticket':value['schemaVersion']=old.TICKET_SCHEMA
                elif kind=='tree':
                    path=output/'build/project/build/teavm-c/c/extra.h';path.write_bytes(b'no unbound member')
                elif kind=='environment':env['UNREVIEWED']='context'
                elif kind=='numeric':value['gateRecord']['bytes']=float(value['gateRecord']['bytes'])
                elif kind=='compiler-receipt':(compiler.directory/'36-c-to-wasm.command.json').write_bytes(b'{}')
                changed=canonical(value)
                if kind=='duplicate':changed=changed[:-1]+b',\"output\":'+canonical(str(output))+b'}'
                ticket_path.write_bytes(changed)
                with self.subTest(kind=kind),mock.patch.object(pipe.subprocess,'Popen') as spawn, \
                        self.assertRaises(ValueError):
                    old.load_ticket(output,digest(changed).removeprefix('sha256:'),env,deadline=time.monotonic()+30)
                spawn.assert_not_called()
                if kind=='tree':path.unlink()
                if kind=='compiler-receipt':(compiler.directory/'36-c-to-wasm.command.json').unlink()

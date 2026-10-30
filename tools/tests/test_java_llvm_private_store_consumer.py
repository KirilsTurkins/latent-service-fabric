"""Closed R8 admission and normal-parent routing; no compiler execution."""
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest import mock

from tools import qualify_java_fibers as fibers
from tools.java_guest import llvm_private_store_consumer as consumer
from tools.java_guest import llvm_private_store_inputs as inputs
from tools.java_guest import wineh_preclang
from tools.java_guest.copy_cost_observation import c_shape, FUNCTION
from tools.rust_capsule_project import canonical, digest
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.ci_lane_inventory import workflow_model


class PrivateScalarConsumer(unittest.TestCase):
    def test_unfilled_new_tuple_and_mixed_modes_refuse_before_io_or_old_sdk_fallback(self):
        with mock.patch.multiple(inputs, QUALIFIED=None, HEAD=None, TREE=None, RUN=None, JOB=None):
            self.assertIsNone(inputs.QUALIFIED)
            self.assertIsNone(inputs.HEAD)
            self.assertIsNone(inputs.RUN)
            with mock.patch.object(inputs.io, 'fresh') as fresh, mock.patch.object(inputs, '_response') as network:
                with self.assertRaisesRegex(ValueError, 'qualified-tuple-unfilled'):
                    inputs.prepare(time.monotonic() + 10)
                fresh.assert_not_called()
                network.assert_not_called()
        for selection in ({'derived_llvm_public': True}, {'observe_public_wineh': True}, {'fixture': 'timers'}):
            with self.subTest(selection=selection), mock.patch.object(fibers, 'fresh') as fresh:
                with self.assertRaisesRegex(ValueError, 'distinct fixed public backend'):
                    fibers.prepare(Path('not-created'), Path('not-read'), private_scalar_llvm_public=True, **selection)
                fresh.assert_not_called()
        workflow = workflow_model((inputs.patch.ROOT / '.github/workflows/java-guest-feasibility.yml').read_text())
        script = '\n'.join(workflow['jobs']['public-fiber-assembly']['steps'][0]['run'].splitlines()[1:-1])
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for ordinal, (private, derived, public, accepted) in enumerate([
                    ('true', 'false', 'true', True), ('false', 'false', 'true', True),
                    ('true', 'true', 'true', False), ('true', 'false', 'false', False),
                    ('True', 'false', 'true', False), ('unknown', 'false', 'true', False)]):
                env = build_environment(root)
                target = root / (str(ordinal) + '.env')
                env.update(PUBLIC_FIBER_ASSEMBLY=public, PUBLIC_FIBER_DERIVED_LLVM=derived,
                           PUBLIC_FIBER_PRIVATE_SCALAR_LLVM=private, QUALIFY_SCRATCH_REFUSALS='false',
                           JAVA_HTTP_SPI='false', GITHUB_ENV=str(target), GITHUB_EVENT_NAME='workflow_dispatch',
                           GITHUB_REF='refs/heads/' + inputs.CONSUMER_BRANCH)
                result = run_bounded_result([sys.executable, '-B', '-c', script], root, env,
                                           timeout_seconds=5, max_output_bytes=4096)
                self.assertEqual(result.returncode == 0, accepted)
                self.assertEqual(target.exists(), accepted and private == 'true')

    def test_full_generated_inventory_and_c_baseline_are_required_without_copy_cost_policy(self):
        raw = FUNCTION + b'    return;\n}\n'
        shape = c_shape(raw)
        rows = {'c/d/l/a/Capsule.c': {'size': len(raw), 'digest': digest(raw)},
                'all.c': {'size': 10, 'digest': digest(b'inventory')}}
        reference = {'source': {'head': 'fixture'}, 'shape': shape, 'generatedInventory': {
            'files': 2, 'bytes': len(raw) + 10, 'digest': digest(canonical(rows))}}
        identity = {'trees': {'generated': rows}}
        with mock.patch.object(wineh_preclang, 'baseline', return_value=reference):
            actual = consumer.backend_baseline(identity, raw)
            self.assertTrue(actual['unchangedPublicCExpected'])
            self.assertEqual(actual['componentAcceptance'], 'pending-normal-command')
            for changed in [raw + b'\n', raw.replace(b'return', b'other_')]:
                with self.assertRaisesRegex(ValueError, 'public-baseline'):
                    consumer.backend_baseline(identity, changed)
            with self.assertRaisesRegex(ValueError, 'public-baseline'):
                consumer.backend_baseline({'trees': {'generated': {'c/d/l/a/Capsule.c': rows['c/d/l/a/Capsule.c']}}}, raw)
            # The historical gate still rejects the unchanged public candidate;
            # the distinct backend gate never upgrades that negative record.
            with self.assertRaisesRegex(ValueError, 'baseline-match'):
                wineh_preclang.require_baseline({'improved': True}, identity)
        sealed = wineh_preclang.baseline()
        self.assertEqual((sealed['generatedInventory']['files'], sealed['shape']['sourceBytes']), (650, 733980))

    def test_one_normal_parent_clang_and_component_required_with_cleanup_inside_bounds(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            compiler = consumer.PrivateScalarPublicCompiler.__new__(consumer.PrivateScalarPublicCompiler)
            compiler.directory = output / 'compiler'
            compiler.wasi_sdk = output / 'toolchain'
            compiler.paths = {'clang': compiler.wasi_sdk / 'bin/clang'}
            compiler.records = []
            compiler._compile_selected, compiler._clang_requested = False, False
            compiler._public_inputs = compiler._backend_gate = None
            compiler._derived = mock.Mock()
            compiler._derived.own = {'products': {'derivedVersion': ['source fixture only']}}
            compiler._owner_deadline = compiler.deadline = time.monotonic() + 1195
            java = (inputs.patch.ROOT / 'sdk/java-guest/fibers/conformance/Capsule.java').read_bytes()
            wit = (inputs.patch.ROOT / 'sdk/java-guest/fibers/conformance/service.wit').read_bytes()
            (output / 'src').mkdir()
            (output / 'wit').mkdir()
            (output / 'src/Capsule.java').write_bytes(java)
            (output / 'wit/service.wit').write_bytes(wit)
            self.assertFalse((output / 'build').exists())
            def parent_compile(instance, sources, selected_wit, world, destination, **options):
                self.assertFalse(destination.exists())
                self.assertEqual((sources, selected_wit, world, destination, options),
                    (output / 'src', output / 'wit', 'tests:caller/service@1.0.0', output / 'build',
                     {'activation_profile': True}))
                # A pure stage-order fixture, not TeaVM generation or compiler credit.
                staged = destination / 'project/src/main/java/Capsule.java'
                staged.parent.mkdir(parents=True)
                staged.write_bytes(java)
                (destination / 'wit').mkdir()
                (destination / 'wit/service.wit').write_bytes(wit)
                return 'parent source-staging fixture'
            with mock.patch.object(consumer.Compiler, 'compile', parent_compile):
                self.assertEqual(compiler.compile(output / 'src', output / 'wit',
                    'tests:caller/service@1.0.0', output / 'build', activation_profile=True),
                    'parent source-staging fixture')
            self.assertTrue(compiler._compile_selected)
            command = [str(compiler.paths['clang']), 'original-normal-argv']
            identity = {'actual': 'bounded public source fixture'}
            original_read = consumer.public_wineh.paths.read
            def read_source(root, name, maximum):
                if name == consumer.GENERATED_C:
                    return b'public C'
                return original_read(root, name, maximum)
            def parent_run(instance, stage, tool, *argv, cwd=None):
                self.assertEqual(full_source_check.call_count, 1)
                self.assertLessEqual(instance.deadline - time.monotonic(), 595)
                self.assertEqual((stage, tool, argv, cwd), ('c-to-wasm', 'clang', ('original-normal-argv',), None))
                instance.records.append({'stage': stage, 'exitCode': 0})
                return 'actual parent fixture result'
            with mock.patch.object(consumer.public_wineh, 'expected_command', return_value=command), \
                    mock.patch.object(consumer.public_wineh, 'public_sources',
                                      wraps=consumer.public_wineh.public_sources) as full_source_check, \
                    mock.patch.object(consumer.public_wineh, 'input_identity', return_value=identity), \
                    mock.patch.object(consumer.public_wineh.paths, 'read', side_effect=read_source), \
                    mock.patch.object(consumer, 'backend_baseline', return_value={'pending': True}), \
                    mock.patch.object(consumer.Compiler, 'run', parent_run):
                absolute = compiler.deadline
                self.assertEqual(compiler.run('c-to-wasm', 'clang', 'original-normal-argv'), 'actual parent fixture result')
                self.assertEqual(compiler.deadline, absolute)
                with self.assertRaisesRegex(ValueError, 'one-clang'):
                    compiler.run('c-to-wasm', 'clang', 'original-normal-argv')
            with mock.patch.object(compiler, 'check_unchanged'):
                with self.assertRaisesRegex(ValueError, 'actual-component-required'):
                    compiler.qualification_record()
                compiler.records += [{'stage': 'component-new', 'exitCode': 1}]
                with self.assertRaisesRegex(ValueError, 'actual-component-required'):
                    compiler.qualification_record()
                compiler.records[-1] = {'stage': 'component-new', 'exitCode': 0}
                with mock.patch.object(inputs, 'pinned', return_value={'fixture': 'not an admission'}):
                    record = compiler.qualification_record()
                    self.assertFalse(record['componentRuntimeQualification'])
                    self.assertEqual(record['nodeExecution'], 'not-run')
                compiler.records.append({'stage': 'component-new', 'exitCode': 0})
                with self.assertRaisesRegex(ValueError, 'actual-component-required'):
                    compiler.qualification_record()


if __name__ == '__main__':
    unittest.main()

"""Bounded fixture and retained-input controls; JVM execution is a separate step."""
import os
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import qualify_java_checkpoint_context as probe
from tools.phase2_operator_process import WorkflowError


class CheckpointCompiler(unittest.TestCase):
    def test_real_frontend_fixture_matches_production_preparation_and_has_no_codegen(self):
        source = probe.COMPILER_CONTROL.read_text()
        self.assertIn('new PreOptimizingClassHolderSource(new ClasspathClassHolderSource(', source)
        self.assertIn('vm.installPlugins();', source)
        self.assertIn('vm.setOptimizationLevel(TeaVMOptimizationLevel.FULL);', source)
        self.assertIn('new CTarget(new CNameProvider())', source)
        self.assertIn('vm.setProgressListener(stop);', source)
        self.assertIn('asyncMethods.get(target) != null', source)
        self.assertIn('checkpoint-control-real-c-analysis-completed', source)
        self.assertIn('checkpoint-control-must-not-generate-code', source)
        self.assertIn('checkpoint-control-mutation-was-applied', source)
        self.assertIn('getSevereProblems().isEmpty()', source)
        self.assertNotIn('printStackTrace', source)
        self.assertIn('"' + probe.COMPILER_EXPECTED + '"', source)
        self.assertEqual(probe.COMPILER_EXPECTED.split(';')[1:], [
            'finite', 'initializer', 'unmanaged', 'managed', 'recursion',
            'runtime-initializer', 'class-object-helper', 'string-copy-body',
            'finite-unmanaged', 'nested-counted', 'changing-bound', 'wrapping-counted',
            'reset-counted', 'exceptional-retry', 'unmanaged-class', 'transitive-initializer',
            'near-max-counted', 'nested-polling', 'mutual-recursion', 'virtual-initializer',
            'string-info-getter', 'string-info-declaration', 'string-info-parent', 'string-info-target',
            'class-info-enum-count', 'class-info-enum-other-refused', 'class-info-declaration',
            'class-info-parent', 'class-info-layout', 'class-info-target', 'class-info-header-shadow',
            'compiler-archive-control', 'compiler-cache-isolation'])

    def test_real_frontend_executes_every_declared_progress_case(self):
        source = probe.COMPILER_CONTROL.read_text()
        cases = re.findall(r'check\((\w+)\.class\.getName\(\), corrected, (false|true), ""\);', source)
        self.assertEqual(cases, [
            ('Finite', 'false'), ('InitializerPolling', 'true'), ('UnmanagedPolling', 'true'),
            ('ManagedPolling', 'false'), ('RecursiveInitializer', 'true'),
            ('FiniteUnmanaged', 'false'), ('NestedCounted', 'false'), ('ChangingBound', 'false'),
            ('WrappingCounted', 'true'), ('ResetCounted', 'true'), ('ExceptionalRetry', 'true'),
            ('UnmanagedClassPolling', 'true'), ('TransitiveInitializer', 'true'),
            ('NearMaxCounted', 'false'), ('NestedPolling', 'true'), ('MutualRecursion', 'true'),
            ('VirtualInitializer', 'true'), ('StringInfoAccess', 'false'),
            ('ClassInfoEnumCountAccess', 'false'), ('ClassInfoEnumElementAccess', 'true')])
        self.assertIn('new String[] { "runtime-initializer", "class-object-helper", "string-copy-body" }', source)
        self.assertIn('check(Finite.class.getName(), corrected, true, mutation);', source)
        self.assertIn('new String[] { "string-info-declaration", "string-info-parent" }', source)
        self.assertIn('check(StringInfoAccess.class.getName(), corrected, true, mutation);', source)
        self.assertIn('check(StringInfoAccess.class.getName(), corrected, true, "", true);', source)
        self.assertIn('new String[] { "class-info-declaration", "string-info-parent", "class-info-layout" }', source)
        self.assertIn('check(ClassInfoEnumCountAccess.class.getName(), corrected, true, mutation);', source)
        self.assertIn('check(ClassInfoEnumCountAccess.class.getName(), corrected, true, "", true);', source)
        self.assertIn('checkClassInfoHeader(corrected);', source)
        self.assertIn('checkpoint-control-class-info-shadow-header-refused', source)
        self.assertIn('checkCompilerArchive(corrected);', source)
        self.assertIn('checkCompilerCacheIsolation(corrected);', source)
        self.assertEqual(len(cases) + 13, len(probe.COMPILER_EXPECTED.split(';')) - 1)

    def test_enum_count_proof_binds_exact_emitter_and_loader_header(self):
        from tools.java_guest import coroutine_patch
        emitted = coroutine_patch.corrected_async_source(
            (probe.SDK/'fibers/compiler-patch/AsyncMethodFinder.java').read_bytes()).decode()
        self.assertIn('case "enumConstantCount":', emitted)
        self.assertIn('pinnedClassMetadataMethod(method) && pinnedClassInfoCompiler()', emitted)
        self.assertIn('Class.forName(emitterName, false, targetClass.getClassLoader()) != emitter', emitted)
        self.assertIn('loader.getResourceAsStream("org/teavm/backend/c/core.h")', emitted)
        self.assertIn('3e0b5c2bdbc3fdcd61241fe02b8fa3710adb39e54e8cad0c9710a6a69e265ce6', emitted)
        self.assertIn('!((org.teavm.model.lowlevel.Characteristics) traits).isFunction(owner)', emitted)
        source = probe.COMPILER_CONTROL.read_text()
        self.assertIn('"org/teavm/backend/c/intrinsic/reflection/ClassInfoIntrinsic.class"', source)
        self.assertIn('"org/teavm/backend/c/core.h"', source)
        self.assertIn('checkpoint-control-class-info-shadow-header-refused', source)

    def test_archive_receipt_is_per_compiler_even_when_target_is_reused(self):
        from tools.java_guest import coroutine_patch
        emitted = coroutine_patch.corrected_async_source(
            (probe.SDK/'fibers/compiler-patch/AsyncMethodFinder.java').read_bytes()).decode()
        body = emitted.split('synchronized (progressStringInfoArchives) {', 1)[1].split(
            '// FunctionIntrinsic', 1)[0]
        self.assertIn('progressStringInfoArchives.get(vm)', body)
        self.assertIn('progressStringInfoArchives.put(vm, false)', body)
        self.assertIn('progressStringInfoArchives.put(vm, result)', body)
        self.assertNotIn('progressStringInfoArchives.get(target)', body)
        fixture = probe.COMPILER_CONTROL.read_text()
        self.assertIn('cache.put(first, Boolean.FALSE);', fixture)
        self.assertIn('Boolean.TRUE.equals(cache.get(second))', fixture)
        self.assertEqual(fixture.count(
            'compileWithTarget(StringInfoAccess.class.getName(), corrected, false, "", target)'), 2)

    def test_real_frontend_preserves_strict_rank_and_excluded_call_controls(self):
        source = probe.COMPILER_CONTROL.read_text()
        self.assertIn('index = Integer.MAX_VALUE - 2; index < Integer.MAX_VALUE;', source)
        self.assertIn('index = Integer.MAX_VALUE; index <= limit;', source)
        self.assertIn('limit = (index & 1) + 4;', source)
        self.assertIn('catch (ArithmeticException retry)', source)
        self.assertIn('@Unmanaged\n    public static final class UnmanagedClassPolling', source)
        self.assertIn('read(new PollingSupplier())', source)
        self.assertNotIn('Activation.checkpoint', source)

    def test_monitor_fixture_keeps_every_reachable_method_in_progress_analysis(self):
        source = probe.MONITOR_CONTROL.read_text()
        self.assertIn('require(reachable.contains(method), "unmodeled-method-query");', source)
        self.assertIn('progressQueries.add(method);', source)
        self.assertIn('inputs.progressQueries.equals(mode.equals("corrected") ? inputs.reachable : Set.of())', source)
        self.assertIn('"final-reachable-progress-query-coverage"', source)
        self.assertNotIn('new MethodDependencyInfo', source)
        self.assertIn('"monitor-suspension-boundary"', source)
        self.assertIn('"real-monitor-family-closure"', source)

    def test_fast_qualification_runs_and_retains_both_production_monitor_controls(self):
        source = Path(probe.__file__).read_text()
        self.assertIn('CONTROL, COMPILER_CONTROL, MONITOR_CONTROL, CLASSLOADER_CONTROL, raw_finder', source)
        self.assertIn("'-d', model, *sources, CONTROL, COMPILER_CONTROL, MONITOR_CONTROL, CLASSLOADER_CONTROL)", source)
        self.assertIn("commands.run('checkpoint-monitor-'+mode,", source)
        self.assertIn("'org.teavm.dependency.MonitorAsyncControl', mode)", source)
        self.assertIn("'java-checkpoint-monitor-control'", source)
        self.assertIn('monitorControls=monitor_results', source)
        self.assertIn('monitor_results.append(monitor_result)', source)

    def test_classlib_proof_uses_the_explicit_loader_and_authenticates_before_initialization(self):
        from tools.java_guest import coroutine_patch
        source = coroutine_patch.corrected_async_source(
            (probe.SDK/'fibers/compiler-patch/AsyncMethodFinder.java').read_bytes()).decode()
        self.assertNotIn('new org.teavm.classlib.', source)
        self.assertIn('ClassLoader loader = dependency.getClassLoader();', source)
        self.assertIn('Class.forName(name, false, loader)', source)
        self.assertIn('depth < 64', source)
        self.assertNotIn('getContextClassLoader()', source)
        self.assertIn('progressClasslibTypes.clear();', source)
        helper = source.split('private Class<?> progressClasslibType(', 1)[1].split(
            'private final java.util.Map<String, org.teavm.model.ClassHolder>', 1)[0]
        lock = json.loads((probe.SDK/'feasibility/dependencies.lock.json').read_bytes())
        row, = [row for row in lock['artifacts'] if row['path'].endswith('/teavm-classlib-0.15.0.jar')]
        self.assertIn('Files.size(jar) != '+str(row['size']), helper)
        self.assertIn('input.readNBytes('+str(row['size']+1)+')', helper)
        self.assertIn(row['sha256'], helper)
        self.assertLess(helper.index(row['sha256']), helper.index('progressClasslibTypes.put(name, host)'))
        self.assertNotIn('newInstance', helper)
        runtime_inventory = source.split('private String progressRuntimeClassIdentity(', 1)[1].split(
            'private String[] progressRuntimeClassNames()', 1)[0]
        for name in ('PlatformMarkerSupport', 'ClasslibSubstitutionPolicy', 'DefaultStringTransformer'):
            self.assertIn(name, helper)
            self.assertNotIn(name, runtime_inventory)

    def test_split_loader_control_runs_the_real_frontend_and_same_size_archive_negative(self):
        source = probe.CLASSLOADER_CONTROL.read_text()
        self.assertIn('ClassLoader.getPlatformClassLoader()', source)
        self.assertIn('"checkpoint-classloader-jcl-not-in-parent"', source)
        self.assertIn('"checkpoint-classloader-finder-owned-by-parent"', source)
        self.assertIn('fixture.getMethod("main", String[].class).invoke', source)
        self.assertIn('fixture.getMethod("checkClasslibIdentity", String.class).invoke', source)
        self.assertIn('bytes[10] ^= 1;', source)
        self.assertIn('Thread.currentThread().setContextClassLoader(previous);', source)
        self.assertIn('Files.deleteIfExists(altered);', source)
        self.assertIn('check(Finite.class.getName(), mode.equals("corrected"), true, "");',
            probe.COMPILER_CONTROL.read_text())
        runner = Path(probe.__file__).read_text()
        self.assertIn("commands.run('checkpoint-classloader-'+mode,", runner)
        self.assertIn('classloaderControls=classloader_results', runner)
        self.assertIn('classloader_results.append', runner)
        self.assertIn('MONITOR_CONTROL, CLASSLOADER_CONTROL, raw_finder', runner)
        self.assertIn("'java-checkpoint-classloader-control'", runner)

    def test_retained_inputs_are_deterministic_and_exclude_unselected_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            selected = root/'control.java'; selected.write_bytes(b'fixed control')
            generated = root/'generated.java'; generated.write_bytes(b'fixed generated finder')
            jar = root/'core.jar'; jar.write_bytes(b'fixed locked jar')
            (root/'unselected.txt').write_bytes(b'not a compiler input')
            records = []
            for name in ('first', 'second'):
                output = root/name
                (output/'commands/logs').mkdir(parents=True)
                with patch.object(probe, 'ROOT', root):
                    records.append(probe.retain_compiler_inputs(output, str(jar), [selected], generated))
                with zipfile.ZipFile(output/'commands/logs/compiler-inputs.zip') as archive:
                    self.assertEqual(set(archive.namelist()), {
                        'control.java', 'generated/AsyncMethodFinder.java', 'jars/core.jar'})
                    self.assertEqual(archive.read('control.java'), b'fixed control')
                    self.assertEqual(archive.read('generated/AsyncMethodFinder.java'), b'fixed generated finder')
                    self.assertEqual(archive.read('jars/core.jar'), b'fixed locked jar')
            self.assertEqual(records[0], records[1])
            self.assertEqual((root/'first/commands/logs/compiler-inputs.zip').read_bytes(),
                (root/'second/commands/logs/compiler-inputs.zip').read_bytes())
            self.assertEqual(selected.read_bytes(), b'fixed control')
            self.assertEqual(jar.read_bytes(), b'fixed locked jar')

    def test_retained_inputs_refuse_duplicate_jar_names_before_writing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root/'out'
            (output/'commands/logs').mkdir(parents=True)
            with patch.object(probe, 'ROOT', root), self.assertRaisesRegex(WorkflowError, 'duplicate'):
                probe.retain_compiler_inputs(output,
                    os.pathsep.join(map(str, (root/'a/core.jar', root/'b/core.jar'))), [], root/'generated.java')
            self.assertFalse((output/'commands/logs/compiler-inputs.zip').exists())

    def test_retained_inputs_refuse_excess_entries_before_reading(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch.object(probe, 'ROOT', root), patch.object(probe, 'read_file') as read:
                with self.assertRaisesRegex(WorkflowError, 'entry-bound'):
                    probe.retain_compiler_inputs(root, str(root/'core.jar'),
                        [root/f'control-{index}.java' for index in range(64)], root/'generated.java')
                read.assert_not_called()


if __name__ == '__main__':
    unittest.main()

"""Finite source/acquisition controls, not execution of the hosted JVM probe."""
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from tools import qualify_java_checkpoint_context as probe
from tools.java_guest import coroutine_patch
from tools.phase2_operator_process import WorkflowError


class CheckpointContext(unittest.TestCase):
    def test_pinned_source_is_reversibly_changed_at_final_find_without_new_replacement_classes(self):
        raw = (probe.SDK/'fibers/compiler-patch/AsyncMethodFinder.java').read_bytes()
        fixed = coroutine_patch.corrected_async_source(raw).decode()
        self.assertEqual(fixed.replace(coroutine_patch.CHECKPOINT_VALIDATION, '').replace(
            coroutine_patch.CHECKPOINT_FIND_AFTER, coroutine_patch.CHECKPOINT_FIND_BEFORE).replace(
            coroutine_patch.ASYNC_AFTER, coroutine_patch.ASYNC_BEFORE), raw.decode())
        self.assertLess(fixed.index('validateCheckpointCallers();'), fixed.index('hasAsyncMethods = findAsyncMethods();'))
        self.assertLess(fixed.index('validateCheckpointCallers();'), fixed.index('validateNonsuspendableProgress();'))
        self.assertLess(fixed.index('validateNonsuspendableProgress();'), fixed.index('hasAsyncMethods = findAsyncMethods();'))
        self.assertEqual(len(coroutine_patch.PATCH_CLASSES), 13)
        self.assertEqual(len(coroutine_patch.ASYNC_CLASSES), 3)
        self.assertNotIn('asyncMethods', coroutine_patch.CHECKPOINT_VALIDATION.split('MethodReference checkpoint', 1)[1])
        self.assertIn('pending.size() == 65536', fixed)
        self.assertEqual(fixed.count('++edges > 262144'), 2)
        self.assertIn('method.getLevel() == org.teavm.model.AccessLevel.PRIVATE', fixed)
        self.assertIn('!method.hasModifier(ElementModifier.STATIC)', fixed)
        self.assertIn('!pinnedFiberEntry(method)', fixed)
        self.assertIn('!jar.equals(finderJar)', fixed)
        self.assertIn('first.getClass() != second.getClass()', fixed)
        self.assertIn('first instanceof org.teavm.model.instructions.EmptyInstruction', fixed)
        self.assertIn('!block.readTryCatchBlocks().isEmpty()', fixed)
        with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-async-finder-source'):
            coroutine_patch.corrected_async_source(raw+b'\n')

    def test_nested_handler_reference_backup_is_exact_reversible_upstream_backport(self):
        raw = (probe.SDK/'fibers/compiler-patch/VolatileDefinitionFinder.java').read_bytes()
        fixed = coroutine_patch.corrected_volatile_source(raw).decode()
        restored = fixed.replace(coroutine_patch.VOLATILE_AFTER,
            coroutine_patch.VOLATILE_BEFORE)
        for name in ('IntHashSet', 'IntSet'):
            restored = restored.replace('import org.teavm.hppc.' + name + ';',
                'import com.carrotsearch.hppc.' + name + ';')
        self.assertEqual(restored.encode(), raw)
        self.assertEqual(fixed.count('for (var outerTryCatch : outerTryCatches)'), 1)
        self.assertIn('definitionsToBackupOnEntry.computeIfAbsent(outerTryCatch', fixed)
        self.assertEqual(coroutine_patch.VOLATILE_CLASSES & coroutine_patch.PATCH_CLASSES,
            coroutine_patch.VOLATILE_CLASSES)
        self.assertIn(coroutine_patch.VOLATILE_ROOT + 'VolatileDefinitionFinder$1.class',
            coroutine_patch.PATCH_CLASSES)
        with self.assertRaisesRegex(ValueError, 'unreviewed-teavm-volatile-definition-source'):
            coroutine_patch.corrected_volatile_source(raw+b'\n')

    def test_selected_model_jars_require_exact_lock_metadata_names_and_finite_total(self):
        lock = json.loads((probe.SDK/'feasibility/dependencies.lock.json').read_bytes())
        rows = probe.selected(lock)
        self.assertEqual({Path(row['path']).parts[-3] for row in rows}, probe.NAMES)
        self.assertEqual(len(rows), 15)
        analyzer_dependencies = {'teavm-extension-apis', 'teavm-extension-spi-util',
            'teavm-metaprogramming-api', 'teavm-relocated-libs-asm-util', 'teavm-relocated-libs-rhino'}
        self.assertTrue(analyzer_dependencies <= {Path(row['path']).parts[-3] for row in rows})
        for name in sorted(analyzer_dependencies):
            changed = copy.deepcopy(lock)
            changed['artifacts'] = [r for r in changed['artifacts'] if Path(r['path']).parts[-3] != name]
            with self.subTest(missing_analyzer_runtime=name), self.assertRaises(ValueError): probe.selected(changed)
        for mutation in ('digest', 'missing', 'registry'):
            changed = copy.deepcopy(lock)
            if mutation == 'digest': changed['artifacts'][0]['sha256'] = '0'*64
            elif mutation == 'missing': changed['artifacts'] = [r for r in changed['artifacts'] if r != rows[0]]
            else: changed['maven'] = 'https://example.invalid/'
            with self.subTest(mutation=mutation), self.assertRaises(ValueError): probe.selected(changed)

    def test_acquisition_rejects_redirect_digest_length_and_expired_deadline_without_installing(self):
        raw = b'explicit-locked-jar-fixture'
        row = {'path':'org/teavm/core/0/core-0.jar','size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
        lock = {'maven':'https://repo.maven.apache.org/maven2/'}
        url = lock['maven']+row['path']
        for mutation in ('redirect', 'digest', 'length', 'deadline'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temporary:
                response = io.BytesIO(raw+b'!' if mutation == 'length' else raw)
                response.geturl = lambda: 'https://example.invalid/' if mutation == 'redirect' else url
                changed = dict(row, sha256='0'*64) if mutation == 'digest' else row
                with patch.object(probe, 'selected', return_value=[changed]), patch.object(
                        probe.urllib.request, 'urlopen', return_value=response) as network:
                    with self.assertRaises(WorkflowError): probe.acquire(Path(temporary), lock,
                        time.monotonic()+(-1 if mutation == 'deadline' else 60))
                    if mutation == 'deadline': network.assert_not_called()
                self.assertEqual(list(Path(temporary).rglob('*.jar')), [])

    def test_correct_jar_has_one_canonical_cache_identity_and_real_probe_declares_no_native_route(self):
        raw = b'explicit-locked-jar-fixture'
        sha = hashlib.sha256(raw).hexdigest()
        row = {'path':'org/teavm/core/0/core-0.jar','size':len(raw),'sha256':sha}
        lock = {'maven':'https://repo.maven.apache.org/maven2/'}
        response = io.BytesIO(raw);response.geturl = lambda: lock['maven']+row['path']
        with tempfile.TemporaryDirectory() as temporary, patch.object(probe, 'selected', return_value=[row]), \
                patch.object(probe.urllib.request, 'urlopen', return_value=response):
            root = Path(temporary)
            probe.acquire(root, lock, time.monotonic()+60)
            self.assertEqual((root/'org.teavm/core/0'/sha/'core-0.jar').read_bytes(), raw)
        control = probe.CONTROL.read_text()
        self.assertIn('new PreciseDependencyAnalyzer(', control)
        self.assertIn('agent.submitMethod(bridge, program(HELPER));', control)
        self.assertIn('for (String name : inputs.source.getClassNames()) analyzer.linkClass(name);', control)
        self.assertIn('!agent.getReachableMethods().contains(CHECKPOINT)', control)
        self.assertLess(control.index('analyzer.processDependencies();'),
            control.index('new AsyncMethodFinder(analyzer.getCallGraph(), analyzer).find(linked);'))
        self.assertIn('getVirtualCallSite()', control)
        self.assertIn('actual-selected-finder-origin', control)

    def test_probe_overlay_keeps_all_original_nonreplacement_bytes_and_refuses_incomplete_classes(self):
        import zipfile
        entries = {name: b'original:'+name.encode() for name in coroutine_patch.PATCH_CLASSES}
        entries.update({'org/teavm/runtime/Fiber.class': b'explicit-original-Fiber-fixture',
            'unrelated.class': b'original-unrelated-fixture'})
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original, classes, target = root/'core.jar', root/'classes', root/'selected.jar'
            classes.mkdir()
            with zipfile.ZipFile(original, 'x') as jar:
                for name, data in entries.items(): jar.writestr(name, data)
            before = original.read_bytes()
            for name in coroutine_patch.ASYNC_CLASSES:
                path = classes/name;path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'\xca\xfe\xba\xbe' + name.encode())
            receipt = probe.overlay(original, classes, target)
            with zipfile.ZipFile(target) as jar:
                self.assertEqual(set(jar.namelist()), set(entries))
                for name, data in entries.items():
                    self.assertEqual(jar.read(name), (classes/name).read_bytes()
                        if name in coroutine_patch.ASYNC_CLASSES else data)
            self.assertEqual(original.read_bytes(), before)
            self.assertEqual(receipt['unchangedEntries'], len(entries)-3)
            self.assertEqual(receipt['unchangedFiberClass']['sha256'],
                hashlib.sha256(entries['org/teavm/runtime/Fiber.class']).hexdigest())
            (classes/sorted(coroutine_patch.ASYNC_CLASSES)[0]).unlink()
            with self.assertRaisesRegex(WorkflowError, 'overlay-class-closure'):
                probe.overlay(original, classes, root/'refused.jar')
            self.assertFalse((root/'refused.jar').exists())


if __name__ == '__main__':
    unittest.main()

"""Closed standard Java boundary admission; component execution is separate."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.java_guest import filesystem
from tools.java_guest.compiler import sdk_snapshot
from tools.java_capsule_build import RECIPE
from tools.rust_capsule_project import ROOT, digest
from tools import sdk_scratch_probe
from tools.sdk_scratch_fixture import project
from tools.tests.test_sdk_scratch_probe import invocation


class JavaClosedFilesystem(unittest.TestCase):
    def test_actual_locked_backend_and_classlib_publish_no_filesystem_authority(self):
        record = filesystem.stage(ROOT / 'sdk/java-guest')
        self.assertEqual(record['originalArtifacts'], list(filesystem.PREIMAGES))
        self.assertEqual(record['refusedMethods'], ['getUserDir', 'getFile'])
        self.assertFalse(record['targetIsWindows'])
        for key in ('publicIoWrappersReplaced', 'resourceStreamsChanged', 'filesystemImportsAdded',
                    'writableScratchImplemented', 'componentExecutionQualifiedByThisRecord'):
            self.assertIs(record[key], False)
        self.assertEqual(record['sourceDigest'], digest((ROOT / 'sdk/java-guest' / filesystem.SOURCE).read_bytes()))

    def test_wrong_revision_digest_size_and_duplicate_preimage_fail_before_profile_publication(self):
        for index in range(2):
            for mutation in ('path', 'sha256', 'size', 'duplicate'):
                rows = copy.deepcopy(list(filesystem.PREIMAGES))
                if mutation == 'duplicate': rows.append(copy.deepcopy(rows[index]))
                elif mutation == 'size': rows[index]['size'] += 1
                else: rows[index][mutation] = 'foreign'
                with self.subTest(index=index, mutation=mutation), \
                        patch.object(filesystem, 'read_json', return_value={'artifacts': rows}), \
                        self.assertRaisesRegex(ValueError, 'java-closed-filesystem-preimage-drift'):
                    filesystem.stage(ROOT / 'sdk/java-guest')

    def test_source_recipe_and_captured_sdk_keep_owned_transformer_and_service(self):
        self.assertIn('tools/java_guest/filesystem.py', RECIPE)
        files = sdk_snapshot(ROOT / 'sdk/java-guest')
        self.assertEqual(files[filesystem.SOURCE], (ROOT / 'sdk/java-guest' / filesystem.SOURCE).read_bytes())
        service = files['facilities/services/META-INF/services/org.teavm.vm.spi.TeaVMPlugin'].splitlines()
        self.assertEqual(service.count(b'dev.latent.guest.facilities.compiler.ClosedFilesystemPlugin'), 1)
        self.assertIn(b'dev.latent.guest.facilities.compiler.EntropyPlugin', service)
        self.assertIn(b'dev.latent.guest.facilities.compiler.LoggingPlugin', service)

    def test_profile_is_bound_to_the_actual_captured_sdk_owner_not_repository_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            sdk = Path(temporary)
            with self.assertRaises(OSError): filesystem.stage(sdk)
        original = filesystem.stage(ROOT / 'sdk/java-guest')
        with patch.object(filesystem, 'read_file', return_value=b'changed-owned-transformer'):
            changed = filesystem.stage(ROOT / 'sdk/java-guest')
        self.assertNotEqual(original['sourceDigest'], changed['sourceDigest'])

    def execute(self, mutation=None):
        rows = [invocation('scratch|java|entry|fresh=1')]
        rows += [invocation('scratch|java|unsupported-operation|fresh=1') for _ in range(3)]
        rows += [invocation(trap=True), invocation('scratch|java|entry|fresh=1')]
        rows += [invocation('scratch|java|' + category + '|fresh=1')
                 for category in sdk_scratch_probe.JAVA_ARGUMENTS.values()]
        if mutation: mutation(rows)
        result = {'invocations': [], 'providerIdle': [], 'samples': []}
        with patch('tools.rust_capsule_node.call', side_effect=rows) as called, \
                patch('tools.rust_capsule_node.assert_value'), \
                patch('tools.rust_capsule_node.provider_idle', return_value={'idle': True}), \
                patch('tools.rust_capsule_node.sample', return_value={'retired': True}):
            sdk_scratch_probe.probe(object(), {'budget': {'cpuFuel': 1000, 'memoryBytes': 8192},
                'grants': []}, object(), result, 5, language='java')
        return result, called

    def test_named_argument_errors_are_separate_from_three_unsupported_calls_and_all_retire(self):
        result, calls = self.execute()
        self.assertEqual(len(result['invocations']), 12)
        self.assertEqual(len(result['providerIdle']), 12)
        self.assertEqual(len(result['samples']), 12)
        self.assertTrue(result['standardScratchRefusal']['allErrorsAreUnsupported'])
        self.assertEqual([row['category'] for row in result['javaFilesystemArguments']['cases']],
                         list(sdk_scratch_probe.JAVA_ARGUMENTS.values()))
        self.assertEqual([call.args[4][0] for call in calls.call_args_list][6:],
                         ['scratch:' + mode for mode in sdk_scratch_probe.JAVA_ARGUMENTS])
        with tempfile.TemporaryDirectory() as temporary:
            app, record = project('java', Path(temporary) / 'application')
            source = (app / 'src/dev/latent/app/Capsule.java').read_bytes()
        self.assertFalse(record['sdkProfileAndLimitsChanged'])
        self.assertTrue(all(mode.encode() in source for mode in sdk_scratch_probe.JAVA_ARGUMENTS))

    def test_unsupported_trap_unknown_or_unreaped_is_not_original_argument_validation(self):
        mutations = (
            lambda rows: rows[6].update(decoded=[{'ok': 'scratch|java|unsupported-operation|fresh=1'}]),
            lambda rows: rows[6].update(exitCode=4),
            lambda rows: rows[6].update(processReaped=False),
            lambda rows: rows[6]['response'].update(outcomeKnown=False),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate), self.assertRaisesRegex(RuntimeError, 'scratch-'):
                self.execute(mutate)


if __name__ == '__main__': unittest.main()

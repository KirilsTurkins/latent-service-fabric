"""Pure/joined source and strict actual filesystem observation controls."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from tools import dotnet_closed_filesystem_fixture as fixture, qualify_dotnet_closed_filesystem as qualification
from tools.dotnet_guest import closed_filesystem, task_wait
from tools.phase3_resource_profile import ACTIVE_COUNTERS
from tools.rust_capsule_project import digest, read_file, write_json
from tools.sdk_scratch_probe import DOTNET_ARGUMENTS
from tools.tests.test_sdk_scratch_probe import invocation
from tools.tests.test_sdk_scratch_qualification import ordinary, replace_json
from tools.sdk_scratch_fixture import SOURCES


class DotnetFilesystemQualification(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.root = Path(owned.name)

    def make(self, joined=False):
        normal = self.root / 'normal'; normal.mkdir(); ordinary(normal)
        output = self.root / 'actual'; output.mkdir()
        shutil.copytree(normal / 'builds/word-count', output / 'build')
        (output / 'node').mkdir()
        argument_rows = [{'mode': name, 'category': category,
            'invocation': invocation('scratch|dotnet|' + category + '|fresh=1')} for name, category in DOTNET_ARGUMENTS.items()]
        scratch = {'allErrorsAreUnsupported': True,
            'cases': [{'mode': mode, 'observation': {'category': 'platform-not-supported', 'unsupported': True},
                'invocation': invocation('scratch|dotnet|platform-not-supported|fresh=1')} for mode in ('open', 'create', 'temp')],
            'preservedRuntimeGrants': [{'capability': 'latent:runtime/activation@0.1.0'}] if joined else []}
        node = {'status': 'passed', 'language': 'dotnet', 'invocations': [invocation('known') for _ in range(39)],
            'standardScratchRefusal': scratch, 'dotnetFilesystemArguments': {'status': 'passed', 'cases': argument_rows},
            'nodeShutdown': {'reaped': True, 'record': {'clean': True}}, 'samples': [{} for _ in range(36)],
            'providerIdle': [{'unavailable': [], 'counters': {key: '0' for key in ACTIVE_COUNTERS}} for _ in range(18)]}
        derived = {'digest': digest(b'final-corelib')}
        intermediate = {'digest': digest(b'intermediate-corelib')}
        binding = {'responseFiles': [{'digest': digest(b'actual-ilc-response'), 'size': 100}],
            'selectedCoreLibDigest': derived['digest']}
        port = {'profile': closed_filesystem.PROFILE, 'requiredDeclarations': [], 'filesystemAuthority': False,
            'modifiedOriginalMethods': 2, 'originalMethodBodies': closed_filesystem.METHODS, 'derived': derived,
            'nativeAotReferenceBinding': binding, 'taskWaitIntermediate': intermediate if joined else None,
            'baseDigest': intermediate['digest'] if joined else task_wait.SOURCE}
        write_json(output / 'node/workflow.json', node)
        write_json(output / 'build/closed-filesystem-port.json', port)
        if joined:
            task = {'profile': task_wait.PROFILE, 'derived': intermediate,
                'nativeAotReferenceBinding': {'responseFiles': binding['responseFiles'],
                    'finalCoreLibDerivation': {'selectedDigest': derived['digest']}}}
            write_json(output / 'build/task-wait-port.json', task)
        return output, node, port

    def test_pure_and_joined_sources_keep_original_sdk_limits_and_named_argument_calls(self):
        pure, plain = fixture.project(self.root / 'pure', joined=False)
        joined, selected = fixture.project(self.root / 'joined', joined=True)
        self.assertEqual(read_file(pure / 'sdk-lock.json'), read_file(joined / 'sdk-lock.json'))
        self.assertEqual(read_file(pure / 'capsule-project.json'), read_file(joined / 'capsule-project.json'))
        self.assertNotIn(b'latent:runtime/activation', read_file(pure / 'wit/world.wit'))
        self.assertIn(b'greet: async func(', read_file(joined / 'wit/world.wit'))
        self.assertIn(b'import latent:runtime/activation@0.1.0;', read_file(joined / 'wit/world.wit'))
        self.assertFalse(plain['explicitTaskWaitWorld']); self.assertTrue(selected['explicitTaskWaitWorld'])
        self.assertEqual(read_file(pure / SOURCES['dotnet']), read_file(joined / SOURCES['dotnet']))
        source = read_file(pure / SOURCES['dotnet'])
        for mode in DOTNET_ARGUMENTS:
            self.assertIn(mode.encode(), source)
        self.assertNotIn(b'.Message', source)

    def test_exact_pure_component_needs_no_activation_but_requires_three_caught_unsupported(self):
        output, node, port = self.make()
        proof = qualification.observed(output, joined=False)
        self.assertEqual(proof['invocations'], 39)
        self.assertIsNone(proof['port']['taskWaitIntermediate'])
        node['standardScratchRefusal']['cases'][0]['observation']['category'] = 'directory-not-found'
        replace_json(output / 'node/workflow.json', node)
        with self.assertRaisesRegex(RuntimeError, 'exact-caught-errors-and-retirement'):
            qualification.observed(output, joined=False)

    def test_unknown_argument_results_owner_leaks_or_missing_outcomes_never_pass(self):
        output, node, port = self.make()
        mutations = (
            lambda value: value['invocations'].pop(),
            lambda value: value['dotnetFilesystemArguments']['cases'][0]['invocation'].update(
                decoded=[{'ok': 'scratch|dotnet|platform-not-supported|fresh=1'}]),
            lambda value: value['providerIdle'][0]['counters'].update({next(iter(ACTIVE_COUNTERS)): '1'}),
            lambda value: value['nodeShutdown']['record'].update(clean=False),
        )
        for mutate in mutations:
            value = copy.deepcopy(node); mutate(value); replace_json(output / 'node/workflow.json', value)
            with self.subTest(mutate=mutate), self.assertRaises(RuntimeError):
                qualification.observed(output, joined=False)

    def test_joined_phase_binds_original_intermediate_and_same_final_native_response(self):
        output, node, port = self.make(joined=True)
        self.assertEqual(qualification.observed(output, joined=True)['port']['baseDigest'], port['taskWaitIntermediate']['digest'])
        task = json.loads(read_file(output / 'build/task-wait-port.json'))
        for field in ('selectedDigest', 'response'):
            changed = copy.deepcopy(task)
            if field == 'selectedDigest': changed['nativeAotReferenceBinding']['finalCoreLibDerivation']['selectedDigest'] = digest(b'foreign')
            else: changed['nativeAotReferenceBinding']['responseFiles'] = []
            replace_json(output / 'build/task-wait-port.json', changed)
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'actual-task-wait-chain'):
                qualification.observed(output, joined=True)

    def test_pure_cannot_inherit_runtime_authority_or_join_without_explicit_grant(self):
        output, node, port = self.make()
        node['standardScratchRefusal']['preservedRuntimeGrants'] = [{'capability': 'latent:runtime/activation@0.1.0'}]
        replace_json(output / 'node/workflow.json', node)
        with self.assertRaisesRegex(RuntimeError, 'independent-runtime-authority'):
            qualification.observed(output, joined=False)


if __name__ == '__main__':
    unittest.main()

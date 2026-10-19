"""Pure fixed-artifact controls; no downloaded or native code execution."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import replay_dotnet_reflection as replay
from tools.phase2_operator_process import WorkflowError


class FixedInputs(unittest.TestCase):
    def test_artifact_wrong_head_run_size_or_digest_refuses_before_payload(self):
        artifact, size, digest = replay.ARTIFACTS['products']
        valid = {'id': artifact, 'size_in_bytes': size, 'digest': digest, 'expired': False,
                 'workflow_run': {'id': replay.ORIGINAL_RUN, 'head_sha': replay.ORIGINAL_HEAD}}
        for key in ('head', 'run', 'size', 'digest', 'expired'):
            value = json.loads(json.dumps(valid))
            if key == 'head': value['workflow_run']['head_sha'] = 'other'
            elif key == 'run': value['workflow_run']['id'] += 1
            elif key == 'size': value['size_in_bytes'] += 1
            elif key == 'digest': value['digest'] = 'sha256:'+'0'*64
            else: value['expired'] = True
            with self.subTest(key=key), patch.object(replay, 'api', return_value=value), \
                 patch.object(replay.urllib.request, 'build_opener') as acquire, self.assertRaises(WorkflowError):
                replay.Artifact('products')
            acquire.assert_not_called()

    def test_fixed_package_layers_are_bound_to_real_marker_and_inventory(self):
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as temporary:
                component = b'owned component bytes'
                source, observation = b'[]\n', b'{"observation":"original"}\n'
                package = b'{"layers":[{"path":"component.wasm","source":"component.wasm"}]}'
                marker = {'componentDigest': replay.digest(component), 'sourceDigest': replay.digest(source),
                          'observationDigest': replay.digest(observation)}
                files = {'BUILD-COMPLETE.json': json.dumps(marker).encode(), 'source-inputs.json': source,
                         'recipe-inputs.json': b'[]', 'build-observation.json': observation,
                         'package-source.json': package, 'deployment.json': b'{}',
                         'component.wasm': component+b'changed' if changed else component,
                         'package-inputs.json': replay.inventory({'package-source.json': package,
                                                                  'component.wasm': component})}
                class Artifact:
                    def extract(self, name, output, maximum=replay.MAX_DOCUMENT):
                        self_name = name.removeprefix('dotnet-capsule-dependencies/builds/word-count/')
                        assert self_name in files
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(files[self_name])
                prepared = Path(temporary)
                if changed:
                    with self.assertRaisesRegex(WorkflowError, 'package-input-identity'):
                        replay.retrieve_build(Artifact(), 'word-count', prepared, marker)
                else:
                    replay.retrieve_build(Artifact(), 'word-count', prepared, marker)
                    self.assertEqual((prepared/'builds/word-count/component.wasm').read_bytes(), component)

    def test_noncompanion_and_unsafe_member_names_never_reach_extraction(self):
        for name in ('greeting', '../word-count', 'word-count/private'):
            with self.subTest(name=name), self.assertRaisesRegex(WorkflowError, 'fixed-companion'):
                replay.retrieve_build(None, name, None, {})
        for name in ('../private', 'C:private', '/absolute', 'a\\b', 'a//b'):
            with self.subTest(name=name), self.assertRaises(WorkflowError):
                replay.safe_name(name)

    def test_archive_link_and_expanded_bound_refuse_without_creating_output(self):
        for mode in ('link', 'oversized'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                data = io.BytesIO()
                with zipfile.ZipFile(data, 'w') as archive:
                    row = zipfile.ZipInfo('fixed.json')
                    row.external_attr = (0o120777 if mode == 'link' else 0o100600) << 16
                    archive.writestr(row, b'{}' if mode == 'link' else b'x'*17)
                artifact = object.__new__(replay.Artifact)
                artifact.archive, artifact.selected = zipfile.ZipFile(data), {}
                output = Path(temporary)/'fixed.json'
                with self.assertRaises(WorkflowError):
                    artifact.extract('fixed.json', output, 16)
                self.assertFalse(output.exists())

    def test_range_reader_refuses_unbounded_network_request(self):
        remote = replay.Ranges('https://unused.invalid', 256*1024**2)
        with patch.object(replay.urllib.request, 'urlopen') as request, self.assertRaises(WorkflowError):
            remote.read()
        request.assert_not_called()
        self.assertEqual(remote.requests, 0)

    def test_range_total_is_finitely_bound_to_fixed_artifact_size_including_rereads(self):
        class Reply:
            status = 206
            headers = {'Content-Range': 'bytes 0-3/4'}
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self, count): return b'1234'
        remote = replay.Ranges('https://unused.invalid', 4)
        with patch.object(replay.urllib.request, 'urlopen', return_value=Reply()) as request:
            for _ in range(2):
                remote.seek(0)
                self.assertEqual(remote.read(4), b'1234')
            remote.seek(0)
            with self.assertRaisesRegex(WorkflowError, 'total-range-bound'):
                remote.read(4)
            self.assertEqual(request.call_count, 2)


class SourceDelta(unittest.TestCase):
    def test_real_selected_runner_has_only_the_reviewed_default_off_delta(self):
        raw=(replay.ROOT/'tools/run_rust_capsule_workflow.py').read_bytes()
        tree=replay.NormalRunner().visit(replay.ast.parse(raw))
        self.assertEqual(replay.hashlib.sha256(replay.ast.dump(tree).encode()).hexdigest(),replay.ORIGINAL_RUNNER_AST)

    def test_other_programme_change_cannot_borrow_original_native_source_identity(self):
        raw=(replay.ROOT/'tools/run_rust_capsule_workflow.py').read_bytes()
        for changed in (raw.replace(b'language="rust"',b'language="go"'),raw+b'\nprint("unexpected replay")\n'):
            with self.subTest(change=len(changed)):
                tree=replay.NormalRunner().visit(replay.ast.parse(changed))
                self.assertNotEqual(replay.hashlib.sha256(replay.ast.dump(tree).encode()).hexdigest(),replay.ORIGINAL_RUNNER_AST)


class BoundaryReplay(unittest.TestCase):
    def exercise(self, boundaries, *, wrong_probe=False, changed_stage=False):
        from contextlib import ExitStack
        import time
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as controls:
            root = Path(temporary)
            output = root / 'result'
            products = {name: root / name for name in replay.PRODUCTS}
            source, receipt = {'frozen': 'source'}, {'sourceIdentityDigest': 'bound', 'binaries': {}}
            staged = {'inventoryDigest': 'sha256:' + 'a' * 64,
                      'files': {'tools/dotnet_guest/build.py': {'digest': 'sha256:' + 'b' * 64, 'size': 1}}}
            calls = []
            class Commands:
                def __init__(self, *args, **kwargs): self.deadline = time.monotonic() + 1800
                def run(self, *args): calls.append(args)
            def create(path, name):
                path.mkdir()
                return path
            def read(path, *args):
                if path.name == 'compiler-containment.json':
                    return {'network': 'denied', 'credentials': 'not-inherited'}
                if path.name == 'recipe-inputs.json': return staged['files']
                if path.name == 'BUILD-COMPLETE.json': return {'componentDigest': 'fresh'}
                if path.name == 'retrieval.json': return {'compiledSource': replay.ORIGINAL_HEAD}
                self.fail('unexpected reader: ' + path.name)
            patches = {
                'Commands': Commands, 'build_environment': lambda path: {},
                'verify_prepared': lambda path: (source, receipt, products),
                'inputs': lambda language: source, 'create': create,
                'source_files': lambda project: {'source': b'owned bytes'},
                'read_json': read, 'file_identity': lambda *args: {'sha256': 'sha256:' + 'c' * 64, 'bytes': 1},
            }
            for name, value in patches.items(): controls.enter_context(patch.object(replay, name, value))
            controls.enter_context(patch.object(replay.dependencies, 'verify_inputs', return_value=SimpleNamespace(lock={'same': True})))
            install = controls.enter_context(patch.object(replay, 'install', return_value={'dynamicAssembly': {'digest': 'bound'}}))
            build = controls.enter_context(patch.object(replay, 'build', return_value=output / 'build'))
            descriptor = controls.enter_context(patch.object(replay, 'descriptor_material', return_value={'descriptor': 'bound'}))
            stage = controls.enter_context(patch.object(replay.staging, 'stage', return_value=staged))
            controls.enter_context(patch.object(replay.staging, 'verify', return_value={} if changed_stage else staged))
            key = 'dotnetReflectionBoundaries' if boundaries else 'dotnetReflection'
            node = {'status': 'passed', key: {'status': 'passed', 'cases': list(range(6 if wrong_probe else 7 if boundaries else 4))},
                    'invocations': list(range(34 if boundaries else 31)),
                    'nodeShutdown': {'reaped': True, 'record': {'clean': True}}}
            invoke = controls.enter_context(patch.object(replay, 'node_workflow', return_value=node))
            result = replay.qualify(root / 'prepared', output, root / 'tools', boundaries=boundaries)
            return result, calls, install.call_args, build.call_count, descriptor.call_args, stage.call_count, invoke.call_args

    def test_boundary_mode_stages_real_recipe_selects_new_roots_and_requires_seven_cases(self):
        result, calls, install, builds, descriptor, stages, invoke = self.exercise(True)
        self.assertEqual(builds, 0)
        self.assertEqual(stages, 1)
        self.assertTrue(install.kwargs['boundaries'])
        self.assertEqual(descriptor.kwargs['roots'], replay.BOUNDARY_ROOTS)
        self.assertTrue(invoke.kwargs['dotnet_reflection_boundaries'])
        self.assertNotIn('dotnet_reflection', invoke.kwargs)
        compile_call, sign_call = calls
        self.assertEqual(compile_call[:5], ('catalogue-free-native-aot', replay.sys.executable, '-I', '-S', '-B'))
        self.assertIn('--expect-source-digest', compile_call)
        self.assertEqual(sign_call[0], 'reflection-sign')
        self.assertEqual(len(result['cases']), 7)
        self.assertFalse(result['optionalReferenceDataPresentDuringBuild'])
        self.assertFalse(result['nativeCargoProductsCompilationPerformed'])
        self.assertFalse(result['normalQualificationRecreated'])
        self.assertEqual(result['originalReflectionCasesRetained'], 4)

    def test_default_mode_preserves_original_build_four_cases_and_descriptor(self):
        result, calls, install, builds, descriptor, stages, invoke = self.exercise(False)
        self.assertEqual(builds, 1)
        self.assertEqual(stages, 0)
        self.assertEqual(install.kwargs, {})
        self.assertEqual(descriptor.kwargs, {})
        self.assertTrue(invoke.kwargs['dotnet_reflection'])
        self.assertNotIn('dotnet_reflection_boundaries', invoke.kwargs)
        self.assertEqual([row[0] for row in calls], ['reflection-sign'])
        self.assertEqual(len(result['cases']), 4)
        self.assertNotIn('stagedBuildSource', result)

    def test_incomplete_node_probe_or_changed_stage_cannot_be_qualified(self):
        for change in ('wrong_probe', 'changed_stage'):
            with self.subTest(change=change), self.assertRaises(WorkflowError):
                self.exercise(True, **{change: True})

    def test_boundary_selector_rejects_non_boolean_before_prepared_or_side_effects(self):
        for value in ('true', 1, None):
            with self.subTest(value=value), patch.object(replay, 'fresh') as fresh, self.assertRaises(WorkflowError):
                replay.qualify(None, None, None, boundaries=value)
            fresh.assert_not_called()


if __name__ == '__main__':
    unittest.main()

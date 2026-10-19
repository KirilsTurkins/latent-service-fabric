"""Pure fixed-artifact controls; no downloaded or native code execution."""
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from tools import replay_dotnet_private_dependencies as replay
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


if __name__ == '__main__':
    unittest.main()

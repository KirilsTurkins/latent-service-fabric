"""Failure-path secret isolation and original-deadline controls, no fake runtime pass."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import java_standard_http_node as owner


class JavaStandardHttpOwnershipTests(unittest.TestCase):
    def test_expired_parent_deadline_cannot_start_signer_or_create_evidence(self):
        with tempfile.TemporaryDirectory() as private:
            output = Path(private)/'output'
            with patch.object(owner, 'run_bounded_result') as signer:
                with self.assertRaisesRegex(RuntimeError, 'original-deadline-expired'):
                    owner.run(Path('unused-artifact'), Path('unused-native'), output, deadline=0)
            signer.assert_not_called()
            self.assertFalse(output.exists())

    def test_failed_peer_acquisition_cleans_private_credentials_outside_retained_evidence(self):
        with tempfile.TemporaryDirectory() as private:
            root = Path(private)
            artifact, native, output = root/'artifact', root/'native', root/'output'
            artifact.mkdir(); native.mkdir()
            for name in ('BUILD-COMPLETE.json', 'component.wasm', 'build-observation.json',
                         'source-inputs.json', 'recipe-inputs.json', 'http-client-profile.json'):
                (artifact/name).write_bytes(b'model input only')
            for name in ('latent', 'latentd', 'capsule_authoring'):
                (native/name).write_bytes(b'model executable, never executed')
            captured = []

            def fail_peer(arguments, *_args, **_options):
                credential = Path(arguments[arguments.index('--credential')+1])
                self.assertFalse(credential.is_relative_to(output))
                self.assertTrue(credential.is_file())
                captured.append((credential, credential.read_bytes()))
                raise RuntimeError('intentional-before-peer-process')

            with patch.object(owner, 'run_bounded_result', return_value=SimpleNamespace(returncode=0)), \
                    patch.object(owner, 'Process', side_effect=fail_peer):
                with self.assertRaisesRegex(RuntimeError, 'intentional-before-peer-process'):
                    owner.run(artifact, native, output)
            self.assertEqual(len(captured), 1)
            credential, raw = captured[0]
            self.assertFalse(credential.exists())
            self.assertTrue((output/'FAILED.json').exists())
            for path in output.rglob('*'):
                if path.is_file():
                    self.assertNotIn(raw, path.read_bytes())
            self.assertFalse((output/'qualification.json').exists())

    def test_acquired_peer_retires_before_its_private_credential_directory_is_removed(self):
        with tempfile.TemporaryDirectory() as private:
            root = Path(private)
            artifact, native, output = root/'artifact', root/'native', root/'output'
            artifact.mkdir(); native.mkdir()
            for name in ('BUILD-COMPLETE.json', 'component.wasm', 'build-observation.json',
                         'source-inputs.json', 'recipe-inputs.json', 'http-client-profile.json'):
                (artifact/name).write_bytes(b'model input only')
            for name in ('latent', 'latentd', 'capsule_authoring'):
                (native/name).write_bytes(b'model executable, never executed')
            test = self
            peers = []

            class AcquiredPeer:
                def __init__(self, arguments, *_args, **_options):
                    self.credential = Path(arguments[arguments.index('--credential')+1])
                    self.closed = False
                    peers.append(self)

                def line(self, _deadline):
                    raise RuntimeError('intentional-after-peer-acquisition')

                def close(self):
                    if not self.closed:
                        test.assertTrue(self.credential.is_file())
                        self.closed = True

            with patch.object(owner, 'run_bounded_result', return_value=SimpleNamespace(returncode=0)), \
                    patch.object(owner, 'Process', side_effect=AcquiredPeer):
                with self.assertRaisesRegex(RuntimeError, 'intentional-after-peer-acquisition'):
                    owner.run(artifact, native, output)
            self.assertEqual(len(peers), 1)
            self.assertTrue(peers[0].closed)
            self.assertFalse(peers[0].credential.exists())
            self.assertFalse((output/'qualification.json').exists())


if __name__ == '__main__':
    unittest.main()

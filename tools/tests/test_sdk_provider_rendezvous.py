"""Readers must never see an acknowledgement before its bytes are complete."""
from contextlib import contextmanager
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.sdk_provider_http_fixture import marker


class ProviderRendezvousTests(unittest.TestCase):
    def test_marker_is_invisible_until_buffered_writer_is_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / "closed-hold-dotnet-deadline"
            original_open = Path.open
            observations = []

            @contextmanager
            def observed_open(path, *args, **kwargs):
                with original_open(path, *args, **kwargs) as output:
                    observations.append(target.exists())
                    yield output
                    # Buffered write has returned, but close has not run yet.
                    observations.append(target.exists())

            with patch.object(Path, "open", observed_open):
                marker(directory, target.name)
            self.assertEqual(observations, [False, False])
            self.assertEqual(target.read_bytes(), b"observed\n")
            self.assertEqual(list(directory.iterdir()), [target])

    def test_repeated_event_fails_without_replacing_existing_acknowledgement(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / "started-hold-dotnet-shutdown"
            marker(directory, target.name)
            original = target.stat()
            with self.assertRaises(FileExistsError):
                marker(directory, target.name)
            self.assertEqual(target.read_bytes(), b"observed\n")
            self.assertEqual(target.stat().st_ino, original.st_ino)
            self.assertEqual(list(directory.iterdir()), [target])


if __name__ == "__main__":
    unittest.main()

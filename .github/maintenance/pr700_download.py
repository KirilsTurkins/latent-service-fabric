"""Qualify the remaining compiler download repair against the security candidate."""
from pathlib import Path
import hashlib
import json
import sys
import tempfile
import time

ROOT = Path(sys.argv[2]).resolve()
sys.path.insert(0, str(ROOT))

FUNCTION = '''def download(destination: Path, source: dict) -> None:
    # Large pinned archives need a reviewed transfer budget, not a relaxed byte
    # cap or a retry of compilation. Other source recipes retain the 90s budget.
    timeout = source.get("timeoutSeconds", 90)
    require(type(timeout) is int and 0 < timeout <= 300, "compiler-download-timeout-invalid")
    maximum = source["maximum"]
    require(type(maximum) is int and maximum > 0, "compiler-download-maximum-invalid")
    deadline, used = time.monotonic() + timeout, 0
    # Create exclusively before networking: never replace a prior input or link.
    with destination.open("xb") as output:
        with urllib.request.urlopen(source["url"], timeout=min(30, timeout)) as incoming:
            while True:
                require(time.monotonic() < deadline, "compiler-download-time-limit")
                raw = incoming.read(min(1024 * 1024, maximum + 1 - used))
                require(time.monotonic() < deadline, "compiler-download-time-limit")
                if not raw:
                    break
                used += len(raw)
                require(used <= maximum, "compiler-download-byte-limit")
                output.write(raw)
    require(file_digest(destination)[0] == source["sha256"], "compiler-upstream-archive-digest")
'''

TESTS = r'''

class CompilerDownloadBounds(unittest.TestCase):
    def setUp(self):
        import hashlib
        from tools import build_dev_guest_tools
        self.builder = build_dev_guest_tools
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name) / "archive"
        self.data = b"verified compiler bytes"
        self.source = {"url": "https://example.invalid/compiler", "maximum": len(self.data),
                       "sha256": "sha256:" + hashlib.sha256(self.data).hexdigest()}

    def transfer(self, *, data=None, elapsed=0):
        import io
        from unittest.mock import Mock
        stream = io.BytesIO(self.data if data is None else data)
        self.clock = 0
        def read(size):
            self.clock = elapsed
            return stream.read(size)
        incoming = Mock()
        incoming.__enter__ = Mock(return_value=incoming)
        incoming.__exit__ = Mock(return_value=False)
        incoming.read.side_effect = read
        with patch.object(self.builder.urllib.request, "urlopen", return_value=incoming) as opened, \
                patch.object(self.builder.time, "monotonic", side_effect=lambda: self.clock):
            self.builder.download(self.path, self.source)
        opened.assert_called_once_with(self.source["url"], timeout=min(30, self.source.get("timeoutSeconds", 90)))
        self.assertTrue(all(0 < call.args[0] <= len(self.data) + 1 for call in incoming.read.call_args_list))

    def test_small_default_transfer_accepts_only_pinned_bytes(self):
        self.transfer(elapsed=89)
        self.assertEqual(self.path.read_bytes(), self.data)

    def test_pinned_zig_transfer_can_exceed_small_archive_deadline(self):
        pin = self.builder.SOURCES["zig"]
        self.assertEqual((pin["maximum"], pin["sha256"]),
                         (self.builder.ZIG_BYTES, "sha256:" + self.builder.ZIG_SHA256))
        self.assertEqual(pin["timeoutSeconds"], 300)
        self.source["timeoutSeconds"] = pin["timeoutSeconds"]
        self.transfer(elapsed=120)
        self.assertEqual(self.path.read_bytes(), self.data)
        self.assertTrue(all("timeoutSeconds" not in source for name, source in self.builder.SOURCES.items() if name != "zig"))

    def test_default_deadline_is_not_extended(self):
        with self.assertRaisesRegex(common.DevError, "compiler-download-time-limit"):
            self.transfer(elapsed=90)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_large_archive_deadline_still_rejects_at_boundary(self):
        self.source["timeoutSeconds"] = 300
        with self.assertRaisesRegex(common.DevError, "compiler-download-time-limit"):
            self.transfer(elapsed=300)
        self.assertEqual(self.path.read_bytes(), b"")

    def test_eof_cannot_hide_an_expired_deadline(self):
        with self.assertRaisesRegex(common.DevError, "compiler-download-time-limit"):
            self.transfer(data=b"", elapsed=90)

    def test_one_extra_byte_is_rejected_before_writing_or_digesting(self):
        with patch.object(self.builder, "file_digest") as digest:
            with self.assertRaisesRegex(common.DevError, "compiler-download-byte-limit"):
                self.transfer(data=self.data + b"!")
            digest.assert_not_called()
        self.assertEqual(self.path.read_bytes(), b"")

    def test_truncated_changed_and_empty_archives_still_fail_digest(self):
        for data in (self.data[:-1], b"x" * len(self.data), b""):
            with self.subTest(data=data):
                self.path.unlink(missing_ok=True)
                with self.assertRaises(common.DevError):
                    self.transfer(data=data)

    def test_invalid_limits_fail_before_network_or_output(self):
        for field, values in (("timeoutSeconds", (0, -1, 301, True, 90.0, "90")),
                              ("maximum", (0, -1, False, "100"))):
            for value in values:
                source = dict(self.source, **{field: value})
                with self.subTest(field=field, value=value), \
                        patch.object(self.builder.urllib.request, "urlopen") as opened:
                    with self.assertRaises(common.DevError):
                        self.builder.download(self.path, source)
                    opened.assert_not_called()
                    self.assertFalse(self.path.exists())

    def test_existing_file_and_symlink_are_not_replaced(self):
        target = self.path.with_name("target")
        target.write_bytes(b"unrelated")
        for linked in (False, True):
            with self.subTest(linked=linked):
                self.path.unlink(missing_ok=True)
                if linked:
                    self.path.symlink_to(target)
                else:
                    self.path.write_bytes(b"prior")
                with patch.object(self.builder.urllib.request, "urlopen") as opened:
                    with self.assertRaises(FileExistsError):
                        self.builder.download(self.path, self.source)
                    opened.assert_not_called()
                self.assertEqual(target.read_bytes(), b"unrelated")
                self.assertEqual(self.path.read_bytes(), b"unrelated" if linked else b"prior")

    def test_network_failure_is_not_retried(self):
        failure = TimeoutError("synthetic socket timeout")
        with patch.object(self.builder.urllib.request, "urlopen", side_effect=failure) as opened:
            with self.assertRaises(TimeoutError) as caught:
                self.builder.download(self.path, self.source)
            self.assertIs(caught.exception, failure)
            self.assertEqual(opened.call_count, 1)
'''


def edit():
    path = ROOT / 'tools/build_dev_guest_tools.py'
    text = path.read_text()
    start, end = text.index('def download('), text.index('\n\ndef main()')
    assert 'time.monotonic() + 90' in text[start:end]
    text = text[:start] + FUNCTION.rstrip() + text[end:]
    before = '"maximum": ZIG_BYTES, "version": ZIG_VERSION}'
    assert before in text
    path.write_text(text.replace(before, '"maximum": ZIG_BYTES, "version": ZIG_VERSION, "timeoutSeconds": 300}'))
    path = ROOT / 'tools/tests/test_dev_tools.py'
    text = path.read_text()
    marker = '\n\nif __name__ == "__main__":'
    assert marker in text and 'class CompilerDownloadBounds' not in text
    path.write_text(text.replace(marker, TESTS + marker))


def probe():
    from tools.build_dev_guest_tools import download, SOURCES, file_digest
    with tempfile.TemporaryDirectory(prefix='lsf-compiler-download-probe-') as temporary:
        archive = Path(temporary) / 'zig.tar.xz'
        started = time.monotonic()
        try:
            download(archive, SOURCES['zig'])
        except Exception:
            print(json.dumps({'downloadPassed': False, 'elapsedSeconds': round(time.monotonic() - started, 3),
                              'bytes': archive.stat().st_size if archive.exists() else 0}), flush=True)
            raise
        digest, size = file_digest(archive)
        assert size == SOURCES['zig']['maximum']
        print(json.dumps({'downloadPassed': True, 'elapsedSeconds': round(time.monotonic() - started, 3),
                          'bytes': size, 'sha256': digest}), flush=True)


{'edit': edit, 'probe': probe}[sys.argv[1]]()

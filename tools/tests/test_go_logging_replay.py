"""Pure bounded source/archive controls; never execute retained native tools."""
import io
from pathlib import Path
import tarfile
import tempfile
import unittest
import zipfile

from tools import replay_go_standard_logging as replay
from tools.phase2_operator_process import WorkflowError


class SourceFence(unittest.TestCase):
    def fixture(self, root, *, special=None):
        source = root / 'source'
        (source / 'apps').mkdir(parents=True)
        (source / 'tools').mkdir()
        native = b'fn main() {}\n'
        probe = b'LIBRARY = "original"\ndef install(): return "original"\ndef configure(): return 17\n'
        (source / 'apps/main.rs').write_bytes(native)
        (source / 'tools/go_standard_logging_probe.py').write_bytes(probe)
        archive = root / 'source.tar.gz'
        with tarfile.open(archive, 'w:gz') as output:
            for name, raw in [('apps/main.rs', native), ('tools/go_standard_logging_probe.py', probe)]:
                row = tarfile.TarInfo(name)
                row.size = len(raw)
                if special and name == 'apps/main.rs':
                    row.type, row.linkname, row.size = tarfile.SYMTYPE, '../outside', 0
                output.addfile(row, None if row.issym() else io.BytesIO(raw))
        return source, archive, ['apps/main.rs', 'tools/go_standard_logging_probe.py']

    def test_actual_source_bytes_and_only_configure_or_tutorial_fixture_changes_are_allowed(self):
        with tempfile.TemporaryDirectory() as temporary:
            source, archive, names = self.fixture(Path(temporary))
            probe = source / 'tools/go_standard_logging_probe.py'
            probe.write_bytes(probe.read_bytes().replace(b'return 17', b'return 14') + b'def tutorials(): return "bounded"\n')
            proof = replay.prove_source(archive, source, names)
            self.assertTrue(proof['runtimeProductionBytesEqualCurrent'])
            self.assertEqual(proof['files'], 1)
            probe.write_bytes(probe.read_bytes().replace(b'return "original"', b'return "changed"'))
            with self.assertRaisesRegex(WorkflowError, 'library-or-install-changed'):
                replay.prove_source(archive, source, names)

    def test_changed_added_removed_production_inputs_refuse_before_any_execution(self):
        for mode in ('changed', 'added', 'removed'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                source, archive, names = self.fixture(Path(temporary))
                if mode == 'changed':
                    (source / 'apps/main.rs').write_bytes(b'fn changed() {}')
                elif mode == 'added':
                    (source / 'apps/new.rs').write_bytes(b'fn added() {}')
                    names.append('apps/new.rs')
                else:
                    names.remove('apps/main.rs')
                with self.assertRaisesRegex(WorkflowError, 'production-source'):
                    replay.prove_source(archive, source, names)

    def test_link_source_archive_refuses_without_extracting_a_target(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, archive, names = self.fixture(root, special=True)
            with self.assertRaisesRegex(WorkflowError, 'link-or-special'):
                replay.prove_source(archive, source, names)
            self.assertFalse((root / 'outside').exists())

    def test_fixed_member_names_reject_aliases_parent_escape_and_windows_paths(self):
        for name in ('../private', '/absolute', 'C:private', 'a\\b', 'a//b', 'a/./b', '', '.', None):
            with self.subTest(name=name), self.assertRaises(WorkflowError):
                replay.safe_name(name)


class MemberFence(unittest.TestCase):
    def test_fixed_member_extractor_does_not_accept_links_or_oversized_data(self):
        for mode in ('link', 'oversized'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                raw = io.BytesIO()
                with zipfile.ZipFile(raw, 'w') as output:
                    row = zipfile.ZipInfo('approved.json')
                    row.external_attr = (0o120777 if mode == 'link' else 0o100600) << 16
                    output.writestr(row, b'{}' if mode == 'link' else b'x' * 17)
                owned = object.__new__(replay.Artifact)
                owned.archive, owned.selected = zipfile.ZipFile(raw), {}
                target = Path(temporary) / 'approved.json'
                with self.assertRaisesRegex(WorkflowError, 'type-or-byte-bound'):
                    owned.extract('approved.json', target, 16)
                self.assertFalse(target.exists())

    def test_range_reader_refuses_an_unbounded_read_without_network(self):
        remote = replay.Ranges('https://unused.invalid', 256 * 1024**2)
        with self.assertRaisesRegex(WorkflowError, 'range-byte-bound'):
            remote.read()
        self.assertEqual(remote.requests, 0)
        with self.assertRaisesRegex(WorkflowError, 'seek-kind'):
            remote.seek(0, 3)


class ImmutableGitSourceFence(unittest.TestCase):
    def test_missing_archive_source_is_bound_to_same_tested_commit_and_current_bytes(self):
        import base64
        import hashlib
        from unittest.mock import patch
        raw = b'owned source from the same tested commit\n'
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        tree = 'a'*40
        record = {'sha': tree, 'tree': [{'path': 'extra.rs', 'type': 'blob', 'mode': '100644',
                                       'sha': blob, 'size': len(raw)}]}
        def api(path):
            if path == 'git/trees/' + tree:
                return record
            self.assertEqual(path, 'git/blobs/' + blob)
            return {'sha': blob, 'size': len(raw), 'encoding': 'base64',
                    'content': base64.b64encode(raw).decode()}
        with tempfile.TemporaryDirectory() as temporary:
            source, archive, names = SourceFence().fixture(Path(temporary))
            (source/'extra.rs').write_bytes(raw)
            names.append('extra.rs')
            with patch.object(replay, 'api', side_effect=api) as query:
                git = replay.GitSources({'sha': replay.ORIGINAL_TESTED, 'tree': {'sha': tree}})
                proof = replay.prove_source(archive, source, names, git)
                self.assertEqual((proof['archiveFiles'], proof['gitOnlyFiles'], proof['files']), (1, 1, 2))
                row = proof['inventory']['extra.rs']
                self.assertEqual(row['testedCommit'], replay.ORIGINAL_TESTED)
                self.assertEqual(row['gitBlobSha1'], blob)
                self.assertEqual(row['sha256'], replay.digest(raw))
                self.assertEqual(row['provenance'], 'official-tested-git-blob')
                self.assertEqual(proof['inventory']['apps/main.rs']['provenance'], 'retained-source-archive')
                self.assertEqual(replay.prove_source(archive, source, names, git), proof)
                self.assertEqual(query.call_count, 2)
                (source/'extra.rs').write_bytes(raw+b'changed')
                with self.assertRaisesRegex(WorkflowError, 'preimage-mismatch'):
                    replay.prove_source(archive, source, names, git)

    def test_wrong_commit_tree_or_nonregular_selected_blob_cannot_supply_source(self):
        from unittest.mock import patch
        with self.assertRaisesRegex(WorkflowError, 'tested-commit'):
            replay.GitSources({'sha': 'other', 'tree': {'sha': 'a'*40}})
        for mode in ('wrong-tree', 'truncated', 'symlink', 'missing', 'oversized'):
            with self.subTest(mode=mode):
                row = {'path': 'extra.rs', 'type': 'blob', 'mode': '120000' if mode == 'symlink' else '100644',
                       'sha': 'b'*40, 'size': 32*1024**2+1 if mode == 'oversized' else 10}
                value = {'sha': 'c'*40 if mode == 'wrong-tree' else 'a'*40,
                         'truncated': mode == 'truncated', 'tree': [] if mode == 'missing' else [row]}
                with patch.object(replay, 'api', return_value=value) as query, self.assertRaises(WorkflowError):
                    replay.GitSources({'sha': replay.ORIGINAL_TESTED, 'tree': {'sha': 'a'*40}}).read('extra.rs')
                self.assertEqual(query.call_count, 1)

    def test_blob_body_must_match_tree_object_hash_and_exact_size(self):
        import base64
        import hashlib
        from unittest.mock import patch
        raw = b'original source'
        blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
        tree = {'sha': 'a'*40, 'tree': [{'path': 'extra.rs', 'type': 'blob', 'mode': '100644',
                                      'sha': blob, 'size': len(raw)}]}
        for mode in ('tampered-same-length', 'wrong-sha', 'wrong-size', 'invalid-base64'):
            with self.subTest(mode=mode):
                value = {'sha': 'c'*40 if mode == 'wrong-sha' else blob,
                         'size': len(raw)+1 if mode == 'wrong-size' else len(raw), 'encoding': 'base64',
                         'content': '!' if mode == 'invalid-base64' else base64.b64encode(
                             b'changed! source' if mode == 'tampered-same-length' else raw).decode()}
                error = ValueError if mode == 'invalid-base64' else WorkflowError
                with patch.object(replay, 'api', side_effect=[tree, value]), self.assertRaises(error):
                    replay.GitSources({'sha': replay.ORIGINAL_TESTED, 'tree': {'sha': 'a'*40}}).read('extra.rs')


if __name__ == '__main__':
    unittest.main()

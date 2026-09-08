import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from tools import package_phase1_evidence as package
from tools import validate_phase1_archive as verify


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='phase1-archive-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        for name in ('aggregate.json', 'comparison.json'):
            (self.source / name).write_bytes(b'{}\n')
        (self.source / 'collector').write_bytes(b'bounded binary bytes\x00')
        self.policy = self.root / 'policy.json'
        self.policy.write_bytes(b'{}\n')
        self.output = self.root / 'package'
        self.output.mkdir()
        package.create_archive(self.source, self.output, self.policy)

    def rehash_archive(self, raw):
        (self.output / verify.ARCHIVE).write_bytes(raw)
        path = self.output / verify.MANIFEST
        manifest = json.loads(path.read_text())
        manifest['archive'] = verify.file_reference(self.output / verify.ARCHIVE, self.output)
        path.write_text(json.dumps(manifest))
        (self.output / (verify.ARCHIVE + '.sha256')).write_text(
            hashlib.sha256(raw).hexdigest() + '  ' + verify.ARCHIVE + '\n')

    def members(self, kind=tarfile.REGTYPE, name='collector', duplicate=False):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w', format=tarfile.USTAR_FORMAT) as archive:
            for row in json.loads((self.output / verify.MANIFEST).read_text())['files']:
                data = self.policy.read_bytes() if row['path'] == 'measurement-policy.json' else (self.source / row['path']).read_bytes()
                info = tarfile.TarInfo(name if row['path'] == 'collector' else row['path'])
                info.type = kind if row['path'] == 'collector' else tarfile.REGTYPE
                info.size = len(data) if info.isfile() else 0
                info.linkname = 'aggregate.json' if info.islnk() or info.issym() else ''
                archive.addfile(info, io.BytesIO(data) if info.isfile() else None)
                if duplicate and row['path'] == 'collector':
                    archive.addfile(info, io.BytesIO(data))
        return gzip.compress(stream.getvalue(), mtime=0)

    def test_round_trip_preserves_every_byte_and_does_not_edit_source(self):
        before = {p.name: p.read_bytes() for p in self.source.iterdir()}
        manifest = verify.verify_package(self.output, replay=False)
        self.assertEqual(len(manifest['files']), 4)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.source.iterdir()})

    def test_archive_is_reproducible_without_source_mtime(self):
        second = self.root / 'second'
        second.mkdir()
        package.create_archive(self.source, second, self.policy)
        self.assertEqual((self.output / verify.ARCHIVE).read_bytes(), (second / verify.ARCHIVE).read_bytes())

    def test_rejects_tampered_archive_checksum(self):
        with (self.output / verify.ARCHIVE).open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_rejects_outer_copy_diverging_from_archived_bytes(self):
        (self.output / 'aggregate.json').write_bytes(b'{"forged":true}')
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_rejects_links_devices_and_traversal_before_extraction(self):
        for kind, name in ((tarfile.SYMTYPE, 'collector'), (tarfile.LNKTYPE, 'collector'),
                           (tarfile.FIFOTYPE, 'collector'), (tarfile.REGTYPE, '../escape'),
                           (tarfile.REGTYPE, 'C:/escape')):
            with self.subTest(kind=kind, name=name):
                self.rehash_archive(self.members(kind, name))
                with self.assertRaises(ValueError):
                    verify.verify_package(self.output, replay=False)
        self.assertFalse((self.root / 'escape').exists())

    def test_rejects_duplicate_members(self):
        self.rehash_archive(self.members(duplicate=True))
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_rejects_rehashed_payload_corruption(self):
        raw = gzip.decompress((self.output / verify.ARCHIVE).read_bytes()).replace(b'bounded binary bytes', b'corrupt binary bytes')
        self.rehash_archive(gzip.compress(raw))
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_rejects_data_after_tar_end_and_truncated_gzip(self):
        original = (self.output / verify.ARCHIVE).read_bytes()
        self.rehash_archive(gzip.compress(gzip.decompress(original) + b'X' * 512))
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)
        self.rehash_archive(original[:-4])
        with self.assertRaises((ValueError, EOFError, OSError)):
            verify.verify_package(self.output, replay=False)

    def test_rejects_large_pax_header_without_reading_its_body(self):
        header = tarfile.TarInfo('collector')
        header.type = tarfile.XHDTYPE
        header.size = 1024 * 1024 * 1024
        self.rehash_archive(gzip.compress(header.tobuf(format=tarfile.USTAR_FORMAT) + b'\0' * 1024))
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_manifest_capacity_and_duplicate_fields_fail(self):
        with patch.object(verify, 'MAX_EXPANDED', 8):
            with self.assertRaises(ValueError):
                verify.verify_package(self.output, replay=False)
        manifest = self.output / verify.MANIFEST
        manifest.write_text('{"schema":"first","schema":"second"}')
        with self.assertRaises(ValueError):
            verify.verify_package(self.output, replay=False)

    def test_failed_replay_never_publishes_package(self):
        destination = self.root / 'unpublished'
        with patch.object(package, 'verify_package', side_effect=ValueError('invalid evidence')):
            with self.assertRaises(ValueError):
                package.package(self.source, destination, self.policy)
        self.assertFalse(destination.exists())
        self.assertEqual((self.source / 'collector').read_bytes(), b'bounded binary bytes\x00')

    def test_policy_checks_recorded_document_and_canonical_digest(self):
        policy = {'version': 1, 'allowance': '64', 'label': 'μs'}
        encoded = json.dumps(policy, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        aggregate = {'policy': {'document': policy, 'sha256': 'sha256:' + hashlib.sha256(encoded).hexdigest()}}
        verify.verify_policy(policy, aggregate)
        with self.assertRaises(ValueError):
            verify.verify_policy({'version': 1, 'allowance': '65'}, aggregate)
        aggregate['policy']['sha256'] = 'sha256:' + '0' * 64
        with self.assertRaises(ValueError):
            verify.verify_policy(policy, aggregate)


class PairedArchiveTests(unittest.TestCase):
    def setUp(self):
        import sys
        tools_directory = str(Path(__file__).resolve().parents[1])
        sys.path.insert(0, tools_directory)
        self.addCleanup(sys.path.remove, tools_directory)
        self.temporary = tempfile.TemporaryDirectory(prefix='phase1-paired-archive-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        from tools.tests.phase1_paired_fixtures import suite
        from tools.phase1_paired.aggregate import aggregate
        from tools.phase1_evidence.common import canonical
        self.suite_path = suite(self.source)
        (self.source / 'aggregate.json').write_bytes(canonical(aggregate(self.suite_path, self.source)))
        self.output = self.root / 'package'
        self.unneeded_policy = self.root / 'does-not-exist.json'

    def test_paired_round_trip_replays_all_inputs_without_measurement_policy(self):
        before = {path.relative_to(self.source).as_posix(): path.read_bytes()
                  for path in self.source.rglob('*') if path.is_file()}
        manifest = package.package(self.source, self.output, self.unneeded_policy)
        self.assertEqual(manifest, verify.verify_package(self.output))
        self.assertEqual({row['path'] for row in manifest['files']}, set(before))
        self.assertTrue({'reproduction/candidate/collector', 'reproduction/control/release/phase0-baseline',
                         'reproduction/candidate/echo-capsule.wasm', 'suite.json'} <= set(before))
        self.assertFalse((self.output / 'measurement-policy.json').exists())
        self.assertFalse((self.output / 'comparison.json').exists())
        self.assertEqual(before, {path.relative_to(self.source).as_posix(): path.read_bytes()
                                for path in self.source.rglob('*') if path.is_file()})

    def test_paired_outer_aggregate_tamper_rejected(self):
        package.package(self.source, self.output, self.unneeded_policy)
        path = self.output / 'aggregate.json'
        value = json.loads(path.read_bytes())
        value['status'] = 'passed'
        path.write_text(json.dumps(value))
        with self.assertRaisesRegex(ValueError, 'outer evidence'):
            verify.verify_package(self.output)

    def test_rehashed_paired_raw_association_never_publishes(self):
        from tools.phase1_evidence.common import canonical, reference
        from tools.tests.phase1_paired_fixtures import refresh
        path = self.source / 'pair-01/candidate/candidate.json'
        value = json.loads(path.read_bytes())
        value['samples'][0]['receipt']['release_digest'] = 'sha256:' + '0' * 64
        path.write_bytes(canonical(value))
        refresh(self.suite_path)
        aggregate_path = self.source / 'aggregate.json'
        value = json.loads(aggregate_path.read_bytes())
        value['source'] = reference(self.suite_path, self.source)
        aggregate_path.write_bytes(canonical(value))
        with self.assertRaisesRegex(ValueError, 'terminal-pin'):
            package.package(self.source, self.output, self.unneeded_policy)
        self.assertFalse(self.output.exists())

    def test_paired_executed_binary_tamper_rejected_by_semantic_replay(self):
        binary = self.source / 'reproduction/candidate/collector'
        binary.write_bytes(b'changed executable')
        with self.assertRaisesRegex(ValueError, 'artifact-identity-mismatch'):
            package.package(self.source, self.output, self.unneeded_policy)
        self.assertFalse(self.output.exists())


class OptimizationArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='optimization-archive-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.output = self.root / 'package'
        self.aggregate = {
            'schema': 'latent.optimization.aggregate.v1', 'profile': 'full',
            'status': 'complete', 'population_complete': True, 'attempt_count_complete': True,
            'validated_attempts': '4', 'test_statistic': '12.5',
        }

    def minimal_inputs(self):
        # This reduced archive has fake executable bytes. Successful full-suite
        # replay is mocked only in tests of archive dispatch/equality; the real
        # replay rejection test below uses the existing semantic suite fixture.
        (self.source / 'suite.json').write_bytes(b'{"test":"extracted suite"}\n')
        (self.source / 'binary').write_bytes(b'fixture executable\x00')
        (self.source / 'empty.log').write_bytes(b'')

    def large_aggregate(self):
        # Distribution/count rows model the full retained report: individually
        # small values, under 8 MiB, but more than 200,000 total JSON nodes.
        row = {'attempts': '400', 'successes': '396', 'failures': '4',
               'latency_nanos': {'minimum': '12000', 'p50': '15000',
                                 'p95': '19000', 'p99': '21000', 'maximum': '22000'}}
        return {**self.aggregate, 'rows': [row] * 20_001}

    def test_large_optimization_aggregate_dispatch_and_replay_use_its_structural_bound(self):
        self.minimal_inputs()
        value = self.large_aggregate()
        path = self.source / 'aggregate.json'
        path.write_bytes(verify.canonical(value))
        self.assertLess(path.stat().st_size, verify.MAX_AGGREGATE_BYTES)
        with self.assertRaisesRegex(ValueError, 'json-structure-limit'):
            verify.read_json(path)
        self.assertEqual(verify.evidence_kind(self.source), 'optimization')
        with patch.object(verify, 'validate_optimization_suite', return_value=value) as replay:
            verify.verify_optimization(self.source)
            replay.assert_called_once_with(self.source / 'suite.json')

    def test_optimization_aggregate_keeps_exact_eight_mib_archive_byte_cap(self):
        self.minimal_inputs()
        path = self.source / 'aggregate.json'
        encoded = verify.canonical(self.aggregate)
        path.write_bytes(encoded + b' ' * (verify.MAX_AGGREGATE_BYTES - len(encoded)))
        self.assertEqual(verify.evidence_kind(self.source), 'optimization')
        with path.open('ab') as stream:
            stream.write(b' ')
        with patch.object(verify, 'validate_optimization_suite') as replay:
            for operation in (verify.evidence_kind, verify.verify_optimization):
                with self.subTest(operation=operation.__name__):
                    with self.assertRaisesRegex(ValueError, 'json-byte-bound'):
                        operation(self.source)
            replay.assert_not_called()

    def test_legacy_dispatch_preserves_node_and_string_limits(self):
        path = self.source / 'aggregate.json'
        for schema in ('latent.phase1.measurement-aggregate.v1',
                       'latent.phase1.paired-aggregate.v1', None):
            for value, reason in (
                    (self.large_aggregate(), 'json-structure-limit'),
                    ({'text': 'x' * (64 * 1024 + 1)}, 'invalid-string')):
                with self.subTest(schema=schema, reason=reason):
                    value['schema'] = schema
                    path.write_bytes(verify.canonical(value))
                    with self.assertRaisesRegex(ValueError, reason):
                        verify.evidence_kind(self.source)

    def archive(self, aggregate=None):
        (self.source / 'aggregate.json').write_bytes(verify.canonical(
            self.aggregate if aggregate is None else aggregate) + b'\n')
        self.output.mkdir()
        references = []
        with (self.output / verify.ARCHIVE).open('xb') as output:
            with gzip.GzipFile(filename='', mode='wb', fileobj=output, mtime=0) as compressed:
                with tarfile.open(fileobj=compressed, mode='w|', format=tarfile.USTAR_FORMAT) as archive:
                    for path in sorted(self.source.rglob('*')):
                        if not path.is_file():
                            continue
                        reference = verify.file_reference(path, self.source)
                        references.append(reference)
                        member = tarfile.TarInfo(reference['path'])
                        member.size = int(reference['bytes'])
                        member.mode = 0o644
                        with path.open('rb') as source:
                            archive.addfile(member, source)
        manifest = {
            'schema': 'latent.phase1.archive-manifest.v1',
            'archive': verify.file_reference(self.output / verify.ARCHIVE, self.output),
            'files': references, 'total_bytes': str(sum(int(row['bytes']) for row in references)),
        }
        (self.output / verify.MANIFEST).write_bytes(verify.canonical(manifest))
        (self.output / (verify.ARCHIVE + '.sha256')).write_text(
            manifest['archive']['sha256'][7:] + '  ' + verify.ARCHIVE + '\n',
            encoding='ascii', newline='\n')
        (self.output / 'aggregate.json').write_bytes((self.source / 'aggregate.json').read_bytes())
        return manifest

    def test_optimization_dispatch_replays_extracted_suite_and_retains_empty_logs(self):
        self.minimal_inputs()
        manifest = self.archive()
        def replay(path):
            self.assertEqual(path.name, 'suite.json')
            self.assertNotEqual(path.parent, self.source)
            self.assertEqual(path.read_bytes(), (self.source / 'suite.json').read_bytes())
            self.assertEqual((path.parent / 'empty.log').read_bytes(), b'')
            self.assertEqual((path.parent / 'binary').read_bytes(), b'fixture executable\x00')
            return self.aggregate
        with patch.object(verify, 'validate_optimization_suite', side_effect=replay) as called:
            self.assertEqual(verify.verify_package(self.output), manifest)
            called.assert_called_once()
        self.assertEqual(next(row['bytes'] for row in manifest['files'] if row['path'] == 'empty.log'), '0')
        self.assertFalse((self.output / 'comparison.json').exists())
        self.assertFalse((self.output / 'measurement-policy.json').exists())

    def test_optimization_packager_replays_before_publishing_without_policy(self):
        self.minimal_inputs()
        (self.source / 'aggregate.json').write_bytes(verify.canonical(self.aggregate) + b'\n')
        before = {path.name: path.read_bytes() for path in self.source.iterdir()}

        def replay(path):
            self.assertFalse(self.output.exists(), 'publication must follow replay')
            self.assertNotEqual(path.parent, self.source)
            self.assertEqual(before, {entry.name: entry.read_bytes() for entry in path.parent.iterdir()})
            return self.aggregate

        # Only the expensive full-population semantic fixture is substituted;
        # archive creation, safe extraction, byte identities and publication run.
        with patch.object(verify, 'validate_optimization_suite', side_effect=replay) as called:
            manifest = package.package(self.source, self.output, self.root / 'absent-policy.json')
            called.assert_called_once()
        self.assertTrue(self.output.is_dir())
        self.assertEqual({row['path'] for row in manifest['files']}, set(before))
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.source.iterdir()})
        self.assertFalse((self.output / 'comparison.json').exists())
        self.assertFalse((self.output / 'measurement-policy.json').exists())

    def test_optimization_packager_does_not_publish_replayed_aggregate_mismatch(self):
        self.minimal_inputs()
        (self.source / 'aggregate.json').write_bytes(verify.canonical(
            {**self.aggregate, 'test_statistic': '0'}))
        with patch.object(verify, 'validate_optimization_suite', return_value=self.aggregate):
            with self.assertRaisesRegex(ValueError, 'differs from replayed'):
                package.package(self.source, self.output, self.root / 'absent-policy.json')
        self.assertFalse(self.output.exists())

    def test_rehashed_aggregate_statistic_cannot_replace_replayed_value(self):
        self.minimal_inputs()
        self.archive({**self.aggregate, 'test_statistic': '0'})
        # Archive, member, sidecar and outer-copy hashes all match the changed
        # bytes. Only replay equality can detect this semantic substitution.
        with patch.object(verify, 'validate_optimization_suite', return_value=self.aggregate):
            with self.assertRaisesRegex(ValueError, 'differs from replayed'):
                verify.verify_package(self.output)

    def test_full_population_flags_are_checked_even_when_aggregate_matches(self):
        for changes in ({'profile': 'smoke'}, {'status': 'incomplete'}, {'status': 'failed'},
                        {'population_complete': False}, {'population_complete': 1},
                        {'attempt_count_complete': False}, {'attempt_count_complete': 1}):
            with self.subTest(changes=changes):
                value = {**self.aggregate, **changes}
                (self.source / 'aggregate.json').write_bytes(verify.canonical(value))
                (self.source / 'suite.json').write_bytes(b'{}')
                with patch.object(verify, 'validate_optimization_suite', return_value=value):
                    with self.assertRaisesRegex(ValueError, 'complete full-population'):
                        verify.verify_optimization(self.source)

    def test_shape_only_is_explicit_and_never_invokes_semantic_replay(self):
        self.minimal_inputs()
        self.archive({**self.aggregate, 'profile': 'smoke', 'status': 'incomplete'})
        with patch.object(verify, 'validate_optimization_suite', side_effect=ValueError('missing actual population')) as replay:
            verify.verify_package(self.output, replay=False)
            replay.assert_not_called()
            with self.assertRaisesRegex(ValueError, 'missing actual population'):
                verify.verify_package(self.output)

    def test_missing_suite_is_rejected_even_for_shape_only_verification(self):
        self.archive()
        with self.assertRaisesRegex(ValueError, 'omits suite'):
            verify.verify_package(self.output, replay=False)

    def test_unknown_aggregate_schema_does_not_masquerade_as_supported(self):
        self.minimal_inputs()
        self.archive({**self.aggregate, 'schema': 'latent.optimization.aggregate.future'})
        with self.assertRaisesRegex(ValueError, 'unsupported evidence schema'):
            verify.verify_package(self.output, replay=False)

    def test_rehashed_raw_semantic_corruption_fails_real_suite_replay(self):
        from tools.tests.test_optimization_evidence import Fixture
        from tools.optimization_evidence.suite import validate_suite
        from tools.optimization_evidence.common import canonical
        fixture = Fixture(self.source)
        retained = validate_suite(self.source / 'suite.json')
        batch = fixture.suite['runs'][0]['batches'][0]
        row_path = self.source / batch['attempts']['path']
        rows = [json.loads(line) for line in row_path.read_bytes().splitlines()]
        rows[0]['response']['payload_sha256'] = 'sha256:' + '0' * 64
        fixture.replace(batch['attempts'], b''.join(canonical(row) + b'\n' for row in rows))
        self.archive(retained)
        # No replay mocks: suite references and the enclosing archive have
        # correct new hashes, while the response no longer matches its input.
        with self.assertRaisesRegex(ValueError, 'false-semantic-success'):
            verify.verify_package(self.output)
        unpublished = self.root / 'unpublished'
        with self.assertRaisesRegex(ValueError, 'false-semantic-success'):
            package.package(self.source, unpublished, self.root / 'absent-policy.json')
        self.assertFalse(unpublished.exists())


class ArtifactIdentityArchiveTests(unittest.TestCase):
    # Reuse only the format-neutral tar/manifest fixture, not another format's
    # tests or semantic validator. These archives deliberately contain fake
    # executable bytes; full valid replay is substituted at the dispatch seam.
    archive = OptimizationArchiveTests.archive

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='artifact-identity-archive-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / 'source'
        self.source.mkdir()
        self.output = self.root / 'package'
        self.aggregate = {
            'schema': 'latent.artifact-identity.aggregate.v1', 'profile': 'full',
            'status': 'passed', 'population_complete': True, 'full_comparison_qualified': True,
            'validated_runs': '252', 'pairs': '7', 'statistics': [{'metric': 'elapsed_nanos', 'value': '12'}],
        }
        (self.source / 'suite.json').write_bytes(b'{"schema":"latent.artifact-identity.suite.v1"}\n')
        (self.source / 'probe').write_bytes(b'fixture executable\x00')
        (self.source / 'profile.folded').write_bytes(b'probe;content_digest 64\n')
        (self.source / 'empty.log').write_bytes(b'')

    def test_artifact_identity_round_trip_replays_before_publish_without_policy(self):
        (self.source / 'aggregate.json').write_bytes(verify.canonical(self.aggregate))
        before = {entry.name: entry.read_bytes() for entry in self.source.iterdir()}

        def replay(path):
            self.assertEqual(path.name, 'suite.json')
            self.assertNotEqual(path.parent, self.source)
            self.assertFalse(self.output.exists())
            self.assertEqual(before, {entry.name: entry.read_bytes() for entry in path.parent.iterdir()})
            return self.aggregate

        with patch.object(verify, 'validate_artifact_identity_suite', side_effect=replay) as called:
            manifest = package.package(self.source, self.output, self.root / 'no-policy.json')
            called.assert_called_once()
        self.assertEqual({row['path'] for row in manifest['files']}, set(before))
        self.assertEqual(before, {entry.name: entry.read_bytes() for entry in self.source.iterdir()})
        self.assertFalse((self.output / 'measurement-policy.json').exists())
        self.assertFalse((self.output / 'comparison.json').exists())
        self.assertEqual(verify.evidence_kind(self.output), 'artifact-identity')

    def test_rehashed_artifact_statistic_fails_semantic_equality_and_is_not_published(self):
        forged = {**self.aggregate, 'statistics': [{'metric': 'elapsed_nanos', 'value': '0'}]}
        self.archive(forged)
        with patch.object(verify, 'validate_artifact_identity_suite', return_value=self.aggregate):
            with self.assertRaisesRegex(ValueError, 'differs from replayed'):
                verify.verify_package(self.output)
            unpublished = self.root / 'unpublished'
            with self.assertRaisesRegex(ValueError, 'differs from replayed'):
                package.package(self.source, unpublished, self.root / 'no-policy.json')
            self.assertFalse(unpublished.exists())

    def test_artifact_identity_requires_full_qualified_population(self):
        for changes in ({'profile': 'smoke'}, {'status': 'failed'}, {'status': 'complete'},
                        {'population_complete': False}, {'population_complete': 1},
                        {'full_comparison_qualified': False}, {'full_comparison_qualified': 1}):
            with self.subTest(changes=changes):
                value = {**self.aggregate, **changes}
                (self.source / 'aggregate.json').write_bytes(verify.canonical(value))
                with patch.object(verify, 'validate_artifact_identity_suite', return_value=value):
                    with self.assertRaisesRegex(ValueError, 'qualified full comparison'):
                        verify.verify_artifact_identity(self.source)

    def test_artifact_identity_missing_suite_fails_even_shape_only(self):
        (self.source / 'suite.json').unlink()
        self.archive()
        with self.assertRaisesRegex(ValueError, 'omits suite'):
            verify.verify_package(self.output, replay=False)

    def test_artifact_identity_preserves_archive_byte_bounds_and_outer_hash_checks(self):
        self.archive()
        with patch.object(verify, 'MAX_COMPRESSED', 1):
            with self.assertRaisesRegex(ValueError, 'exceeds bound'):
                verify.verify_package(self.output, replay=False)
        (self.output / 'aggregate.json').write_bytes(b'{"forged":true}')
        with self.assertRaisesRegex(ValueError, 'outer evidence'):
            verify.verify_package(self.output, replay=False)

    def test_rehashed_failed_collection_cannot_be_promoted_by_forged_aggregate(self):
        from tools.artifact_identity_runner.model import suite
        # Real replay, no mocks: even with valid new archive/member checksums,
        # the declared passed aggregate cannot conceal a failed collection.
        failed = suite('full', 'a' * 40, 'b' * 40)
        (self.source / 'suite.json').write_bytes(verify.canonical(failed))
        self.archive()
        verify.verify_package(self.output, replay=False)
        with self.assertRaisesRegex(ValueError, 'collection-did-not-pass'):
            verify.verify_package(self.output)
        unpublished = self.root / 'unpublished'
        with self.assertRaisesRegex(ValueError, 'collection-did-not-pass'):
            package.package(self.source, unpublished, self.root / 'no-policy.json')
        self.assertFalse(unpublished.exists())


if __name__ == '__main__':
    unittest.main()

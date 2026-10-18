"""Closed routing controls; mocked report identities do not qualify native signing."""
import copy
import json
from contextlib import contextmanager
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tools.java_transaction_qualification import current_campaign, packaging
from tools.java_transaction_qualification.inputs import ComponentInput, digest


ROOT = Path(__file__).resolve().parents[2]
PACKET = 'docs/testing/evidence/java-current-http-refreshed-capture-2026-10-16.json'
MODE = 'fixture-sign-refreshed-current-java-inputs'
SOURCE = 'eba0d96e9439028aacd6c1f9a85d4ce0118a19bc'
PROFILE = 'qualified-http-v1:bb85705ae221db0b883cf8253e00ef1091b7ea70e768299bb14a2175286c4391'
NAMES = ('aggregate', 'put-once-legacy-v1', 'put-once-compatible-v2',
         'put-once-writer-v2', 'put-once-diagnostics')


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()


def captured_packet():
    return json.loads((ROOT / PACKET).read_bytes())


class RoutingFixture:
    """Only the unit oracle maps labeled bytes to captured report identities."""
    def __init__(self):
        self.packet = captured_packet()
        rows = self.packet['captures']['variants']
        self.reports = {name: ('mock-report:' + name).encode() for name in rows}
        self.identities = {self.reports[name]: row['materials']['report']['sha256']
                           for name, row in rows.items()}
        self.items = [SimpleNamespace(name=name, directory=Path('/mock-capture') / name,
                      compiler_source=SOURCE, component_digest=rows[name]['materials']['component']['sha256'])
                      for name in NAMES]
        self.reads = []
        self.packet_error = None
        self.packet_raw = None

    @contextmanager
    def observed(self):
        original = packaging.read_file

        def material(path, *args):
            if path.name == 'report.json':
                return self.reports[path.parent.name]
            self.reads.append(path.name)
            if path.name == Path(PACKET).name:
                if self.packet_error is not None:
                    raise self.packet_error
                return encoded(self.packet) if self.packet_raw is None else self.packet_raw
            return original(path, *args)

        def identity(raw):
            return self.identities[raw] if raw in self.identities else digest(raw)

        with patch.object(packaging, 'read_file', side_effect=material), \
                patch.object(packaging, 'digest', side_effect=identity):
            yield self


class RefreshedCurrentRouting(unittest.TestCase):
    def test_public_packet_preserves_six_components_and_separate_new_capture_identity(self):
        raw = (ROOT / PACKET).read_bytes()
        self.assertEqual(digest(raw), 'sha256:2027a62c2706e337b571dd0d3433d9d8546501e3ca33f5025703f6e1da677616')
        packet = json.loads(raw)
        prior = json.loads((ROOT / 'docs/testing/evidence/java-current-http-reconstructed-capture-2026-10-15.json').read_bytes())
        self.assertEqual(packet['captures']['sourceCommit'], SOURCE)
        self.assertEqual(packet['captures']['nativeIdempotencyProfile'], PROFILE)
        self.assertNotEqual(packet['captures']['nativeIdempotencyProfile'], prior['captures']['nativeIdempotencyProfile'])
        self.assertEqual(set(packet['captures']['variants']), set(NAMES) | {'forbidden-http'})
        for name, row in packet['captures']['variants'].items():
            self.assertEqual(row['materials']['component'], prior['captures']['variants'][name]['materials']['component'])
            self.assertEqual(row['materials']['compilerInputs'], prior['captures']['variants'][name]['materials']['compilerInputs'])
        for field in ('signingQualified', 'executionQualified', 'memoryExhaustionQualified', 'packagedDistributionQualified'):
            self.assertIs(packet[field], False)

    def test_new_named_report_map_is_distinct_from_each_old_closed_mode(self):
        expected = {name: row['materials']['report']['sha256'] for name, row in captured_packet()['captures']['variants'].items()
                    if name != 'forbidden-http'}
        for name in ('docs/development/phase4-handoffs/2026-10-12/pr970-current-post-evidence.json',
                     'docs/testing/evidence/java-current-rebuilt-capture-2026-10-13.json',
                     'docs/testing/evidence/java-current-fresh-http-capture-2026-10-13.json',
                     'docs/testing/evidence/java-current-native-memory-capture-2026-10-14.json',
                     'docs/testing/evidence/java-current-http-reconstructed-capture-2026-10-15.json'):
            packet = json.loads((ROOT / name).read_bytes())['captures']
            old = {variant: row['materials']['report']['sha256'] for variant, row in packet['variants'].items()
                   if variant != 'forbidden-http'}
            with self.subTest(packet=name):
                self.assertNotEqual(expected, old)

    def test_exact_new_set_selects_fixed_mode_without_reading_old_packets(self):
        fixture = RoutingFixture()
        for items in (fixture.items, list(reversed(fixture.items))):
            fixture.reads.clear()
            with fixture.observed():
                self.assertEqual(packaging.current_signing_mode(items), MODE)
            self.assertEqual(fixture.reads, [Path(PACKET).name])

    def test_all_five_old_modes_never_read_the_new_packet(self):
        from tools.tests.test_java_current_inputs import CurrentJavaNativeMemoryPackaging, CurrentJavaPackaging
        names, packets = CurrentJavaPackaging.signing_packets()
        old_source = '9bae83952d9513c965a88d375b2a533916a98473'
        for packet in packets.values():
            packet['captures']['sourceCommit'] = old_source
        _, native, filename, _ = CurrentJavaNativeMemoryPackaging().context()
        packets[filename] = native[filename]
        for prefix, mode, source in (
                ('historical:', 'fixture-sign-current-java-inputs', old_source),
                ('', 'fixture-sign-rebuilt-current-java-inputs', old_source),
                ('fresh:', 'fixture-sign-fresh-http-current-java-inputs', old_source),
                ('native-memory:', 'fixture-sign-native-memory-current-java-inputs', SOURCE)):
            reads = []

            def material(path, *_args):
                if path.name == 'report.json':
                    return (prefix + path.parent.name).encode()
                reads.append(path.name)
                return encoded(packets[path.name])

            items = [SimpleNamespace(name=name, directory=Path('/old-capture') / name,
                                     compiler_source=source) for name in names]
            with self.subTest(mode=mode), patch.object(packaging, 'read_file', side_effect=material):
                self.assertEqual(packaging.current_signing_mode(items), mode)
            self.assertNotIn(Path(PACKET).name, reads)
        from tools.tests.test_java_reconstructed_current_routing import RoutingFixture as PriorFixture
        prior = PriorFixture()
        with prior.observed():
            self.assertEqual(packaging.current_signing_mode(prior.items),
                             'fixture-sign-reconstructed-current-java-inputs')
        self.assertNotIn(Path(PACKET).name, prior.reads)

    def test_partial_duplicate_or_diagnostic_substitution_refuses(self):
        for change in ('empty', 'partial', 'extra', 'duplicate', 'forbidden-instead-of-diagnostic'):
            fixture = RoutingFixture()
            if change == 'empty': fixture.items.clear()
            elif change == 'partial': fixture.items.pop()
            elif change == 'extra': fixture.items.append(fixture.items[0])
            elif change == 'duplicate': fixture.items[-1] = fixture.items[0]
            else: fixture.items[-1].name = 'forbidden-http'
            with self.subTest(change=change), fixture.observed(), self.assertRaises(ValueError):
                packaging.current_signing_mode(fixture.items)

    def test_single_old_or_unknown_report_cannot_mix_with_the_new_set(self):
        old = json.loads((ROOT / 'docs/testing/evidence/java-current-http-reconstructed-capture-2026-10-15.json').read_bytes())['captures']['variants']
        for name in NAMES:
            for wrong in (old[name]['materials']['report']['sha256'], 'sha256:' + 'f' * 64):
                fixture = RoutingFixture()
                fixture.identities[fixture.reports[name]] = wrong
                with self.subTest(variant=name, report=wrong), fixture.observed(), self.assertRaises(ValueError):
                    packaging.current_signing_mode(fixture.items)
                self.assertNotIn(Path(PACKET).name, fixture.reads)

    def test_each_selected_source_and_component_remains_exact(self):
        for index in range(len(NAMES)):
            for field, wrong in (('compiler_source', '9bae83952d9513c965a88d375b2a533916a98473'),
                                 ('component_digest', 'sha256:' + 'f' * 64)):
                fixture = RoutingFixture()
                setattr(fixture.items[index], field, wrong)
                with self.subTest(variant=NAMES[index], field=field), fixture.observed(), self.assertRaises(ValueError):
                    packaging.current_signing_mode(fixture.items)
                self.assertEqual(fixture.reads, [Path(PACKET).name])

    def test_changed_packet_source_profile_report_or_component_has_no_old_fallback(self):
        for change in ('source', 'profile', 'report', 'component'):
            fixture = RoutingFixture()
            captures = fixture.packet['captures']
            if change == 'source': captures['sourceCommit'] = 'f' * 40
            elif change == 'profile': captures['nativeIdempotencyProfile'] = 'qualified-http-v1:' + 'f' * 64
            else: captures['variants']['aggregate']['materials'][change]['sha256'] = 'sha256:' + 'f' * 64
            with self.subTest(change=change), fixture.observed(), self.assertRaises(ValueError):
                packaging.current_signing_mode(fixture.items)
            self.assertEqual(fixture.reads, [Path(PACKET).name])

    def test_missing_malformed_or_incomplete_new_packet_is_fatal(self):
        for change, error in (('missing', FileNotFoundError), ('malformed', ValueError),
                              ('captures', KeyError), ('report-row', ValueError), ('component', KeyError)):
            fixture = RoutingFixture()
            if change == 'missing': fixture.packet_error = FileNotFoundError('missing captured packet')
            elif change == 'malformed': fixture.packet_raw = b'{'
            elif change == 'captures': fixture.packet.pop('captures')
            elif change == 'report-row': fixture.packet['captures']['variants'].pop('aggregate')
            else: fixture.packet['captures']['variants']['aggregate']['materials'].pop('component')
            with self.subTest(change=change), fixture.observed(), self.assertRaises(error):
                packaging.current_signing_mode(fixture.items)
            self.assertEqual(fixture.reads, [Path(PACKET).name])

    def test_all_six_selection_rows_remain_explicit_and_refuse_added_authority(self):
        rows = [{'sourceCommit': SOURCE, 'variant': name,
                 'reportDigest': row['materials']['report']['sha256'],
                 'componentDigest': row['materials']['component']['sha256'],
                 'compilerInputsDigest': row['materials']['compilerInputs']['sha256']}
                for name, row in captured_packet()['captures']['variants'].items()]
        document = {'schemaVersion': 'latent.java.current-campaign-selections.v1', 'selections': rows}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            path = root / 'selection.json'
            raw = encoded(document)
            path.write_bytes(raw)
            selected = current_campaign.selections(root, path, digest(raw))
            self.assertEqual({row.variant for _, row in selected}, set(NAMES) | {'forbidden-http'})
            for change in ('missing', 'duplicate', 'source', 'component', 'authority'):
                value = copy.deepcopy(document)
                if change == 'missing': value['selections'].pop()
                elif change == 'duplicate': value['selections'][1] = value['selections'][0]
                elif change == 'source': value['selections'][0]['sourceCommit'] = 'f' * 40
                elif change == 'component': value['selections'][1]['componentDigest'] = value['selections'][0]['componentDigest']
                else: value['selections'][0]['signedExecutionQualified'] = True
                raw = encoded(value)
                path.write_bytes(raw)
                with self.subTest(change=change), self.assertRaises(ValueError):
                    current_campaign.selections(root, path, digest(raw))

    def test_terminal_pending_and_early_identity_bind_the_new_packet_bytes(self):
        from tools import run_java_early_http_qualification as early
        from tools import run_java_pending_recovery_qualification as pending
        from tools import run_java_transaction_http_qualification as terminal
        self.assertEqual(terminal.COLLECTORS.count(PACKET), 1)
        old_packet = 'docs/testing/evidence/java-current-http-reconstructed-capture-2026-10-15.json'
        self.assertLess(terminal.COLLECTORS.index(PACKET), terminal.COLLECTORS.index(old_packet))
        self.assertEqual(terminal.COLLECTORS[-1], old_packet)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in dict.fromkeys(terminal.COLLECTORS + pending.EXTRA_COLLECTORS + early.EXTRA_COLLECTORS):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((ROOT / name).read_bytes())
            with patch.object(terminal, '__file__', str(root / 'tools/run_java_transaction_http_qualification.py')), \
                    patch.object(pending, '__file__', str(root / 'tools/run_java_pending_recovery_qualification.py')), \
                    patch.object(early, '__file__', str(root / 'tools/run_java_early_http_qualification.py')):
                before = [module.collector_identity() for module in (terminal, pending, early)]
                path = root / PACKET
                path.write_bytes(path.read_bytes() + b'\n')
                after = [module.collector_identity() for module in (terminal, pending, early)]
            for original, changed in zip(before, after):
                self.assertNotEqual(original[PACKET], changed[PACKET])
                self.assertEqual({k: v for k, v in original.items() if k != PACKET},
                                 {k: v for k, v in changed.items() if k != PACKET})

    def package_observation(self, *, refused=False):
        names = (*NAMES, 'forbidden-http')
        items = [ComponentInput(name, Path('/mock-package') / name, digest(name.encode()),
                 'companion', 'source', SOURCE, 'abi', None) for name in names]
        accepted = items[:-1]
        surface = {'world': packaging.WORLD, 'imports': sorted({
            'latent:state/key-value@0.2.0', 'latent:intents/staging@0.1.0', 'latent:http/client@0.2.0',
            'latent:clock/monotonic@0.1.0', 'latent:clock/wall@0.1.0'}),
            'exports': ['examples:transactional-aggregate/api@1.0.0']}

        def material(path, *_args):
            if path.name == 'surface.json': return encoded(surface)
            if path.name == 'release-set.json': return encoded({'schemaVersion': 'latent.component.signing-fixture.v1',
                'trust': 'ephemeral-native-package-test-only',
                'releases': [{'componentDigest': item.component_digest} for item in accepted]})
            if path.name == 'source-inputs.json': return b'inventory'
            if path.name == 'component.wasm': return path.parent.name.encode()
            raise AssertionError('unexpected mock packaging material')

        command = SimpleNamespace(records=[], run=Mock())
        receipts = []
        with patch.object(packaging, 'fresh', side_effect=lambda path: path), \
                patch.object(packaging, 'build_environment', return_value={}), \
                patch.object(packaging, 'Commands', return_value=command), \
                patch.object(packaging, 'file_identity', return_value={'test': 'mock-native-tool'}), \
                patch.object(packaging, 'prepare'), patch.object(packaging, 'read_file', side_effect=material), \
                patch.object(packaging, 'snapshot', return_value={}), patch.object(packaging, 'inventory', return_value=b'inventory'), \
                patch.object(packaging, 'write_json', side_effect=lambda path, value: receipts.append((path, copy.deepcopy(value)))), \
                patch.object(packaging, 'current_signing_mode', return_value=MODE,
                    side_effect=ValueError('closed identity refusal') if refused else None) as selected:
            if refused:
                with self.assertRaises(ValueError):
                    packaging._package_items(items, Path('/output'), Path('/contracts'), Path('/signer'), timeout=600, compiler_source=SOURCE)
            else:
                self.assertEqual(packaging._package_items(items, Path('/output'), Path('/contracts'), Path('/signer'),
                    timeout=600, compiler_source=SOURCE), Path('/output/signed'))
        selected.assert_called_once_with(accepted)
        return command, receipts

    def test_package_issues_one_fixed_five_input_signer_call_and_keeps_forbidden_unsigned(self):
        command, receipts = self.package_observation()
        command.run.assert_called_once_with(MODE, Path('/signer'), MODE, Path('/output/signed'), SOURCE,
                                           *(Path('/output') / name for name in NAMES))
        controls = [value for path, value in receipts if path.name == 'current-preparation-control.json']
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]['variant'], 'forbidden-http')
        for field in ('signed', 'executionAuthorized', 'requestDispatched', 'immediateHttpDenialQualified', 'signedNodeExecutionQualified'):
            self.assertIs(controls[0][field], False)
        self.assertIs(receipts[-1][1]['passed'], True)

    def test_refused_capture_identity_cannot_issue_any_signer_command(self):
        command, receipts = self.package_observation(refused=True)
        command.run.assert_not_called()
        self.assertIs(receipts[-1][1]['passed'], False)


if __name__ == '__main__':
    unittest.main()

"""Validate and present original observations without invoking or retrying guests."""
import copy
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools import guest_compatibility_outcomes as outcomes
from tools.dev_workflow.common import DevError, digest, encode


def selected():
    report = compatibility.report('java', digest(b'compiler inventory'), digest(b'component'),
        'lsf-host-abi-phase3-v4', [], [])
    return report, context.create(report, [], {'state': 'absent'})


def observation(reason=12, code='resource-exhausted'):
    return {'category': 'platform-failure', 'outcomeKnown': True, 'error': {'code': code,
        'message': 'private error', 'details': [{'kind': 'activation.diagnostic.v1',
        'fields': {'stage': '5', 'reason': str(reason)}}]},
        'data': {'payload': 'private source', 'consumption': {'cpuFuel': str(2**64 - 1), 'childCalls': 2}}}


def capture(*, bound=True):
    report, selected_context = selected()
    collector = outcomes.Capture(digest(b'frontend source'), report['componentDigest'], selected_context if bound else None)
    collector.observe('original-case', observation(), True)
    return collector.snapshot(), report, selected_context


def rehash(value):
    value['identity'] = digest(encode({key: item for key, item in value.items() if key != 'identity'}))
    return value


class OutcomeReader(unittest.TestCase):
    def test_observed_lifecycle_disposition_round_trips_for_every_language_without_cause_claims(self):
        for language in compatibility.LANGUAGES:
            with self.subTest(language=language):
                report = compatibility.report(language, digest(b'source'), digest(b'component'),
                    'lsf-host-abi-phase3-v4', [], [])
                selected_context = context.create(report, [], {'state': 'absent'})
                collector = outcomes.Capture(digest(b'frontend'), report['componentDigest'], selected_context)
                result = observation(code='guest-trap')
                result['error']['details'] = [{'kind': 'activation.guest-trap',
                    'fields': {'code': 'runtime-lifecycle-unproven', 'cell_id': 'private-cell'}}]
                original = copy.deepcopy(result)
                collector.observe('lifecycle-refusal', result, True)
                value = outcomes.read(encode(collector.snapshot()), report=report, selected_context=selected_context)
                row = value['cases'][0]
                self.assertEqual(row['guestTrapCode'], 'runtime-lifecycle-unproven')
                self.assertEqual((row['cause'], row['resourceDimension'], row['physicalRetirement']),
                                 ('unknown', 'unknown', 'unproven'))
                self.assertEqual((value['libraryReachability'], value['workerDrain'], value['retrySafety']),
                                 ('unknown', 'unproven', 'unknown'))
                self.assertIn('runtime disposition runtime-lifecycle-unproven', outcomes.present(value))
                self.assertNotIn('private-', encode(value).decode())
                self.assertEqual(result, original)

    def test_lifecycle_disposition_cannot_certify_a_cause_or_accept_unknown_tokens(self):
        report, selected_context = selected()
        collector = outcomes.Capture(digest(b'frontend'), report['componentDigest'], selected_context)
        result = observation(code='guest-trap')
        detail = {'kind': 'activation.guest-trap', 'fields': {'code': 'runtime-lifecycle-unproven'}}
        result['error']['details'] = [detail]
        collector.observe('lifecycle-refusal', result, True)
        value = collector.snapshot()
        for field, claim in (('cause', 'lifecycle-unproven'), ('resourceDimension', 'timers'),
                             ('physicalRetirement', 'reaped'), ('guestTrapCode', 'private-token')):
            changed = copy.deepcopy(value); changed['cases'][0][field] = claim; rehash(changed)
            with self.subTest(field=field), self.assertRaises(DevError): outcomes.validate(changed)
        for details in ([detail, detail], [detail] * 17,
                        [{'kind': 'activation.guest-trap', 'fields': {'code': 'private-token'}}]):
            result['error']['details'] = details
            projected = outcomes.original(result)
            self.assertNotIn('guestTrapCode', projected)
            self.assertTrue(projected['trapDetailsUnavailable'])
            self.assertEqual((projected['cause'], projected['resourceDimension']), ('unknown', 'unknown'))
            self.assertNotIn('private-token', encode(projected).decode())

    def test_round_trip_binds_component_report_context_and_distinct_frontend_source(self):
        value, report, selected_context = capture()
        self.assertEqual(outcomes.read(encode(value), report=report, selected_context=selected_context), value)
        self.assertNotEqual(value['frontendSourceDigest'], value['compatibilitySourceDigest'])
        self.assertEqual(value['cases'][0]['consumption'], {'cpuFuel': str(2**64 - 1), 'childCalls': '2'})

    def test_node_resource_exhaustion_preserves_unknown_dimension_and_retirement(self):
        value, _, _ = capture()
        row = value['cases'][0]
        self.assertEqual((row['cause'], row['resourceDimension'], row['physicalRetirement']),
                         ('resource-exhausted', 'unknown', 'unproven'))
        self.assertNotIn('private', encode(value).decode())

    def test_stale_component_report_and_runtime_context_cannot_borrow_outcomes(self):
        value, report, selected_context = capture()
        wrong_report = compatibility.report('java', digest(b'other source'), report['componentDigest'],
            report['runtimeProfile'], [], [])
        wrong_component = compatibility.report('java', report['sourceDigest'], digest(b'other component'),
            report['runtimeProfile'], [], [])
        wrong_context = context.create(report, [context.material('compiler', 'other', digest(b'other compiler'))], {'state': 'absent'})
        for bindings in ({'report': wrong_report}, {'report': wrong_component}, {'selected_context': wrong_context}):
            with self.subTest(bindings=bindings), self.assertRaisesRegex(DevError, 'stale-'):
                outcomes.validate(value, **bindings)

    def test_absent_and_invalid_context_remain_visible_without_invented_links(self):
        value, report, selected_context = capture(bound=False)
        self.assertEqual(outcomes.read(encode(value), report=report, selected_context=selected_context)['contextState'], 'absent')
        value['contextState'] = 'invalid-present'; rehash(value)
        self.assertEqual(outcomes.read(encode(value))['contextState'], 'invalid-present')
        value['contextIdentity'] = digest(b'invented'); rehash(value)
        with self.assertRaisesRegex(DevError, 'context-links'): outcomes.validate(value)

    def test_rehashed_cause_or_dimension_cannot_disagree_with_numeric_evidence(self):
        value, _, _ = capture()
        for field, claim in (('cause', 'denied-grant'), ('resourceDimension', 'timers')):
            changed = copy.deepcopy(value); changed['cases'][0][field] = claim; rehash(changed)
            with self.subTest(field=field), self.assertRaisesRegex(DevError, 'cause-evidence'):
                outcomes.validate(changed)

    def test_rehashed_support_retirement_and_retry_claims_are_rejected(self):
        value, _, _ = capture()
        for field, claim in (('authority', 'granted'), ('workerDrain', 'complete'), ('retrySafety', 'safe'),
                             ('libraryReachability', 'proven'), ('initialization', 'executed')):
            changed = copy.deepcopy(value); changed[field] = claim; rehash(changed)
            with self.subTest(field=field), self.assertRaisesRegex(DevError, 'cannot-certify'):
                outcomes.validate(changed)
        value['cases'][0]['physicalRetirement'] = 'reaped'; rehash(value)
        with self.assertRaisesRegex(DevError, 'retirement-evidence'): outcomes.validate(value)

    def test_hostile_or_malformed_row_fields_fail_closed(self):
        value, _, _ = capture()
        for field, hostile in (('rawMessage', 'private payload'), ('case', '/home/private'),
            ('errorCode', 'private-code'), ('consumption', {'cpuFuel': None}),
            ('consumption', {'childCalls': str(2**32)}), ('targetMatches', 'true'),
            ('activationDiagnostic', {'state': 'observed', 'fields': {'stage': '5', 'reason': '17'}}),
            ('activationDiagnostic', {'state': 'absent', 'fields': {}}),
            ('invalidConsumptionFields', ['cpuFuel']), ('guestTrapCode', 'guest-runtime-error'),
            ('admissionCurrentnessReason', 'private-reason')):
            changed = copy.deepcopy(value); changed['cases'][0][field] = hostile; rehash(changed)
            with self.subTest(field=field, hostile=hostile), self.assertRaises(DevError): outcomes.validate(changed)

    def test_reader_bounds_duplicates_and_unbound_identity_fail_closed(self):
        value, _, _ = capture()
        for raw in (b'x' * (outcomes.MAX_BYTES + 1), b'{"schemaVersion":1,"schemaVersion":2}'):
            with self.assertRaises(DevError): outcomes.read(raw)
        value['omittedCases'] = 2
        with self.assertRaisesRegex(DevError, 'identity-or-size'): outcomes.validate(value)
        value['cases'] *= 129; rehash(value)
        with self.assertRaisesRegex(DevError, 'case-limit'): outcomes.validate(value)

    def test_all_original_projection_shapes_round_trip_without_enriching_results(self):
        report, selected_context = selected()
        collector = outcomes.Capture(digest(b'frontend'), report['componentDigest'], selected_context)
        inputs = [None, {}, {'error': {'code': 'private-code'}}, observation(9), observation(10), observation(11),
                  observation(15, 'cancelled'), observation(12, 'guest-trap')]
        inputs[-1]['error']['details'].append({'kind': 'activation.guest-trap', 'fields': {'code': 'guest-runtime-error'}})
        inputs[-1]['error']['details'].append({'kind': 'admission.currentness', 'fields': {'reason': 'admission-owner-retired'}})
        before = copy.deepcopy(inputs)
        for index, row in enumerate(inputs): collector.observe(f'case-{index}', row, False)
        self.assertEqual(outcomes.read(encode(collector.snapshot()))['cases'][3]['cause'], 'unknown')
        self.assertEqual(inputs, before)


class OutcomePresentation(unittest.TestCase):
    def test_presentation_names_observed_failures_and_omissions_without_success_claims(self):
        value, _, _ = capture()
        value['omittedCases'] = 3; value['cases'][0]['targetMatches'] = False; rehash(value)
        text = outcomes.present(value)
        self.assertIn('cause resource-exhausted', text)
        self.assertIn('observations omitted: 3', text)
        self.assertIn('target differs', text)
        self.assertIn('physical retirement is unproven', text)
        self.assertNotIn('private', text)

    def test_cli_validates_all_sidecars_before_printing_any_output(self):
        value, report, selected_context = capture()
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            for name, item in (('report', report), ('context', selected_context), ('outcomes', value)):
                (output / name).write_bytes(encode(item))
            arguments = ['compatibility', str(output / 'report'), '--context', str(output / 'context'),
                         '--outcomes', str(output / 'outcomes')]
            with patch('sys.argv', arguments), patch('sys.stdout', new_callable=io.StringIO) as stdout:
                self.assertEqual(compatibility.main(), 0)
                self.assertIn('original-case: cause resource-exhausted', stdout.getvalue())
            value['componentDigest'] = digest(b'other component'); rehash(value)
            (output / 'outcomes').write_bytes(encode(value))
            with patch('sys.argv', arguments), patch('sys.stdout', new_callable=io.StringIO) as stdout:
                with self.assertRaisesRegex(DevError, 'stale-component'): compatibility.main()
                self.assertEqual(stdout.getvalue(), '')

    def test_json_output_cannot_silently_ignore_requested_outcome_observations(self):
        with patch('sys.argv', ['compatibility', 'unused', '--json', '--outcomes', 'unused']):
            with self.assertRaisesRegex(DevError, 'requires-text'): compatibility.main()


if __name__ == '__main__': unittest.main()

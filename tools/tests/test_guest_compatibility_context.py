"""Actual source/receipt validators; no guest-runtime qualification claims."""
import copy
from pathlib import Path
import tempfile
import unittest
import os
from unittest.mock import patch

from tools import guest_compatibility as compatibility
from tools import guest_compatibility_context as context
from tools import guest_compatibility_context_build as builder
from tools import guest_compatibility_outcomes as outcomes
from tools.dev_workflow.common import DevError, digest, encode

SOURCE = encode({'fixture': 'source inventory'})
COMPONENT = b'actual component identity fixture'
SDK = encode({'language': 'java'})


def report(language='java'):
    return compatibility.report(language, digest(SOURCE), digest(COMPONENT), 'lsf-host-abi-phase3-v4', [],
        [compatibility.finding('unresolved-behavior', 'initialization', 'not-evaluated')])


class BuildContext(unittest.TestCase):
    def setUp(self):
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.output = Path(owned.name)
        self.original = encode(report())
        (self.output / 'compatibility-report.json').write_bytes(self.original)
        self.materials = [{'name': 'build-recipe', 'digest': digest(b'recipe'), 'size': 6}]

    def receipt(self, filename, name, value):
        raw = encode(value); (self.output / filename).write_bytes(raw)
        self.materials.append({'name': name, 'digest': digest(raw), 'size': len(raw)})
        return raw

    def finish(self):
        return builder.finish(self.output, {'sdk-lock.json': SDK}, SOURCE, COMPONENT, self.materials)

    def test_immutable_v1_report_bytes_and_identity_survive_context_emission(self):
        value = self.finish()
        self.assertEqual((self.output / 'compatibility-report.json').read_bytes(), self.original)
        self.assertEqual(value['compatibilityReportIdentity'], report()['identity'])
        self.assertEqual(value['standardRuntime']['state'], 'absent')
        self.assertEqual((value['reachability'], value['initialization'], value['workerDrain']), ('unknown', 'unknown', 'unproven'))

    def test_owner_selected_runtime_identity_does_not_certify_any_api(self):
        raw = self.receipt('runtime-profile.json', 'runtime-profile', {'profile': 'teavm-activation-fibers-v1', 'qualification': 'qualified'})
        value = self.finish()
        self.assertEqual(value['standardRuntime']['receiptDigest'], digest(raw))
        self.assertEqual(value['standardRuntime']['state'], 'selected-unqualified')
        self.assertEqual(value['qualification'], 'unknown')
        self.assertIn('qualification unknown', context.present(value))

    def test_changed_runtime_receipt_is_denied_after_material_capture(self):
        self.receipt('runtime-profile.json', 'runtime-profile', {'profile': 'old'})
        (self.output / 'runtime-profile.json').write_bytes(encode({'profile': 'new'}))
        with self.assertRaisesRegex(DevError, 'stale-or-unbound-receipt'): self.finish()
        self.assertEqual((self.output / 'compatibility-report.json').read_bytes(), self.original)

    def test_unbound_runtime_receipt_is_denied(self):
        (self.output / 'runtime-profile.json').write_bytes(encode({'profile': 'unbound'}))
        with self.assertRaisesRegex(DevError, 'unbound'): self.finish()

    def test_original_transformed_patch_and_recipe_configuration_are_distinct(self):
        patch = {'name': 'owned-port', 'profile': 'owned-runtime-v1',
                 'original': {'digest': digest(b'original')}, 'selected': {'digest': digest(b'derived')},
                 'selection': {'configuration': 'finite-transform', 'privateUrl': 'https://secret.invalid/token'}}
        self.receipt('compiler-patches.json', 'automatic-compiler-patches', {'formatVersion': 1, 'patches': [patch]})
        value = self.finish(); material = next(row for row in value['materials'] if row['kind'] == 'patch')
        self.assertEqual(material['originalDigest'], digest(b'original'))
        self.assertEqual(material['digest'], digest(b'derived'))
        self.assertNotIn(material['transformDigest'], {material['originalDigest'], material['digest']})
        self.assertNotIn('secret.invalid', encode(value).decode())

    def test_changed_patch_receipt_is_denied(self):
        self.receipt('compiler-patches.json', 'automatic-compiler-patches', {'formatVersion': 1, 'patches': []})
        (self.output / 'compiler-patches.json').write_bytes(encode({'formatVersion': 1, 'patches': [{'name': 'replacement'}]}))
        with self.assertRaisesRegex(DevError, 'stale-or-unbound'): self.finish()

    def test_missing_patch_preimage_is_denied(self):
        self.receipt('compiler-patches.json', 'automatic-compiler-patches', {'formatVersion': 1, 'patches': [{'name': 'missing'}]})
        with self.assertRaisesRegex(DevError, 'patch-identity'): self.finish()

    def test_changed_source_or_component_cannot_borrow_old_report(self):
        for source, component in ((b'changed', COMPONENT), (SOURCE, b'changed')):
            with self.subTest(source=source):
                with self.assertRaisesRegex(DevError, 'stale-build'):
                    builder.finish(self.output, {'sdk-lock.json': SDK}, source, component, self.materials)

    def test_freshly_rehashed_context_still_requires_current_source_and_materials(self):
        value = self.finish()
        with self.assertRaisesRegex(DevError, 'stale-source'): context.validate(value, source=digest(b'new'))
        with self.assertRaisesRegex(DevError, 'stale-runtime-or-patch'): context.validate(value, expected_materials=[])
        with self.assertRaisesRegex(DevError, 'stale-component'): context.validate(value, component=digest(b'new'))

    def test_metadata_tokens_reject_credentials_and_host_paths(self):
        for token in ('https://user:password@host', '../secret', 'C:\\secret', 'token?password=1'):
            with self.subTest(token=token), self.assertRaises(DevError): context.material('runtime', token, digest(b'bytes'))

    def test_material_and_document_limits_are_fail_closed(self):
        materials = [context.material('compiler', 'tool' + str(index), digest(str(index).encode())) for index in range(65)]
        with self.assertRaisesRegex(DevError, 'material-limit'): context.create(report(), materials, {'state': 'absent'})
        with self.assertRaises(DevError): context.read(b'x' * (context.MAX_BYTES + 1))


def result(reason=None, *, code='resource-exhausted', fields=None):
    value = {'category': 'platform-failure', 'outcomeKnown': True,
             'error': {'code': code}, 'data': {'payload': {'private': 'secret'}, 'consumption': {'cpuFuel': '18446744073709551615'}}}
    if reason is not None:
        value['error']['details'] = [{'kind': 'activation.diagnostic.v1', 'fields': {'stage': '2', 'reason': str(reason), **(fields or {})}}]
    return value


class OriginalOutcome(unittest.TestCase):
    def test_queue_pressure_remains_unknown_resource_dimension(self):
        value = outcomes.original(result(9))
        self.assertEqual(value['activationDiagnostic']['state'], 'observed')
        self.assertEqual((value['cause'], value['resourceDimension']), ('unknown', 'unknown'))

    def test_coarse_exhaustion_unimplemented_and_guest_traps_do_not_prove_unsupported_operation(self):
        for code in ('resource-exhausted', 'unimplemented', 'guest-trap'):
            value = outcomes.original(result(code=code))
            self.assertEqual(value['cause'], 'unknown')
            self.assertEqual(value['libraryReachability'], 'unknown')

    def test_absent_invalid_and_valid_diagnostics_stay_distinct(self):
        self.assertEqual(outcomes.original(result())['activationDiagnostic']['state'], 'absent')
        self.assertEqual(outcomes.original(result(17))['activationDiagnostic']['state'], 'invalid-present')
        self.assertEqual(outcomes.original(result(10))['activationDiagnostic']['state'], 'observed')

    def test_closed_enum_numeric_and_digest_projection_rejects_hostile_fields(self):
        for fields in ({'unknown': 'private'}, {'profile': '3'}, {'configured_bound': '-1'},
                       {'fixed_bytes': str(2**64)}, {'profile_digest': 'A' * 64}, {'stage': True}):
            with self.subTest(fields=fields):
                self.assertEqual(outcomes.original(result(10, fields=fields))['activationDiagnostic']['state'], 'invalid-present')

    def test_maximum_unsigned_numeric_values_are_preserved_without_payloads(self):
        value = outcomes.original(result(10, fields={'configured_bound': str(2**64-1), 'profile': '2', 'profile_digest': 'f'*64}))
        self.assertEqual(value['activationDiagnostic']['fields']['configured_bound'], str(2**64-1))
        self.assertEqual(value['consumption']['cpuFuel'], str(2**64-1))
        self.assertNotIn('secret', encode(value).decode())

    def test_only_explicit_named_memory_and_fuel_reasons_name_dimensions(self):
        for reason, dimension in ((10, 'guest-memory'), (11, 'fuel'), (12, 'unknown')):
            self.assertEqual(outcomes.original(result(reason))['resourceDimension'], dimension)

    def test_client_reaping_and_cancel_ack_do_not_certify_worker_retirement(self):
        capture = outcomes.Capture(digest(b'frontend'), digest(COMPONENT))
        capture.observe('cancel', result(15), True)
        row = capture.snapshot()['cases'][0]
        self.assertEqual(row['clientProcess'], 'reaped')
        self.assertEqual(row['cause'], 'cancelled')
        self.assertEqual(row['physicalRetirement'], 'unproven')
        self.assertEqual(capture.snapshot()['workerDrain'], 'unproven')

    def test_frontend_and_compatibility_source_identities_remain_separate(self):
        selected = context.create(report(), [], {'state': 'absent'})
        capture = outcomes.Capture(digest(b'frontend snapshot'), digest(COMPONENT), selected)
        capture.observe('original', result(8), True)
        value = capture.snapshot()
        self.assertNotEqual(value['frontendSourceDigest'], value['compatibilitySourceDigest'])
        self.assertEqual(value['componentDigest'], digest(COMPONENT))
        self.assertEqual(value['cases'][0]['cause'], 'denied-grant')
        self.assertEqual(value['retrySafety'], 'unknown')

    def test_stale_context_is_invalid_present_never_applied_to_actual_result(self):
        selected = context.create(report(), [], {'state': 'absent'})
        capture = outcomes.Capture(digest(b'frontend'), digest(b'other component'), selected)
        self.assertEqual(capture.snapshot()['contextState'], 'invalid-present')

    def test_finite_case_omissions_do_not_change_original_results(self):
        capture = outcomes.Capture(digest(b'frontend'), digest(COMPONENT)); original = result(9); before = copy.deepcopy(original)
        for _ in range(130): capture.observe('case', original, False)
        value = capture.snapshot()
        self.assertEqual(len(value['cases']), 128); self.assertEqual(value['omittedCases'], 2)
        self.assertLessEqual(len(encode(value)), 128 * 1024); self.assertEqual(original, before)

    def test_private_error_codes_are_redacted_as_invalid_present(self):
        value = outcomes.original(result(code='https://credential:secret@host'))
        self.assertEqual(value['errorCodeState'], 'invalid-present')
        self.assertNotIn('secret', encode(value).decode())

    @unittest.skipUnless(os.name == 'posix', 'real private scenario state requires Linux')
    def test_existing_failed_scenario_keeps_one_original_invoke_and_adds_bound_sidecar(self):
        from tools.tests.test_dev_node_diagnostics import ProbeIntegration
        capture = outcomes.Capture(digest(b'original frontend'), digest(COMPONENT))
        with patch.object(outcomes, 'from_build', return_value=capture):
            # Retain all original failed-assertion/client-ownership checks,
            # including its exact once-only invocation assertion.
            ProbeIntegration('test_shared_scenario_observes_the_original_result_without_changing_failed_assertion').test_shared_scenario_observes_the_original_result_without_changing_failed_assertion()
        value = capture.snapshot()
        self.assertEqual(len(value['cases']), 1)
        self.assertEqual(value['cases'][0]['guestTrapCode'], 'guest-runtime-error')
        self.assertEqual(value['cases'][0]['physicalRetirement'], 'unproven')
        self.assertEqual(value['frontendSourceDigest'], digest(b'original frontend'))
        self.assertNotIn('private-provider-message', encode(value).decode())


if __name__ == '__main__': unittest.main()

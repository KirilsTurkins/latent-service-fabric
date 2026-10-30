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

    def test_current_java_material_binds_runtime_bytes_without_certifying_execution(self):
        raw = self.receipt('runtime-profile.json', 'java-runtime-profile', {'profile': 'teavm-activation-fibers-v1'})
        value = self.finish()
        self.assertEqual(value['standardRuntime']['receiptDigest'], digest(raw))
        self.assertEqual(value['standardRuntime']['state'], 'selected-unqualified')
        (self.output / 'runtime-profile.json').write_bytes(encode({'profile': 'changed'}))
        with self.assertRaisesRegex(DevError, 'stale-or-unbound-receipt'):
            self.finish()

    def test_java_runtime_material_cannot_be_ambiguous(self):
        self.receipt('runtime-profile.json', 'java-runtime-profile', {'profile': 'teavm-activation-fibers-v1'})
        self.materials.append({'name': 'runtime-profile', 'digest': digest(b'other'), 'size': 5})
        with self.assertRaisesRegex(DevError, 'ambiguous-runtime-material'):
            self.finish()

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
        self.assertEqual(outcomes.original(result(27))['activationDiagnostic']['state'], 'invalid-present')
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


class TypeScriptNetContext(unittest.TestCase):
    """Actual build/context readers with source-bound finite Socket receipts."""

    def setUp(self):
        from tools.typescript_guest import net_profile, runtime_profile
        from tools.rust_capsule_project import ROOT, inventory, read_file
        from tools import guest_runtime_receipts
        owned = tempfile.TemporaryDirectory(); self.addCleanup(owned.cleanup)
        self.output = Path(owned.name)
        self.profile = net_profile
        self.inventory = inventory
        self.files = {'sdk-lock.json': encode({'version': 1}),
            'capsule-project.json': encode({'runtimeProfile': runtime_profile.IMPORT_PROFILE}),
            'vendor/lsf/' + net_profile.DECLARATION: read_file(ROOT/net_profile.DECLARATION),
            'vendor/lsf/' + net_profile.WIT: read_file(ROOT/net_profile.WIT)}
        self.source = inventory(self.files)
        self.recipe = inventory({name: read_file(ROOT/name) for name in net_profile.RECIPE})
        (self.output/'recipe-inputs.json').write_bytes(self.recipe)
        self.identities = net_profile.identities(ROOT)
        self.selection = net_profile.selected({'standardNetModules': ['node:net'],
            'standardNetProfile': net_profile.PROFILE, 'standardNetIdentities': self.identities}, self.identities)
        self.raw = encode(self.selection)
        (self.output/'typescript-net-selection.json').write_bytes(self.raw)
        self.materials = [{'name': 'build-recipe', 'digest': digest(self.recipe), 'size': len(self.recipe)},
            {'name': 'typescript-standard-net', 'digest': digest(self.raw), 'size': len(self.raw)}]
        self.materials.append(guest_runtime_receipts.emit(self.output, 'typescript', runtime_profile.IMPORT_PROFILE,
            self.files, self.source, COMPONENT, self.materials, graph=None,
            binding_digest=digest(b'original binding output'), configuration={'world': 'source-only-fixture'}))
        observed = compatibility.report('typescript', digest(self.source), digest(COMPONENT),
            'lsf-host-abi-phase3-v5', [],
            [compatibility.finding('unresolved-behavior', 'initialization', 'not-evaluated')])
        self.report_raw = encode(observed)
        (self.output/'compatibility-report.json').write_bytes(self.report_raw)

    def finish(self):
        return builder.finish(self.output, self.files, self.source, COMPONENT, self.materials)

    def test_selected_socket_source_mapping_preserves_unknown_qualification_and_report(self):
        value = self.finish(); text = context.present(value)
        self.assertEqual((self.output/'compatibility-report.json').read_bytes(), self.report_raw)
        self.assertEqual(value['qualification'], 'unknown')
        self.assertEqual(value['authority'], 'none')
        self.assertEqual(value['workerDrain'], 'unproven')
        self.assertEqual(value['standardRuntime']['ownerIssue'], 745)
        self.assertIn('net, node:net; profile lsf-node-net-tcp-v1', text)
        self.assertIn('implementation/qualification owner #745; qualification unknown; authority none', text)
        for identity in (*self.identities.values(), digest(self.raw), digest(self.recipe)):
            self.assertIn(identity, text)
        self.assertNotIn('buffer, node:buffer', text)

    def test_captured_declaration_and_interface_cannot_borrow_another_recipe(self):
        for path in (self.profile.DECLARATION, self.profile.WIT):
            with self.subTest(path=path):
                changed = dict(self.files); changed['vendor/lsf/' + path] += b'\n'
                with self.assertRaisesRegex(DevError, 'net-captured-input-drift'):
                    builder.typescript_net_materials(self.raw, self.recipe, self.inventory(changed))
        import json
        recipe = json.loads(self.recipe)
        del recipe[self.profile.BINDINGS]
        with self.assertRaisesRegex(DevError, 'net-input-missing'):
            builder.typescript_net_materials(self.raw, encode(recipe), self.source)

    def test_changed_or_forged_selection_and_unbound_owner_are_refused(self):
        for field, forged in (('maximumSocketStates', 2.0), ('tlsApi', 0),
                              ('qualification', 'passed'), ('authority', 'granted')):
            with self.subTest(field=field):
                changed = copy.deepcopy(self.selection); changed[field] = forged
                with self.assertRaisesRegex(DevError, 'net-selection-drift'):
                    builder.typescript_net_materials(encode(changed), self.recipe, self.source)
        (self.output/'typescript-net-selection.json').write_bytes(encode({**self.selection, 'profile': 'changed'}))
        with self.assertRaisesRegex(DevError, 'stale-or-unbound-receipt'):
            self.finish()
        (self.output/'typescript-net-selection.json').write_bytes(self.raw)
        (self.output/'standard-runtime-selection.json').unlink()
        self.materials = [row for row in self.materials if row['name'] != 'standard-runtime-selection']
        with self.assertRaisesRegex(DevError, 'net-owner-required'):
            self.finish()

    def test_rehashed_partial_or_wrong_owner_context_cannot_present_socket_mapping(self):
        original = self.finish()
        for alteration in ('partial', 'wrong-owner'):
            changed = copy.deepcopy(original)
            if alteration == 'partial':
                changed['materials'] = [row for row in changed['materials']
                    if row['name'] != 'typescript-standard-net-transport']
            else:
                changed['standardRuntime']['ownerIssue'] = 744
            changed['identity'] = digest(encode({key: item for key, item in changed.items() if key != 'identity'}))
            with self.subTest(alteration=alteration), self.assertRaisesRegex(DevError, 'net-module-'):
                context.present(changed)

    def test_original_outcome_reader_rejects_changed_and_rehashed_socket_sources(self):
        original = self.finish()
        (self.output/'source-inputs.json').write_bytes(self.source)
        descriptor = {'artifacts': {'component': 'component.wasm'}}
        receipt = {'source': digest(b'original frontend'), 'artifacts': {'component': digest(COMPONENT)}}

        def read():
            return outcomes.from_build(self.output, descriptor, receipt).context_state

        self.assertEqual(read(), 'observed')
        stripped = copy.deepcopy(original)
        stripped['materials'] = [row for row in stripped['materials'] if row['name'] not in context.NET_MATERIALS]
        stripped['identity'] = digest(encode({key: item for key, item in stripped.items() if key != 'identity'}))
        (self.output/'compatibility-context.json').write_bytes(encode(stripped))
        self.assertEqual(read(), 'invalid-present')
        changed = copy.deepcopy(original)
        next(row for row in changed['materials']
             if row['name'] == 'typescript-standard-net-backend')['digest'] = digest(b'forged backend')
        changed['identity'] = digest(encode({key: item for key, item in changed.items() if key != 'identity'}))
        (self.output/'compatibility-context.json').write_bytes(encode(changed))
        self.assertEqual(read(), 'invalid-present')
        # Rehashing the recipe, selection and context together cannot borrow the
        # original runtime owner's signed input identities either.
        import json
        recipe = json.loads(self.recipe)
        recipe[self.profile.BACKEND]['digest'] = digest(b'forged backend')
        recipe_raw = encode(recipe)
        selected = copy.deepcopy(self.selection)
        selected['identities']['backend'] = digest(b'forged backend')
        selected_raw = encode(selected)
        (self.output/'recipe-inputs.json').write_bytes(recipe_raw)
        (self.output/'typescript-net-selection.json').write_bytes(selected_raw)
        replacements = {'build-recipe': digest(recipe_raw), 'typescript-standard-net': digest(selected_raw)}
        for row in changed['materials']:
            if row['name'] in replacements:
                row['digest'] = replacements[row['name']]
        changed['identity'] = digest(encode({key: item for key, item in changed.items() if key != 'identity'}))
        (self.output/'compatibility-context.json').write_bytes(encode(changed))
        self.assertEqual(read(), 'invalid-present')
        (self.output/'recipe-inputs.json').write_bytes(self.recipe)
        (self.output/'typescript-net-selection.json').write_bytes(self.raw)
        (self.output/'compatibility-context.json').write_bytes(encode(original))
        self.assertEqual(read(), 'observed')

    def test_complete_socket_mapping_survives_original_material_limit(self):
        from tools import guest_runtime_receipts
        from tools.typescript_guest.runtime_profile import IMPORT_PROFILE
        self.materials = [row for row in self.materials if row['name'] != 'standard-runtime-selection']
        self.materials += [{'name': 'a-tool-' + str(index), 'digest': digest(str(index).encode()), 'size': 1}
                           for index in range(61)]
        (self.output/'standard-runtime-selection.json').unlink()
        self.materials.append(guest_runtime_receipts.emit(self.output, 'typescript', IMPORT_PROFILE,
            self.files, self.source, COMPONENT, self.materials, graph=None,
            binding_digest=digest(b'original binding output'), configuration={'world': 'source-only-fixture'}))
        value = self.finish()
        self.assertEqual(len(value['materials']), 64)
        self.assertGreater(value['omittedMaterials'], 0)
        self.assertEqual(set(context.net_module(value)), {*context.NET_MATERIALS, 'build-recipe'})
        self.assertLessEqual(len(encode(value)), context.MAX_BYTES)


if __name__ == '__main__': unittest.main()

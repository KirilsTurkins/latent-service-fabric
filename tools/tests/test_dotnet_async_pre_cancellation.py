"""Admission, exact source selection and zero-dispatch controls; no native claim."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.dotnet_guest import http_errors
from tools.dotnet_standard_http_node import request_api_binding, require_pre_cancelled_outbound
from tools.dotnet_standard_http_project import managed_source, project
from tools.phase2_operator_process import WorkflowError
from tools.probe_dotnet_http_errors import validate_async_probe
from tools.rust_capsule_project import ROOT, digest, inventory, read_file, snapshot


class AsyncPreCancellation(unittest.TestCase):
    def test_host_probe_binds_its_receipt_to_the_actual_derived_assembly_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            derived = Path(temporary)/'System.Net.Http.dll'
            derived.write_bytes(b'bounded-host-control-assembly')
            result = {
                'assertions': 17, 'originalDigest': http_errors.SOURCE_DIGEST,
                'derivedDigest': digest(derived.read_bytes()),
                'originalEntersAsyncBodyDespitePreCancellation': True,
                'preCancelledTaskPreservesOriginalToken': True,
                'outerNullValidationPreserved': True, 'uncancelledFaultsPreserved': True,
                'preCancelledGuestIoQualified': False, 'pendingGuestIoQualified': False,
                'defaultClientComponentQualified': False}
            validate_async_probe(result, derived)
            for field, wrong in (('derivedDigest', digest(b'foreign-derived')),
                                 ('originalDigest', digest(b'foreign-original')),
                                 ('preCancelledGuestIoQualified', True), ('outerNullValidationPreserved', False)):
                with self.subTest(field=field), self.assertRaisesRegex(
                        ValueError, 'http-async-pre-cancellation-probe-assertions'):
                    validate_async_probe({**result, field: wrong}, derived)
            derived.write_bytes(b'changed-after-probe')
            with self.assertRaisesRegex(ValueError, 'http-async-pre-cancellation-probe-assertions'):
                validate_async_probe(result, derived)

    def test_receipt_rejects_missing_foreign_and_type_confused_fields(self):
        expected = copy.deepcopy(http_errors.ASYNC_PRE_CANCELLATION)
        http_errors.validate_async_pre_cancellation(expected)
        for key, value in expected.items():
            with self.subTest(key=key):
                missing = dict(expected); del missing[key]
                with self.assertRaisesRegex(ValueError, 'http-async-pre-cancellation-rewrite-receipt'):
                    http_errors.validate_async_pre_cancellation(missing)
                wrong = dict(expected)
                wrong[key] = (int(value) if type(value) is bool else bool(value) if type(value) is int else 'foreign')
                with self.assertRaisesRegex(ValueError, 'http-async-pre-cancellation-rewrite-receipt'):
                    http_errors.validate_async_pre_cancellation(wrong)
        with self.assertRaisesRegex(ValueError, 'http-async-pre-cancellation-rewrite-receipt'):
            http_errors.validate_async_pre_cancellation({**expected, 'private': 'never-retained'})

    def test_async_selection_adds_only_pre_cancelled_mode_and_keeps_async_api(self):
        original = read_file(ROOT/'examples/dotnet-standard-http/Main.cs')
        self.assertEqual(managed_source(), original)
        line = b'        if (which == 4) cancellation.CancelAfter(100);'
        newline = b'\r\n' if b'\r\n' in original else b'\n'
        selected = managed_source(pre_cancelled_async=True)
        self.assertEqual(selected, original.replace(line, line+newline+b'        if (which == 6) cancellation.Cancel();'))
        self.assertEqual(selected.count(b'client.SendAsync('), 1)
        self.assertNotIn(b'client.Send(', selected)
        self.assertNotIn(b'new HttpClient(', selected.replace(b'new HttpClient()', b''))
        with tempfile.TemporaryDirectory() as temporary:
            created = project(Path(temporary)/'async-cancel', pre_cancelled_async=True)
            self.assertEqual(snapshot(created)['src/Main.cs'], selected)

    def test_selection_rejects_mixed_non_boolean_or_ambiguous_request_modes(self):
        for sync, asynchronous in ((True, True), (1, False), (False, 1), ('false', False), (False, None)):
            with self.subTest(sync=sync, asynchronous=asynchronous), self.assertRaisesRegex(
                    ValueError, 'standard-dotnet-request-api-selection'):
                managed_source(synchronous_send=sync, pre_cancelled_async=asynchronous)

    def test_actual_api_binding_rejects_an_original_fixture_as_the_extra_programme(self):
        with tempfile.TemporaryDirectory() as temporary:
            artifact = Path(temporary)
            component = b'control-component'
            (artifact/'component.wasm').write_bytes(component)
            def captured(source):
                raw = inventory({'src/Main.cs': source})
                (artifact/'source-inputs.json').write_bytes(raw)
                (artifact/'build-observation.json').write_text(json.dumps({
                    'source': {'snapshotDigest': digest(raw)}, 'componentDigest': digest(component),
                    'componentSize': len(component)}), encoding='utf-8')
            captured(managed_source())
            with self.assertRaisesRegex(WorkflowError, 'standard-dotnet-observed-request-api-mismatch'):
                request_api_binding(artifact, synchronous_send=False, pre_cancelled_async=True)
            captured(managed_source(pre_cancelled_async=True))
            bound = request_api_binding(artifact, synchronous_send=False, pre_cancelled_async=True)
            self.assertEqual(bound['name'], 'HttpClient.SendAsync')
            self.assertEqual(bound['completionOption'], 'ResponseHeadersRead')
            self.assertEqual(bound['componentDigest'], digest(component))

    def test_pre_cancelled_request_requires_integer_zero_outbound_attempts(self):
        for value in (0, True, False, 1, -1, 0.0, '0', None):
            row = {'response': {'data': {'consumption': {'outboundRequests': value}}}}
            with self.subTest(value=value):
                if type(value) is int and value == 0:
                    require_pre_cancelled_outbound(row)
                else:
                    with self.assertRaisesRegex(WorkflowError, 'pre-cancelled-outbound-attempt'):
                        require_pre_cancelled_outbound(row)

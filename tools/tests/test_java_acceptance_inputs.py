"""Input checks are synthetic and never establish signed Java execution."""
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from tools.java_transaction_qualification import acceptance_inputs as acceptance
from tools.java_transaction_qualification import current_inputs as current
from tools.java_transaction_qualification.inputs import digest
from tools.tests.test_java_current_inputs import encoded, fixture


class JavaAcceptanceInputs(unittest.TestCase):
    def test_values_bind_declared_vectors_and_cannot_claim_signed_execution(self):
        source = (b'Long.MIN_VALUE 0xffff_fff1L UTF8_VALUE command.get(ABSENT_KEY) '
                  b'query.get(ABSENT_KEY) value-instance-reused .stage(command)')
        world, companion = b'world', b'companion'
        payload = json.dumps([None, acceptance.UTF8_TEXT], ensure_ascii=False, separators=(',', ':')).encode()
        declaration = {'schemaVersion': 'latent.java.transaction-value-inputs.v1', 'selectors': acceptance.SELECTORS,
            'expectedUnsignedValues': {'highBit': '9223372036854775808', 'unsignedMaximum': '18446744073709551615'},
            'utf8Text': acceptance.UTF8_TEXT, 'utf8PayloadDigest': digest(payload), 'absentOptionalRequired': True,
            'freshInstanceRequired': True, 'originalSourceDigest': 'sha256:' + '1' * 64, 'sourceDigest': digest(source),
            'worldDigest': digest(world), 'companionDigest': digest(companion), 'componentCompiled': False,
            'signedStateExecutionQualified': False, 'unsignedRoundtripQualified': False, 'utf8RoundtripQualified': False,
            'absentOptionalQualified': False}
        raw = encoded(declaration)
        files = {'project/src/dev/latent/app/Capsule.java': source, 'project/wit/world.wit': world,
                 'project/transaction-value-inputs.json': raw}
        report = {'componentDigest': 'component', 'companionDigest': digest(companion), 'sourceDigest': 'source',
                  'hostAbiDigest': 'abi', 'valueInputDigest': digest(raw), 'applicationVariant': 'values',
                  'deferredHttpRequirementsDigest': 'requirements'}
        _, selected = fixture()
        selected = replace(selected, variant=acceptance.VALUES)
        with patch.object(acceptance, '_validate_materials', return_value=report):
            self.assertEqual(acceptance.validate_files(Path('/capture'), files, selected).requirements_digest, 'requirements')
            for name, value in (('signedStateExecutionQualified', True), ('utf8Text', 'different'),
                                ('expectedUnsignedValues', {})):
                changed = encoded({**declaration, name: value})
                with self.subTest(name=name), self.assertRaises(ValueError):
                    acceptance.validate_files(Path('/capture'), {**files, 'project/transaction-value-inputs.json': changed},
                                              selected)

    def test_child_import_is_only_permitted_for_separately_selected_child(self):
        files, selected = fixture()
        report = json.loads(files['report.json'])
        report['actualImports'].append('latent:service/invoke@0.1.0')
        files['report.json'] = encoded(report)
        selected = replace(selected, report_digest=digest(files['report.json']))
        with self.assertRaises(ValueError):
            current.validate_materials(files, selected)
        report['variant'] = acceptance.CHILD
        files['report.json'] = encoded(report)
        selected = replace(selected, variant=acceptance.CHILD, report_digest=digest(files['report.json']))
        self.assertEqual(current._validate_materials(files, selected, (acceptance.CHILD,))['variant'], acceptance.CHILD)
        report['actualImports'].remove('latent:service/invoke@0.1.0')
        files['report.json'] = encoded(report)
        with self.assertRaises(ValueError):
            current._validate_materials(files, replace(selected, report_digest=digest(files['report.json'])), (acceptance.CHILD,))

    def test_child_source_must_make_typed_call_inside_command_without_effect_authority(self):
        source = (b'try (var command = State.acquireCommand().value()) {\n'
                  b'Bindings.LatentServiceInvoke.call(\n'
                  b'Bindings.LatentServiceInvokePlatformErrorCode.PermissionDenied\n'
                  b'return Result.err(Bindings.ExamplesTransactionalAggregateApiBusinessError.Rejected)')
        files = {'project/src/dev/latent/app/Capsule.java': source}
        report = {'componentDigest': 'component', 'companionDigest': 'companion',
                  'sourceDigest': 'source', 'hostAbiDigest': 'abi'}
        _, selected = fixture()
        selected = replace(selected, variant=acceptance.CHILD)
        with patch.object(acceptance, '_validate_materials', return_value=report):
            item = acceptance.validate_files(Path('/capture'), files, selected)
            self.assertIsNone(item.requirements_digest)
            for mutated in (source.replace(b'PermissionDenied', b'Unavailable'),
                            source.replace(b'LatentServiceInvoke.call(', b'other(')):
                with self.subTest(source=mutated), self.assertRaises(ValueError):
                    acceptance.validate_files(Path('/capture'), {**files, 'project/src/dev/latent/app/Capsule.java': mutated}, selected)
            with self.assertRaises(ValueError):
                acceptance.validate_files(Path('/capture'), {**files, 'project/deferred-http-requirements.json': b'{}'}, selected)


if __name__ == '__main__':
    unittest.main()

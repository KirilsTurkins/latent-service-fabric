"""Optional catalogue integrity and evidence classification; no native builds."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools import compatibility_catalogue as subject

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / 'docs/compatibility-catalogue/v1'


class Catalogue(unittest.TestCase):
    def setUp(self):
        self.value = json.loads((DATA / 'catalogue.json').read_bytes())

    def reseal(self):
        for entry in self.value['entries']:
            entry['identity'] = subject.identity({k: v for k, v in entry.items() if k != 'identity'})

    def test_retained_actual_receipts_validate_and_readable_catalogue_is_current(self):
        import jsonschema
        schema = json.loads((DATA / 'schema.json').read_bytes())
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(self.value, schema)
        subject.validate(self.value, DATA)
        self.assertEqual((DATA / 'README.md').read_text(encoding='utf8'), subject.markdown(self.value))
        entry = self.value['entries'][0]
        self.assertEqual(entry['package']['version'], '6.0')
        self.assertEqual(entry['construction'], 'ordinary-default')
        self.assertEqual(len(self.value['documents']), 6)

    def test_another_bound_component_or_source_cannot_borrow_the_signed_result(self):
        original = copy.deepcopy(self.value)
        for dimension in ('source', 'component'):
            self.value = copy.deepcopy(original)
            # This is a genuine existing digest in the same retained receipt,
            # so ordinary document/value integrity alone would accept it.
            selected = self.value['entries'][0]['bindings']['runtime']
            self.value['entries'][0]['bindings'][dimension] = copy.deepcopy(selected)
            self.reseal()
            with self.subTest(dimension=dimension), self.assertRaisesRegex(ValueError, 'execution-source-component'):
                subject.validate(self.value, DATA)

    def test_changed_coordinate_version_or_artifact_cannot_borrow_another_package_receipt(self):
        original = copy.deepcopy(self.value)
        for key, replacement in [('coordinate', 'outside:other:6.0'), ('version', '7.0'),
                                 ('artifactDigest', subject.digest(b'other JAR'))]:
            self.value = copy.deepcopy(original)
            self.value['entries'][0]['package'][key] = replacement
            self.reseal()
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'package-binding'):
                subject.validate(self.value, DATA)

    def test_wrong_engine_graph_patch_and_wit_bindings_cannot_reuse_a_passing_entry(self):
        original = copy.deepcopy(self.value)
        for dimension in subject.DIMENSIONS:
            self.value = copy.deepcopy(original)
            self.value['entries'][0]['bindings'][dimension]['valueDigest'] = subject.digest(b'stale')
            self.reseal()
            with self.subTest(dimension=dimension), self.assertRaisesRegex(ValueError, 'reference-drift'):
                subject.validate(self.value, DATA)

    def test_native_reference_injection_and_pending_compiler_receipt_cannot_claim_tested_default(self):
        original = copy.deepcopy(self.value)
        for kind in ('native-reference', 'compiler', 'not-run'):
            self.value = copy.deepcopy(original)
            self.value['entries'][0]['evidence']['kind'] = kind
            self.reseal()
            with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'default-path-evidence'):
                subject.validate(self.value, DATA)
        self.value = copy.deepcopy(original)
        self.value['entries'][0]['construction'] = 'injected-adapter';self.reseal()
        with self.assertRaisesRegex(ValueError, 'default-path-evidence'):
            subject.validate(self.value, DATA)
        self.value = copy.deepcopy(original)
        result = {'document': 'profile', 'pointer': '/qualification',
                  'valueDigest': subject.identity('pending')}
        self.value['entries'][0]['evidence']['result'] = result;self.reseal()
        with self.assertRaisesRegex(ValueError, 'default-path-evidence'):
            subject.validate(self.value, DATA)

    def test_optional_configuration_incompatible_and_untested_are_distinct_from_default_pass(self):
        row = self.value['entries'][0]
        row['status'] = 'optional-adapter-assisted';self.reseal()
        with self.assertRaisesRegex(ValueError, 'adapter-classification'):
            subject.validate(self.value, DATA)
        row['construction'] = 'injected-adapter';self.reseal()
        subject.validate(self.value, DATA)
        for status, reason in [('supported-ordinary-configuration', 'configuration-evidence'),
                               ('known-incompatible', 'incompatible-evidence'),
                               ('untested', 'untested-evidence')]:
            row['status'] = status;self.reseal()
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, reason):
                subject.validate(self.value, DATA)

    def test_document_tampering_absence_links_and_path_escape_fail_only_the_optional_reader(self):
        record = copy.deepcopy(self.value['documents']['qualification'])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary);path = root / 'public.json'
            raw = b'{"status":"passed"}'
            selected = {**record, 'path': 'public.json', 'bytes': len(raw), 'sha256': subject.digest(raw)}
            path.write_bytes(raw)
            subject.document(root, selected)
            path.write_bytes(b'{"status":"failed"}')
            with self.assertRaisesRegex(ValueError, 'document-drift'):
                subject.document(root, selected)
            path.unlink()
            with self.assertRaises(OSError):
                subject.document(root, selected)
            for name in ('../outside.json', '/outside.json', 'sub\\outside.json', 'C:/outside.json'):
                with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'document-path'):
                    subject.document(root, {**selected, 'path': name})
            path.write_bytes(raw)
            import os
            os.link(path, root / 'second-name.json')
            with self.assertRaisesRegex(ValueError, 'document-bound'):
                subject.document(root, selected)

    def test_new_authority_unknown_fields_duplicate_entries_and_unbound_edits_are_rejected(self):
        original = copy.deepcopy(self.value)
        changes = (lambda v: v.update(authority='grant'),
                   lambda v: v.update(allowPackages=['example']),
                   lambda v: v['entries'].append(copy.deepcopy(v['entries'][0])),
                   lambda v: v['entries'][0].update(status='untested'))
        for change in changes:
            self.value = copy.deepcopy(original);change(self.value)
            with self.subTest(change=change), self.assertRaises(ValueError):
                subject.validate(self.value, DATA)
        subject.validate({**original, 'documents': {}, 'entries': []}, Path('catalogue-does-not-exist'))

    def test_pointer_aliases_and_markup_cannot_change_the_presented_scope(self):
        value = {'a/b': {'~field': [3]}}
        self.assertEqual(subject.pointer(value, '/a~1b/~0field/0'), 3)
        for path in ('/a~1b/~0field/00', '/a~1b/~0field/-1', '/a~1b/~2field', '/missing'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                subject.pointer(value, path)
        self.value['entries'][0]['surface'] = '<script>|unexpected table'
        rendered = subject.markdown(self.value)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;\\|unexpected table', rendered)


if __name__ == '__main__':
    unittest.main()

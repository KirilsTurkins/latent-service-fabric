import json
from pathlib import Path
import unittest

from tools import browser_response_ownership as ownership


class BrowserResponseOwnershipTests(unittest.TestCase):
    def test_versioned_complete_table_and_guide_are_exactly_synchronized(self):
        table = ownership.table()
        self.assertEqual(table['schemaVersion'], 'latent.browser.response-ownership.v1')
        self.assertEqual(table['httpContract'], 'latent:web/application@0.1.0')
        self.assertEqual(table['browserProfile'], 'same-origin-v1')
        self.assertEqual(table['referrerPolicy'], 'same-origin')
        self.assertEqual(len({row['id'] for row in table['rows']}), 10)
        names = [name for row in table['rows'] for name in row['names']]
        prefixes = [prefix for row in table['rows'] for prefix in row['prefixes']]
        self.assertEqual(len(set(names)), len(names))
        self.assertEqual(len(set(prefixes)), len(prefixes))
        for row in table['rows']:
            for name in row['names'] + [prefix + 'fixture' for prefix in row['prefixes']]:
                self.assertEqual(ownership.ownership(name), row['id'])
                self.assertEqual(ownership.ownership(name.upper()), row['id'])
        guide = (ownership.ROOT / 'docs/security/browser-boundary.md').read_text(encoding='utf-8')
        block = ownership.BEGIN + guide.split(ownership.BEGIN, 1)[1].split(ownership.END, 1)[0] + ownership.END
        self.assertEqual(block, ownership.documentation())
        self.assertIn('strict-transport-security', names)
        self.assertIn('set-cookie', names)
        self.assertIn('cache-control', names)
        self.assertIn('authorization', names)
        self.assertIn('transfer-encoding', names)

    def test_declared_conflicts_are_bounded_nonreflective_and_dynamic_requires_execution(self):
        names = ['Referrer-Policy', 'Content-Length', 'authorization', 'x-lsf-secret',
                 'access-control-allow-origin', 'location', 'location', 'X-App-Value',
                 'x-app-value', 'synthetic-secret\r\nx-injected']
        result = ownership.inspect_declared_header_names(names, dynamic=True)
        self.assertTrue(result['dynamicOutputRequiresExecution'])
        self.assertTrue(result['valuesAndBodyRequireValidation'])
        self.assertFalse(result['responseQualified'])
        self.assertEqual(result['conflicts'], [
            {'index': index, 'reason': 'reserved-header'} for index in range(5)]
            + [{'index': 6, 'reason': 'duplicate-singleton'}, {'index': 7, 'reason': 'header-grammar'},
               {'index': 9, 'reason': 'header-grammar'}])
        encoded = json.dumps(result)
        for name in names:
            self.assertNotIn(name, encoded)
        self.assertEqual(ownership.inspect_declared_header_names(['cache-control', 'cache-control', 'etag'])['conflicts'], [])

    def test_case_collisions_wire_grammar_and_maximum_header_budget(self):
        names = ['x-app-result'] * 64
        result = ownership.inspect_declared_header_names(names)
        self.assertEqual(result['conflicts'], [])
        for invalid in [names + ['etag'], {'name': 'etag'}, 'etag']:
            with self.assertRaisesRegex(ValueError, 'response-header-inspection-bound'):
                ownership.inspect_declared_header_names(invalid)
        for name in ['', 'x' * 65, '\u0130nvalid', None, 'x header']:
            result = ownership.inspect_declared_header_names([name])
            self.assertEqual(result['conflicts'], [{'index': 0, 'reason': 'header-grammar'}])
        self.assertEqual(ownership.inspect_declared_header_names(['LOCATION', 'location'])['conflicts'],
                         [{'index': 0, 'reason': 'header-grammar'}])

    def test_java_authoring_vectors_cover_every_field_prefix_and_authoritative_limit(self):
        rows = ownership.java_vectors().splitlines()
        self.assertTrue(100 <= len(rows) <= 256)
        table = ownership.table()
        for row in table['rows']:
            for name in row['names'] + [prefix + 'fixture' for prefix in row['prefixes']]:
                self.assertIn(name + '\t' + row['id'], rows)
                self.assertIn(name.upper() + '\t' + row['id'], rows)
        for name, value in table['limits'].items():
            self.assertIn('limit:' + name + '\t' + str(value), rows)


if __name__ == '__main__':
    unittest.main()

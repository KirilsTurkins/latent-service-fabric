import json
import os
from pathlib import Path
import shutil
import unittest

from tools.build_process import run_bounded_result
from tools.test_run import redact


ROOT = Path(__file__).resolve().parents[2]
ORIGIN = 'http://docs.example.test:8080'


class FrameworkRequestObservationTests(unittest.TestCase):
    def observe(self, values, origin=ORIGIN):
        module = (ROOT / 'examples/framework-compatibility/request-observation.mjs').as_uri()
        program = (
            'import {publicRequestPath} from ' + json.dumps(module) + ';'
            'const inputs = JSON.parse(process.argv[1]);'
            'console.log(JSON.stringify(inputs.values.map(value => '
            'publicRequestPath(value, inputs.origin))));'
        )
        node = shutil.which('node')
        self.assertIsNotNone(node, 'the maintained contract lane installs Node')
        result = run_bounded_result(
            [node, '--input-type=module', '--eval', program,
             json.dumps({'values': values, 'origin': origin})],
            ROOT, dict(os.environ), 10, 65536,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertEqual(result.stderr, b'')
        return json.loads(result.stdout)

    def test_root_localized_and_mounted_public_paths_survive_actual_outer_redaction(self):
        paths = ['', 'assets/js/main.89c367e9.js', 'de/assets/js/17896441.89c367e9.js',
                 'docs/de/guide/', 'guide/']
        actual = self.observe([ORIGIN + '/' + path for path in paths])
        self.assertEqual(actual, paths)
        for path in actual:
            with self.subTest(path=path):
                record = json.dumps({'path': path, 'status': 503})
                self.assertEqual(json.loads(redact(record)), {'path': path, 'status': 503})

    def test_actual_redactor_erases_old_absolute_path_and_retains_new_public_path(self):
        public = 'de/assets/js/17896441.89c367e9.js'
        old = redact(json.dumps({'url': '/' + public, 'status': 503}))
        self.assertEqual(json.loads(old), {'url': '<path>', 'status': 503})
        path, = self.observe([ORIGIN + '/' + public])
        current = redact(json.dumps({'path': path, 'status': 503}))
        self.assertEqual(json.loads(current), {'path': public, 'status': 503})

    def test_origin_userinfo_query_and_fragment_are_never_returned(self):
        raw = 'http://fixture-user:fixture-pass@docs.example.test:8080/de/main.js?private=fixture-value#fragment'
        path, = self.observe([raw])
        self.assertEqual(path, 'de/main.js')
        output = redact(json.dumps({'path': path, 'status': 503}))
        for private in ('fixture-user', 'fixture-pass', 'docs.example.test', '8080', 'private', 'fixture-value', 'fragment'):
            self.assertNotIn(private, output)

    def test_foreign_origin_scheme_and_port_cannot_be_reported_as_local_public_paths(self):
        values = ['http://foreign.example.test:8080/de/main.js',
                  'https://docs.example.test:8080/de/main.js',
                  'http://docs.example.test:8081/de/main.js',
                  'file:///private/host/file', 'data:text/plain,private']
        self.assertEqual(self.observe(values), ['unmapped'] * len(values))

    def test_raw_dot_segments_are_rejected_before_url_normalization(self):
        values = [ORIGIN + path for path in ['/../private', '/de/../../private', '/./main.js', '/de/./main.js']]
        self.assertEqual(self.observe(values), ['unmapped'] * len(values))

    def test_encoded_traversal_separators_and_control_bytes_are_not_exposed(self):
        values = [ORIGIN + '/' + path for path in ['%2e%2e/private', 'de/%2E/main.js', '%252e%252e/private',
                  'de%2fprivate.js', 'de/%5cprivate', 'de/%00private']]
        self.assertEqual(self.observe(values), ['unmapped'] * len(values))

    def test_backslashes_windows_paths_and_relative_urls_are_unmapped(self):
        values = [ORIGIN + '/de\\private.js', 'http:\\docs.example.test\\private',
                  'C:\\private\\file', '//docs.example.test:8080/main.js', '/de/main.js', 'not-a-url']
        self.assertEqual(self.observe(values), ['unmapped'] * len(values))

    def test_dotfiles_and_double_slashes_cannot_escape_the_public_path_projection(self):
        values = [ORIGIN + path for path in ['/.env', '/de/.private', '//private', '/de//main.js']]
        self.assertEqual(self.observe(values), ['unmapped'] * len(values))

    def test_controls_unicode_and_header_like_path_text_are_unmapped(self):
        values = [ORIGIN + '/' + path for path in ['de/main\nprivate.js', 'de/main\rprivate.js',
                  'de/main\tprivate.js', 'de/\u00e4.js', 'de/header:value', 'de/key=value']]
        self.assertEqual(self.observe(values), ['unmapped'] * len(values))

    def test_relative_path_and_input_size_bounds_retain_no_truncated_private_suffix(self):
        public = 'a' * 253 + '.js'
        values = [ORIGIN + '/' + public, ORIGIN + '/' + public + 'x', ORIGIN + '/' + 'x' * 8193]
        self.assertEqual(self.observe(values), [public, 'unmapped', 'unmapped'])

    def test_nonstring_values_and_invalid_expected_origin_fail_to_fixed_label(self):
        values = [None, False, 1, [], {}, '']
        self.assertEqual(self.observe(values), ['unmapped'] * len(values))
        self.assertEqual(self.observe([ORIGIN + '/main.js'], 'not-a-url'), ['unmapped'])

    def test_public_hashed_assets_keep_exact_case_and_filename_characters(self):
        paths = ['_next/static/chunks/App-1_2.abc~def.js', 'assets/css/styles.ABC123.css',
                 'de/assets/media/font-123.woff2', 'img/logo.svg']
        self.assertEqual(self.observe([ORIGIN + '/' + path for path in paths]), paths)

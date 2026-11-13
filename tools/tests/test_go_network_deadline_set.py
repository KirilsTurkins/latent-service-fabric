"""Fail-closed controls for the focused Go active-deadline reference."""
import hashlib
import json
from pathlib import Path
import unittest

from tools import go_network_deadline_set_reference as q

ROOT = Path(__file__).resolve().parents[2]
TEMPLATE = ROOT / 'sdk/go-guest/runtime/net_stream.go.in'


class GoDeadlineSetReference(unittest.TestCase):
    def rows(self, old=False):
        cases = [q.CASES[0]] if old else q.CASES
        result = [{'Package': q.PACKAGE, 'Action': 'start'}]
        for case in cases:
            if old:
                result.append({'Package': q.PACKAGE, 'Action': 'output', 'Test': case,
                               'Output': 'mixed-clock-basis-accepted: read=true'})
            result.append({'Package': q.PACKAGE, 'Action': 'fail' if old else 'pass', 'Test': case})
        result.append({'Package': q.PACKAGE, 'Action': 'fail' if old else 'pass'})
        return result

    def encoded(self, rows):
        return b'\n'.join(json.dumps(row).encode() for row in rows) + b'\n'

    def test_exact_setter_and_helper_are_the_only_projected_runtime_code(self):
        raw = TEMPLATE.read_bytes()
        helper, setter = q.methods(raw, current=True)
        self.assertEqual(q.projected(raw, current=True), q.STUB + helper + b'\n' + setter + b'\n')
        self.assertIn(b'(a == a.Round(0)) == (b == b.Round(0))', helper)
        self.assertNotIn(b'c.stream', setter)
        old = setter.replace(b'!lsfStreamSameDeadline(t, c.readDeadline)', b'!t.Equal(c.readDeadline)')
        old = old.replace(b'!lsfStreamSameDeadline(t, c.writeDeadline)', b'!t.Equal(c.writeDeadline)')
        self.assertEqual(hashlib.sha256(old).hexdigest(), q.OLD_SHA)
        self.assertEqual(q.methods(old, current=False), (old,))
        for invalid in (raw + setter, raw + helper, raw.replace(b'\n', b'\r\n'), b'x' * 65537):
            with self.subTest(size=len(invalid)), self.assertRaises(ValueError):
                q.methods(invalid, current=True)

    def test_reader_requires_the_actual_old_failure_and_all_current_cases(self):
        self.assertEqual(q.observed(self.encoded(self.rows(True)), True), [q.CASES[0]])
        self.assertEqual(q.observed(self.encoded(self.rows()), False), list(q.CASES))
        bad = self.rows(True); bad[1]['Output'] = 'compile failure'
        with self.assertRaises(ValueError): q.observed(self.encoded(bad), True)
        for bad in (self.rows()[:-2] + self.rows()[-1:], self.rows() + [self.rows()[1]],
                    [dict(self.rows()[0], Action='skip')] + self.rows()[1:],
                    [dict(self.rows()[0], Package='unexpected')] + self.rows()[1:]):
            with self.assertRaises(ValueError): q.observed(self.encoded(bad), False)
        duplicate = self.encoded(self.rows()).replace(b'"Action": "start"', b'"Action": "start", "Action": "pass"', 1)
        with self.assertRaisesRegex(ValueError, 'duplicate-field'): q.observed(duplicate, False)


if __name__ == '__main__':
    unittest.main()
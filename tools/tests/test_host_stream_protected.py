import unittest
from tools import qualify_host_stream_protected as owner


class FocusedStreamHostOwner(unittest.TestCase):
    def test_six_closed_case_ids_require_original_single_green_nonignored_outcome(self):
        names = [name for group in owner.CASES.values() for name in group]
        self.assertEqual(len(names), 6)
        self.assertEqual(len(set(names)), 6)
        for name in names:
            raw = ('test '+name+' ... ok\ntest result: ok. 1 passed; 0 failed; '
                '0 ignored; 0 measured; 123 filtered out; finished in 1s\n').encode()
            self.assertEqual(owner.outcome(raw,name),name)
            for changed in (raw.replace(b'1 passed',b'0 passed'),
                    raw.replace(b'0 failed',b'1 failed'),raw.replace(b'0 ignored',b'1 ignored'),
                    raw.replace(b'... ok',b'... FAILED'),b'',raw+raw):
                with self.assertRaises(ValueError):
                    owner.outcome(changed,name)

    def test_other_registered_case_cannot_satisfy_selected_case_or_missing_totals(self):
        first,second = owner.CASES['latent-streams']
        raw = ('test '+first+' ... ok\ntest result: ok. 1 passed; 0 failed; '
            '0 ignored; 0 measured; 123 filtered out; finished in 1s\n').encode()
        for changed,name in ((raw,second),(raw.split(b'test result:')[0],first),
                (raw.replace(b'1 passed',b'2 passed'),first),
                (raw.replace(b'0 measured',b'1 measured'),first)):
            with self.assertRaises(ValueError):
                owner.outcome(changed,name)

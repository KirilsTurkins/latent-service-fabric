"""Parser observations preserve hostile baseline failures and real retirement."""
import copy
import json
import unittest

from tools import qualify_host_stream_tls_parser as reference


class ParserReferenceObservations(unittest.TestCase):
    def rows(self, original=False):
        expected = {reference.OLD_CASE: True} if original else reference.CASES
        return [{"case": name, "inputBytes": 16, "accepted": admitted,
                 "expectedAccepted": admitted, "peakAllocationBytes": 131072 if original else 1024,
                 "cumulativeAllocationBytes": 131072 if original else 2048,
                 "liveAfterDropBytes": 0} for name, admitted in expected.items()]

    def encoded(self, rows):
        return b"\n".join(json.dumps(row).encode() for row in rows)

    def test_original_parser_must_exceed_same_ceiling_and_retire_allocations(self):
        rows = self.rows(True)
        self.assertEqual(reference.observations(self.encoded(rows), original=True), rows)
        for field, invalid in (("peakAllocationBytes", 65536), ("liveAfterDropBytes", 1),
                               ("accepted", False)):
            changed = copy.deepcopy(rows)
            changed[0][field] = invalid
            with self.assertRaises(ValueError):
                reference.observations(self.encoded(changed), original=True)

    def test_every_bounded_vector_keeps_exact_acceptance_and_zero_live_owners(self):
        rows = self.rows()
        self.assertEqual(reference.observations(self.encoded(rows), original=False), rows)
        for index, row in enumerate(rows):
            for field, invalid in (("accepted", not row["accepted"]), ("liveAfterDropBytes", 1),
                                   ("peakAllocationBytes", 65537), ("cumulativeAllocationBytes", 0),
                                   ("inputBytes", True), ("expectedAccepted", 1)):
                changed = copy.deepcopy(rows)
                changed[index][field] = invalid
                with self.subTest(case=row["case"], field=field), self.assertRaises(ValueError):
                    reference.observations(self.encoded(changed), original=False)

    def test_missing_duplicate_foreign_and_extra_observations_are_rejected(self):
        rows = self.rows()
        for changed in (rows[:-1], rows[:-1] + [rows[0]], rows + [rows[0]], self.rows(True)):
            with self.assertRaises(ValueError):
                reference.observations(self.encoded(changed), original=False)
        changed = copy.deepcopy(rows)
        changed[0]["inferredTlsQualification"] = True
        with self.assertRaises(ValueError):
            reference.observations(self.encoded(changed), original=False)


if __name__ == "__main__":
    unittest.main()

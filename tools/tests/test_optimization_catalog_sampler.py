"""Source sampler bounds and interval association without large fixtures."""
from io import BytesIO
import unittest

from tools.optimization_backend_revision.catalog import sampler
from tools.optimization_evidence.common import EvidenceError, canonical


class SamplerTests(unittest.TestCase):
    def rows(self, values):
        stream = BytesIO(b"".join(canonical([str(item) for item in row]) + b"\n" for row in values))
        return sampler.read(stream, "initial", pid=7, start_ticks=41, elapsed_nanos=1000)

    def test_phase_requires_both_actual_sample_endpoints(self):
        rows = self.rows([(90, 110, 7, 41, 50, 100, 1, 1),
                          (150, 160, 7, 41, 60, 100, 1, 2),
                          (190, 210, 7, 41, 90, 100, 2, 2)])
        result = sampler.phase(rows, 100, 200)
        self.assertEqual((result["sample_count"], result["rss_max_bytes"]), ("1", "60"))
        empty = sampler.phase(rows, 111, 149)
        self.assertEqual((empty["sample_count"], empty["rss_max_bytes"]), ("0", None))

    def test_crossed_owner_clock_and_regressing_counters_reject(self):
        base = (10, 20, 7, 41, 50, 100, 2, 3)
        for changed in ((30, 40, 8, 41, 50, 100, 2, 3),
                        (30, 40, 7, 42, 50, 100, 2, 3),
                        (19, 40, 7, 41, 50, 100, 2, 3),
                        (30, 1001, 7, 41, 50, 100, 2, 3),
                        (30, 40, 7, 41, 101, 100, 2, 3),
                        (30, 40, 7, 41, 50, 99, 2, 3),
                        (30, 40, 7, 41, 50, 100, 1, 3),
                        (30, 40, 7, 41, 50, 100, 2, 2)):
            with self.subTest(changed=changed), self.assertRaises(EvidenceError):
                self.rows([base, changed])

    def test_closed_decimal_rows_and_finite_lines(self):
        for content in (b"", b"[]\n", b'["01"]\n', b'[1,2,7,41,50,100,1,1]\n',
                        b'[' + b' ' * 256 + b']\n', b'["1","2","7","41","50","100","1","1"]'):
            with self.subTest(content=content[:20]), self.assertRaises(EvidenceError):
                sampler.read(BytesIO(content), "initial", pid=7, start_ticks=41, elapsed_nanos=1000)
        with self.assertRaises(EvidenceError):
            sampler.read(BytesIO(b""), "allocation", pid=7, start_ticks=41, elapsed_nanos=1000)


if __name__ == "__main__":
    unittest.main()

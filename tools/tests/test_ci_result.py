import copy
import unittest

from tools.ci_result import COMMON, PRODUCT, failures


class AggregateTests(unittest.TestCase):
    def state(self, profile):
        result = {name: {"result": "success" if profile == "full" or name in COMMON else "skipped"}
                  for name in COMMON | PRODUCT}
        result["profile"]["outputs"] = {"profile": profile}
        return result

    def test_every_profile_requires_current_site_success(self):
        for profile in ("docs", "website", "full"):
            result = self.state(profile)
            self.assertEqual(failures(result), [])
            for job in COMMON | (PRODUCT if profile == "full" else frozenset()):
                for state in ("failure", "cancelled", "skipped"):
                    changed = copy.deepcopy(result)
                    changed[job]["result"] = state
                    self.assertIn(job, failures(changed))

    def test_unknown_incomplete_and_inconsistent_results_fail_closed(self):
        for profile in ("docs", "website"):
            state = self.state(profile)
            state["rust"]["result"] = "success"
            self.assertIn("rust", failures(state))
        self.assertTrue(failures(self.state("unknown")))
        for invalid in ({}, [], None, {"website": {"result": "success"}}):
            self.assertTrue(failures(invalid))
        state = self.state("full")
        state["website"]["result"] = "pending"
        self.assertTrue(failures(state))


if __name__ == "__main__":
    unittest.main()

"""Keep a closed failure reason without settling or repeating an operation."""
from __future__ import annotations
import copy
from pathlib import Path
import re
import tempfile
import unittest
from unittest.mock import Mock

from tools.dev_workflow import common, journal, operation_observation, state


class ClosedOperationObservation(unittest.TestCase):
    def response(self, reason="admission-clock-lease-uncovered", retryable=True):
        return {"category": "platform-failure", "outcomeKnown": False, "requestDispatched": True,
                "data": {"credential": "private-fixture-value"}, "error": {"code": "unavailable",
                "message": "private-fixture-value", "retryable": retryable, "details": [{
                    "kind": "admission.currentness", "fields": {"reason": reason}}]}}

    def observe(self, response):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        controller = journal.Journal(root, "node", "examples")
        mutation = Mock(return_value=response)
        with self.assertRaisesRegex(common.DevError, "operation-outcome-uncertain-use-recover") as caught:
            controller.execute("deployment", {"deployment": "original", "expectedGeneration": "3"}, mutation)
        self.assertTrue(caught.exception.uncertain)
        mutation.assert_called_once()
        original = controller.read()["pending"]
        self.assertEqual(original["id"], mutation.call_args.args[0])
        self.assertEqual(controller.read()["history"], [])
        observation = state.load(root, "last-operation-observation.json")
        self.assertEqual(observation["id"], original["id"])
        self.assertFalse(observation["outcomeKnown"])
        self.assertTrue(observation["requestDispatched"])
        self.assertEqual(observation["resultSha256"], common.digest(common.encode(response)))
        self.assertLess(len(common.encode(observation)), 1024)
        self.assertNotIn(b"private-fixture-value", common.encode(observation))
        with self.assertRaisesRegex(common.DevError, "recover-original-operation-before-new-mutation"):
            controller.execute("deployment", {}, mutation)
        mutation.assert_called_once()
        return observation

    def test_all_current_public_reasons_retain_retryability_without_settling_the_original(self):
        core = (Path(__file__).resolve().parents[2] / "crates/latent-core/src/error.rs").read_text(encoding="utf-8")
        declaration = re.search(r"pub const ADMISSION_CURRENTNESS_REASONS:.*?= &\[(.*?)\];", core, re.S)
        self.assertIsNotNone(declaration)
        self.assertEqual(operation_observation.CURRENTNESS_REASONS,
                         frozenset(re.findall(r'"([a-z-]+)"', declaration[1])))
        for reason in sorted(operation_observation.CURRENTNESS_REASONS):
            for retryable in (False, True):
                with self.subTest(reason=reason, retryable=retryable):
                    observation = self.observe(self.response(reason, retryable))
                    self.assertEqual(observation["failureDetail"], {
                        "kind": "admission.currentness", "reason": reason, "retryable": retryable})

    def test_unknown_ambiguous_or_private_detail_shapes_are_not_retained(self):
        original = self.response()
        variants = []
        for category in ("transport-failure", "not-found", "unknown"):
            changed = copy.deepcopy(original)
            changed["category"] = category
            variants.append(changed)
        for retryable in (None, 0, 1, "true"):
            changed = copy.deepcopy(original)
            changed["error"]["retryable"] = retryable
            variants.append(changed)
        for detail in (None, [], {}, [None], [{"kind": "private", "fields": {"reason": "admission-clock-lease-uncovered"}}],
                       [{"kind": "admission.currentness", "fields": {"reason": "private-fixture-value"}}],
                       [{"kind": "admission.currentness", "fields": {"reason": "admission-clock-lease-uncovered", "secret": "private-fixture-value"}}],
                       [{"kind": "admission.currentness", "fields": {"reason": "admission-clock-lease-uncovered"}, "extra": "private-fixture-value"}],
                       original["error"]["details"] * 2):
            changed = copy.deepcopy(original)
            changed["error"]["details"] = detail
            variants.append(changed)
        for changed in variants:
            with self.subTest(response=changed):
                self.assertNotIn("failureDetail", self.observe(changed))

    def test_known_terminal_result_does_not_create_an_uncertainty_observation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            controller = journal.Journal(root, "node", "examples")
            response = self.response()
            response["outcomeKnown"] = True
            self.assertEqual(controller.execute("deployment", {}, Mock(return_value=response)), response)
            self.assertIsNone(controller.read()["pending"])
            self.assertEqual(len(controller.read()["history"]), 1)
            self.assertFalse((root / "last-operation-observation.json").exists())


if __name__ == "__main__":
    unittest.main()

"""Native close observations cannot invent approval, commitment or delivery."""
import copy
from types import SimpleNamespace
import unittest

from tools.java_transaction_qualification import configuration as cfg, pending_restore as pending, staging


def inspection():
    return {"action": "inspect-close-effects", "planDigest": "sha256:" + "a" * 64,
        "proposedOutcome": "closed-without-redrive", "recoveryRemainsPaused": True,
        "plan": {"schemaVersion": "lsf.effect-recovery-close.v1", "operatorId": cfg.OPERATOR,
            "operationId": "close-original", "scope": {"tenant": cfg.TENANT,
                "namespace": cfg.NAMESPACE, "incarnation": 1},
            "expectedView": list(b"NV\x02" + bytes([19]) * 32
                + b"".join(n.to_bytes(8, "little") for n in (1, 2, 3, 4))),
            "expectedGuard": [1, 2, 3], "lossWindowDigest": [4] * 32, "reason": pending.REASON,
            "effects": [{"effectId": "b" * 64, "originalDigest": [5] * 32,
                "payloadDigest": [6] * 32, "historyDigest": [7] * 32,
                "originalDisposition": "Uncertain", "originalClockMillis": 100}]}}


def receipt(inspected):
    return {"action": "close-effects", "recoveryRemainsPaused": True,
        "providerAcknowledgementInferred": False,
        "receipt": {"schemaVersion": "lsf.effect-recovery-close.v1", "outcome": "closed-without-redrive",
            "plan": copy.deepcopy(inspected["plan"]), "acknowledgement": [170] * 32,
            "observedAtMillis": 101}}


class PendingRestoreOracle(unittest.TestCase):
    def test_plan_preserves_actual_uncertain_identity_and_original_view(self):
        value = inspection()
        self.assertIs(pending.close_plan(value, "close-original", "b" * 64,
            value["plan"]["expectedView"]), value["plan"])
        for key, changed in (("operatorId", "foreign"), ("operationId", "later"),
                             ("reason", "inferred delivery"), ("approved", True)):
            bad = copy.deepcopy(value)
            bad["plan"][key] = changed
            with self.subTest(field=key), self.assertRaises(ValueError):
                pending.close_plan(bad, "close-original", "b" * 64, value["plan"]["expectedView"])
        for changed in ("Pending", "ProviderAcknowledged", "DeadLettered"):
            bad = copy.deepcopy(value)
            bad["plan"]["effects"][0]["originalDisposition"] = changed
            with self.subTest(disposition=changed), self.assertRaises(ValueError):
                pending.close_plan(bad, "close-original", "b" * 64, value["plan"]["expectedView"])

    def test_plan_refuses_foreign_scope_bool_counts_and_changed_original_bytes(self):
        value = inspection()
        for scope in ({"tenant": "foreign", "namespace": cfg.NAMESPACE, "incarnation": 1},
                      {"tenant": cfg.TENANT, "namespace": cfg.NAMESPACE, "incarnation": True}):
            bad = copy.deepcopy(value)
            bad["plan"]["scope"] = scope
            with self.assertRaises(ValueError):
                pending.close_plan(bad, "close-original", "b" * 64, value["plan"]["expectedView"])
        for key, changed in (("originalClockMillis", True), ("payloadDigest", [0] * 32),
                             ("historyDigest", [True] * 32), ("effectId", "c" * 64)):
            bad = copy.deepcopy(value)
            bad["plan"]["effects"][0][key] = changed
            with self.subTest(field=key), self.assertRaises(ValueError):
                pending.close_plan(bad, "close-original", "b" * 64, value["plan"]["expectedView"])

    def test_close_receipt_does_not_supply_provider_ack_or_reconstructed_plan(self):
        value = inspection()
        observed = receipt(value)
        self.assertIs(pending.close_receipt(observed, value), observed["receipt"])
        for key, changed in (("outcome", "provider-acknowledged"), ("acknowledgement", [1] * 32),
                             ("observedAtMillis", 99), ("observedAtMillis", True)):
            bad = copy.deepcopy(observed)
            bad["receipt"][key] = changed
            with self.subTest(field=key), self.assertRaises(ValueError):
                pending.close_receipt(bad, value)
        bad = copy.deepcopy(observed)
        bad["receipt"]["plan"]["effects"][0]["effectId"] = "c" * 64
        with self.assertRaises(ValueError):
            pending.close_receipt(bad, value)
        bad = dict(observed, providerAcknowledgementInferred=True)
        with self.assertRaises(ValueError):
            pending.close_receipt(bad, value)

    def test_retirement_and_failed_process_cannot_prove_wrong_ack_did_not_commit(self):
        value = {"operationSucceeded": False, "result": None,
            "failure": {"stage": "review", "failure": {"owner": "storage", "reason": "unavailable"}},
            "catalogsRetired": True, "retirement": {"clean": True, "physicallyRetired": True,
                "liveWorkers": 0, "acceptedJobs": 0, "threadsJoined": 4}}
        pending.wrong_ack_refused(value)
        for reason in ("commitUncertain", "conflict", "invalid"):
            bad = copy.deepcopy(value)
            bad["failure"]["failure"]["reason"] = reason
            with self.assertRaises(ValueError):
                pending.wrong_ack_refused(bad)
        bad = copy.deepcopy(value)
        bad["retirement"]["physicallyRetired"] = False
        with self.assertRaises(ValueError):
            pending.wrong_ack_refused(bad)

    def test_programme_is_pinned_and_cannot_reuse_default_or_diagnostic_candidate(self):
        args = SimpleNamespace(native_source_commit="a" * 40, conductor_source_commit="b" * 40,
            portable="original", prepare_authority_only=True, resume_candidate=None,
            candidate_digest=None, recovery_helper="actual", pending_restore_only=False)
        ordinary = staging.sources(args)
        self.assertNotIn("programme", ordinary)
        args.pending_restore_only = True
        self.assertEqual(staging.sources(args)["programme"], "signed-java-unresolved-effect-restore-v3")
        self.assertNotEqual(staging.sources(args), ordinary)
        args.recovery_helper = None
        with self.assertRaises(ValueError):
            staging.mode(args)


if __name__ == "__main__":
    unittest.main()

"""Keep optional library hash entropy separate from ordinary runtime authority."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools.dotnet_guest import entropy_grants as grants, runtime
from tools.guest_runtime_profiles import profiles
from tools.phase2_operator_process import WorkflowError


class ExplicitEntropyAuthority(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lsf-dotnet-entropy-grants-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.commands = []
        def command(*args, **kwargs):
            self.commands.append((args, kwargs))
        self.client = SimpleNamespace(directory=self.root, call=command)
        self.target = {"service": "examples/my-greeting", "generation": "3",
            "grants": [{"capability": runtime.CLOCK, "policy": "clock-allow"}]}
        self.descriptor = {"id": grants.PROVIDER, "tenant": "examples", "service": "entropy-host",
            "capability": runtime.RANDOM, "profile": grants.PROFILE,
            "configurationDigest": "sha256:" + "a" * 64, "configurationEpoch": "1"}
        self.node = SimpleNamespace(startup_record={"providers": [self.descriptor]})
        self.denied = {"exitCode": 4, "response": {"category": "platform-failure", "outcomeKnown": True,
            "error": {"code": "permission-denied"}, "data": {
                "consumption": {"cpuFuel": "0", "peakMemoryBytes": "0", "effectCount": 0}}}}

    def test_explicit_world_is_captured_without_changing_ordinary_application_source(self):
        (self.root / "wit").mkdir()
        path = self.root / "wit/world.wit"
        path.write_text("package examples:greeting@1.0.0;\nworld service {\n    import " + runtime.CLOCK + ";\n}\n")
        source = self.root / "Main.cs"
        source.write_bytes(b"unchanged ordinary library call sites")
        grants.declare(self.root)
        self.assertEqual(source.read_bytes(), b"unchanged ordinary library call sites")
        self.assertIn("import " + runtime.RANDOM + ";", path.read_text())
        self.assertTrue((self.root / "wit/deps/random/package.wit").is_file())
        before = path.read_bytes()
        with self.assertRaisesRegex(WorkflowError, "fixture-world"):
            grants.declare(self.root)
        self.assertEqual(path.read_bytes(), before)

    def test_configuration_adds_only_one_explicit_consumer_and_keeps_defaults(self):
        settings = {"providers": {"clockMonotonic": {"identity": {"id": "clock"}},
            "bindings": [{"name": "clock-greeting", "contract": runtime.CLOCK}]}}
        original = copy.deepcopy(settings)
        self.assertEqual(set(profiles("dotnet")), {"clockMonotonic"})
        grants.configure(settings)
        self.assertEqual(settings["providers"]["clockMonotonic"], original["providers"]["clockMonotonic"])
        self.assertEqual(settings["providers"]["bindings"][0], original["providers"]["bindings"][0])
        selected = settings["providers"]["bindings"][1]
        self.assertEqual(selected["consumerService"], "examples/my-greeting")
        self.assertEqual(selected["contract"], runtime.RANDOM)
        self.assertEqual(selected["providerBinding"], grants.BINDING)
        with self.assertRaisesRegex(WorkflowError, "already-present"):
            grants.configure(settings)
        for service in ("production/app", "examples/../app", "examples/app\n", None):
            with self.subTest(service=service), self.assertRaisesRegex(WorkflowError, "fixture-service"):
                grants.configure({"providers": {"bindings": []}}, service=service)

    def test_provider_binding_capacity_is_unchanged_and_rejection_does_not_mutate(self):
        settings = {"providers": {"bindings": [{"name": str(i)} for i in range(16)]}}
        original = copy.deepcopy(settings)
        with self.assertRaisesRegex(WorkflowError, "binding-bound"):
            grants.configure(settings)
        self.assertEqual(settings, original)

    def test_policy_follows_real_pre_store_denial_and_preserves_clock_grant(self):
        result = {}
        with patch("tools.rust_capsule_node.call", return_value=self.denied) as invoke, \
                patch("tools.rust_capsule_node.deploy", return_value={"selected": True}) as deploy:
            observed = grants.grant(self.client, self.node, self.root / "deployment.json", "publication:exact",
                self.target, result)
        self.assertEqual(observed, {"selected": True})
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual(len(self.commands), 2)
        self.assertEqual(deploy.call_count, 1)
        self.assertEqual(deploy.call_args.kwargs["generation"], "3")
        self.assertEqual(deploy.call_args.kwargs["grants"], [*self.target["grants"],
            {"capability": runtime.RANDOM, "policy": grants.POLICY}])
        binding = json.loads((self.root / (grants.PROVIDER + "-binding.json")).read_bytes())
        policy = json.loads((self.root / (grants.PROVIDER + "-policy.json")).read_bytes())
        self.assertEqual(binding["restriction"], {"operations": ["bytes"]})
        self.assertEqual(binding["configurationDigest"], self.descriptor["configurationDigest"])
        rule = policy["rules"][0]
        self.assertEqual(rule["services"], [self.target["service"]])
        self.assertEqual(rule["publications"], ["publication:exact"])
        self.assertEqual(rule["operations"], ["bytes"])
        self.assertEqual(rule["ceiling"], {"operations": 16, "inputBytes": 8,
            "outputBytes": 4096, "wallTimeMillis": 5000})
        self.assertEqual(result["noncryptoEntropyAuthority"]["secureRandom"], "unchanged-denial")

    def test_uncertain_or_dispatched_guest_failure_never_creates_entropy_authority(self):
        invalid = []
        for key, value in (("cpuFuel", "1"), ("peakMemoryBytes", "65536"), ("effectCount", 1)):
            denied = copy.deepcopy(self.denied)
            denied["response"]["data"]["consumption"][key] = value
            invalid.append(denied)
        denied = copy.deepcopy(self.denied)
        denied["response"]["outcomeKnown"] = False
        invalid.append(denied)
        denied = copy.deepcopy(self.denied)
        denied["response"]["error"]["code"] = "guest-trap"
        invalid.append(denied)
        for denied in invalid:
            with self.subTest(denied=denied), patch("tools.rust_capsule_node.call", return_value=denied), \
                    patch("tools.rust_capsule_node.deploy") as deploy, \
                    self.assertRaisesRegex(WorkflowError, "requires-explicit-grant"):
                grants.grant(self.client, self.node, self.root / "deployment.json", "publication:exact",
                    self.target, {})
            deploy.assert_not_called()
        self.assertEqual(self.commands, [])
        self.assertFalse((self.root / (grants.PROVIDER + "-policy.json")).exists())

    def test_provider_epoch_profile_and_clock_boundary_are_not_guessed(self):
        for key, value in (("configurationEpoch", "2"), ("profile", "unreviewed"),
                           ("tenant", "other"), ("service", "other"), ("capability", runtime.CLOCK)):
            with self.subTest(key=key), patch("tools.rust_capsule_node.call", return_value=self.denied), \
                    self.assertRaisesRegex(WorkflowError, "installation-identity"):
                grants.grant(self.client, SimpleNamespace(startup_record={"providers": [{**self.descriptor, key: value}]}),
                    self.root / "deployment.json", "publication:exact", self.target, {})
        for existing in ([], [{"capability": runtime.RANDOM, "policy": "already"}]):
            with self.subTest(existing=existing), patch("tools.rust_capsule_node.call") as invoke, \
                    self.assertRaisesRegex(WorkflowError, "existing-grants"):
                grants.grant(self.client, self.node, self.root / "deployment.json", "publication:exact",
                    {**self.target, "grants": existing}, {})
            invoke.assert_not_called()
        self.assertEqual(self.commands, [])


if __name__ == "__main__":
    unittest.main()

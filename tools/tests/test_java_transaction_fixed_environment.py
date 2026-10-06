"""Reviewed fixture selectors cannot refresh policy, tools or current hosts."""
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest

from tools.java_transaction_qualification import fixed_environment as fixed
from tools.java_transaction_qualification import reviewed_tls
from tools.java_transaction_qualification.inputs import digest


def fixture(root):
    policies = root / "policies"
    policies.mkdir()
    rows = []
    for index in range(10):
        kind = "provider-binding" if index < 5 else "policy"
        name = f"original-{index}"
        raw = (json.dumps({"original": index}, separators=(",", ":")) + "\n").encode()
        file = f"authority-{kind}-{name}.json"
        (policies / file).write_bytes(raw)
        rows.append({"kind": kind, "id": name, "file": file,
            "operationId": f"java-reviewed-{kind}-{name}", "expectedGeneration": 0,
            "digest": digest(raw), "bytes": len(raw)})
    hosts = {"originalProvider": "native-only", "epoch": 1}
    raw = json.dumps(hosts).encode()
    (root / "observed-native-hosts-reference.json").write_bytes(raw)
    value = {"schemaVersion": "latent.java-transaction.stable-unsigned-review.v1",
        "nativeSource": "a" * 40, "originalCompilerSource": "ff9ecd0733456bceacf5b96f14274b9c2dc0e8e6",
        "nativeTools": {"original": "tool"}, "unsignedMutations": rows,
        "observedHostsReferenceSha256": digest(raw),
        "recipient": {"port": 56599, "origin": {"scheme": "https", "host": "localhost", "port": 56599},
            "providerIncarnation": "f" * 64, "ingressAuthority": "localhost:51231", "ingressBind": "127.0.0.1:51231"},
        "environment": {"originalNonrenewableQualificationSeconds": 1200,
            "maximumNodeSessions": 6, "maximumOfflineNativeActions": 12}}
    args = SimpleNamespace(native_source_commit="a" * 40, reviewed_policy_environment=root / "review.json")
    save(args, value)
    return args, value, hosts


def save(args, value):
    raw = json.dumps(value).encode()
    args.reviewed_policy_environment.write_bytes(raw)
    args.reviewed_policy_environment_digest = digest(raw)


class ReviewedEnvironment(unittest.TestCase):
    def test_default_tls_and_closed_original_native_three_file_selection(self):
        self.assertIsNone(reviewed_tls.selected(SimpleNamespace(), None))
        with tempfile.TemporaryDirectory() as temp:
            args, value, _ = fixture(Path(temp))
            folder = Path(temp) / "tls-fixture"
            folder.mkdir()
            rows = []
            for name in sorted(reviewed_tls.FILES):
                raw = ("native-fixture-" + name).encode()
                (folder / name).write_bytes(raw)
                rows.append({"file": name, "bytes": len(raw), "digest": digest(raw)})
            value["reviewedTlsFixture"] = {"directory": "tls-fixture", "producerNativeSource": args.native_source_commit,
                                           "files": rows}
            save(args, value)
            self.assertEqual(fixed.load(args), value)
            self.assertEqual(set(reviewed_tls.selected(args, value)[1]), reviewed_tls.FILES)
            (folder / "ca.der").write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "tls-byte-drift"):
                fixed.load(args)

    def test_tls_hardlinks_and_extra_records_cannot_borrow_native_fixture_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            args, value, _ = fixture(Path(temp))
            folder = Path(temp) / "tls-fixture"
            folder.mkdir()
            rows = []
            for name in sorted(reviewed_tls.FILES):
                raw = name.encode()
                (folder / name).write_bytes(raw)
                rows.append({"file": name, "bytes": len(raw), "digest": digest(raw)})
            value["reviewedTlsFixture"] = {"directory": "tls-fixture", "producerNativeSource": args.native_source_commit,
                                           "files": rows}
            save(args, value)
            os.link(folder / "ca.der", Path(temp) / "foreign-alias")
            with self.assertRaisesRegex(ValueError, "tls-refuses-links"):
                fixed.load(args)

    def test_default_selection_has_no_review_or_fixed_environment(self):
        args = SimpleNamespace()
        self.assertIsNone(fixed.load(args))
        self.assertIsNone(fixed.identity(args))
        args.reviewed_policy_environment_digest = "sha256:" + "a" * 64
        with self.assertRaisesRegex(ValueError, "paired-reviewed"):
            fixed.load(args)

    def test_exact_review_pins_ports_incarnation_and_rejects_manifest_byte_drift(self):
        with tempfile.TemporaryDirectory() as temp:
            args, value, _ = fixture(Path(temp))
            self.assertEqual(fixed.load(args), value)
            self.assertEqual(fixed.identity(args)["recipient"], value["recipient"])
            args.reviewed_policy_environment.write_bytes(args.reviewed_policy_environment.read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "environment-byte-drift"):
                fixed.load(args)

    def test_host_tool_and_policy_programme_drift_refuse_before_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            args, value, hosts = fixture(Path(temp))
            client = SimpleNamespace(directory=Path(temp) / "policies")
            fixed.check_tools(args, value["nativeTools"])
            fixed.check_authority(args, client, hosts, value["unsignedMutations"])
            with self.assertRaisesRegex(ValueError, "native-tools-drift"):
                fixed.check_tools(args, {"changed": "tool"})
            with self.assertRaisesRegex(ValueError, "current-native-host-drift"):
                fixed.check_authority(args, client, dict(hosts, epoch=2), value["unsignedMutations"])
            with self.assertRaisesRegex(ValueError, "current-policy-programme-drift"):
                fixed.check_authority(args, client, hosts, list(reversed(value["unsignedMutations"])))

    def test_selected_environment_cannot_widen_bounds_alias_ports_or_supply_bool_counters(self):
        with tempfile.TemporaryDirectory() as temp:
            args, value, _ = fixture(Path(temp))
            for key, changed in (("port", True), ("port", 0), ("ingressBind", "0.0.0.0:51231"),
                                 ("providerIncarnation", "foreign")):
                old = value["recipient"][key]
                value["recipient"][key] = changed
                save(args, value)
                with self.subTest(key=key), self.assertRaises(ValueError):
                    fixed.load(args)
                value["recipient"][key] = old
            value["environment"]["maximumOfflineNativeActions"] = 13
            save(args, value)
            with self.assertRaisesRegex(ValueError, "campaign-bounds"):
                fixed.load(args)

    def test_changed_guest_or_compiler_identity_cannot_borrow_reviewed_publication_authority(self):
        with tempfile.TemporaryDirectory() as temp:
            args, value, _ = fixture(Path(temp))
            item = SimpleNamespace(name="original", component_digest="component", companion_digest="companion",
                source_digest="source", compiler_source=value["originalCompilerSource"],
                host_abi_digest="abi", requirements_digest=None)
            value["originalCompiledInputs"] = [{"variant": item.name, "componentDigest": item.component_digest,
                "companionDigest": item.companion_digest, "sourceDigest": item.source_digest,
                "compilerSource": item.compiler_source, "hostAbiDigest": item.host_abi_digest,
                "requirementsDigest": item.requirements_digest}]
            save(args, value)
            fixed.check_inputs(args, [item])
            item.compiler_source = "changed-compiler"
            with self.assertRaisesRegex(ValueError, "compiled-input-drift"):
                fixed.check_inputs(args, [item])

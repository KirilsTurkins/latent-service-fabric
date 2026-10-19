"""The worker-stack reference preserves exact source/lock and closed observations."""
import hashlib
import json
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import qualify_node_worker_stacks as reference


class NodeWorkerStackReference(unittest.TestCase):
    def test_fixed_registry_closure_matches_maintained_lock_and_unknown_inputs_refuse(self):
        raw = reference.locked(reference.ROOT)
        self.assertEqual(len(tomllib.loads(raw.decode())["package"]), 17)
        self.assertEqual(hashlib.sha256(raw).hexdigest(), reference.LOCK_SHA256)
        workspace = (reference.ROOT / "Cargo.lock").read_bytes()
        for kind in ("identity", "local", "registry"):
            changed = raw + b"\n" if kind == "identity" else raw
            if kind == "local":
                changed = changed.replace(b'name = "node-worker-stack-reference"', b'name = "unknown"')
            if kind == "registry":
                chosen = next(r["checksum"] for r in tomllib.loads(raw.decode())["package"] if "source" in r)
                changed = changed.replace(chosen.encode(), b"0" * 64)
            selected = reference.LOCK_SHA256 if kind == "identity" else hashlib.sha256(changed).hexdigest()
            with self.subTest(kind=kind), patch.object(reference, "LOCK_SHA256", selected), \
                    patch.object(reference, "read", side_effect=[changed, workspace]), self.assertRaises(ValueError):
                reference.locked(reference.ROOT)

    def test_old_semantic_derivation_changes_only_explicit_stack_size_and_rejects_unknown_shape(self):
        source = (reference.ROOT / reference.PROFILE).read_bytes()
        old = reference.original_semantics(source)
        line = b"            .thread_stack_size(THREAD_STACK_BYTES)\n"
        self.assertEqual(source.replace(line, b"", 1), old)
        self.assertEqual(source.count(line), 1)
        for changed in (old, source + line):
            with self.assertRaisesRegex(ValueError, "preimage"):
                reference.original_semantics(changed)

    def test_only_five_named_zero_filtered_successes_are_evidence(self):
        raw = ("\n".join("test " + n + " ... ok" for n in sorted(reference.CASES))
               + "\ntest result: ok. 5 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 0.1s\n").encode()
        self.assertEqual(reference.evidence(raw, set(reference.CASES)), sorted(reference.CASES))
        for changed in (raw.replace(sorted(reference.CASES)[0].encode(), b"unknown"),
                        raw.replace(b"0 filtered out", b"1 filtered out"), raw + b"test unknown ... ok\n",
                        raw.replace(b" ... ok", b" ... FAILED", 1), b"x" * (1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                reference.evidence(changed, set(reference.CASES))

    def test_exact_four_bounded_native_mappings_and_two_ambient_old_refusals_are_required(self):
        new = f"STACK_MAPPING usable={reference.STACK - 4096} guard=4096 envelope={reference.STACK + reference.GUARD}\n".encode() * 4
        old = f"STACK_MAPPING_REFUSED usable={reference.AMBIENT - 4096} guard=4096 envelope={reference.STACK + reference.GUARD}\n".encode() * 2
        self.assertEqual(len(reference.measurements(new, old=False)), 4)
        self.assertEqual(len(reference.measurements(old, old=True)), 2)
        for raw, label in ((new, False), (old, True)):
            for changed in (raw[:-1], raw + raw, raw.replace(b"guard=4096", b"guard=0"),
                            raw.replace(b"envelope=2162688", b"envelope=9999999")):
                # A missing final newline is permitted by a bounded line parser.
                if changed == raw[:-1]:
                    self.assertEqual(len(reference.measurements(changed, old=label)), 2 if label else 4)
                    continue
                with self.assertRaises(ValueError):
                    reference.measurements(changed, old=label)
        with self.assertRaises(ValueError):
            reference.measurements(new.replace(str(reference.STACK - 4096).encode(), str(reference.AMBIENT).encode()), old=False)

    def test_same_target_executable_alias_and_later_overwrite_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            old, new = Path(temporary) / "old", Path(temporary) / "new"
            old.write_bytes(b"original ambient source executable")
            new.write_bytes(b"bounded production source executable")
            paths = {"old": old, "new": new}
            identities = {label: reference.digest(path, 4096) for label, path in paths.items()}
            reference.verify_executables(paths, identities)
            with self.assertRaisesRegex(ValueError, "alias"):
                reference.verify_executables({"old": new, "new": new}, identities)
            old.write_bytes(new.read_bytes())
            with self.assertRaisesRegex(ValueError, "changed"):
                reference.verify_executables(paths, identities)

    def test_unsupported_platform_refuses_before_output_or_native_process(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "not-created"
            with patch.object(reference.artifacts, "require_source"), \
                    patch.object(reference.sys, "platform", "unsupported"), \
                    patch.object(reference, "run_owned", side_effect=AssertionError("no process")), \
                    self.assertRaisesRegex(ValueError, "platform"):
                reference.qualify(reference.ROOT, output, "a" * 40)
            self.assertFalse(output.exists())

    def test_changed_source_fails_before_any_build_or_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "not-created"
            with patch.object(reference.artifacts, "require_source"), \
                    patch.object(reference, "read", side_effect=ValueError("changed-source")), \
                    patch.object(reference, "run_owned", side_effect=AssertionError("no native process")), \
                    self.assertRaisesRegex(ValueError, "changed-source"):
                reference.qualify(reference.ROOT, output, "a" * 40)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()

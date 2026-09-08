"""Real Rust-v0 allocation stacks plus rehashed symbol-proof crossing regressions."""
import base64
import gzip
import json
from pathlib import Path
import tempfile
import unittest

from tools.artifact_identity_evidence.heaptrack import replay
from tools.artifact_identity_runner.files import reference
from tools.optimization_cache_lookup import allocations, model
from tools.optimization_cache_lookup.files import Artifacts, inventory

MANGLED = "_RNvNtNtCsfuGAVL8Xcft_15latent_wasmtime5cache11measurement19measured_cache_hits"


class SymbolFixture:
    def __init__(self, root):
        self.root = Path(root)
        value = json.loads(gzip.decompress(Path(__file__).with_name("fixtures").joinpath("cache_lookup_mangled.json.gz").read_bytes()))
        assert "not qualifying benchmark evidence" in value["purpose"]
        self.put("interpreted.heaptrack", value["profile"])
        self.put("allocations.folded.gz", base64.b64decode(value["folded"]))
        self.put("symbols.log", value["demangled"])
        self.put("symbols-raw.log", value["raw"])
        binary_path = value["profile"].splitlines()[1][2:].split(" ")[0]
        self.binary = {"path": "builds/control/latent-wasmtime-cache-lookup", "sha256": "sha256:" + "a" * 64, "bytes": "1"}
        self.tool = {"path": "/usr/bin/x86_64-linux-gnu-nm", "sha256": "sha256:" + "b" * 64}
        self.proof = {}
        for ordinal, (kind, name, command) in enumerate((
                ("demangled", "symbols.log", [self.tool["path"], "--defined-only", "--demangle", binary_path]),
                ("raw", "symbols-raw.log", [self.tool["path"], "--defined-only", binary_path]))):
            receipt = {"process_id": 101 + ordinal, "start_time_ticks": str(1000 + ordinal), "role": "artifact-identity-helper",
                       "executable_sha256": self.tool["sha256"], "reaped": True, "output_closed": True, "exit_code": 0}
            self.put(name + ".process.json", json.dumps(receipt))
            row = {"command": command, "process": receipt, "log": self.ref(name)}
            if kind == "demangled":
                self.proof.update(row)
            else:
                self.proof["raw"] = row
        self.record = {"command": ["heaptrack", "--output", "profile", *value["profile"].splitlines()[1][2:].split(" ")],
                       "profile_refs": {name: self.ref(path) for name, path in
                                        (("interpreted", "interpreted.heaptrack"), ("allocations", "allocations.folded.gz"))}}

    def ref(self, name):
        return reference(self.root / name, self.root)

    def put(self, name, value):
        (self.root / name).write_bytes(value if isinstance(value, bytes) else value.encode())

    def verify(self):
        # Every mutation is followed by fresh artifact hashes and receipts.
        self.proof["log"] = self.ref("symbols.log")
        self.proof["raw"]["log"] = self.ref("symbols-raw.log")
        self.record["profile_refs"]["interpreted"] = self.ref("interpreted.heaptrack")
        self.record["profile_refs"]["allocations"] = self.ref("allocations.folded.gz")
        artifacts = Artifacts(self.root, inventory(self.root))
        return allocations.attribute(self.record, self.binary, self.proof, self.tool, artifacts,
                                     replay(self.root / "interpreted.heaptrack"))


class SymbolIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cache-symbol-replay-")
        self.addCleanup(self.temp.cleanup)
        self.fixture = SymbolFixture(self.temp.name)

    def test_actual_v0_and_source_suffix_replay_agree(self):
        result = self.fixture.verify()
        self.assertEqual(result["status"], "available")
        self.assertEqual((result["allocation_count"], result["allocated_bytes"]), ("256", "3584"))
        self.assertEqual(result["verified_symbol"], {"address": "3ebb70", "type": "t", "demangled": model.SYMBOL, "raw": MANGLED})

    def test_rehashed_raw_address_or_type_cannot_cross_function(self):
        for line in (f"00000000003ebb71 t {MANGLED}\n", f"00000000003ebb70 T {MANGLED}\n"):
            with self.subTest(line=line):
                self.fixture.put("symbols-raw.log", line)
                with self.assertRaisesRegex(ValueError, "address-type-missing-or-ambiguous"):
                    self.fixture.verify()

    def test_raw_nm_must_inspect_the_same_executable_with_same_tool(self):
        self.fixture.proof["raw"]["command"][-1] += "-other"
        with self.assertRaisesRegex(ValueError, "raw-symbol-command-crossed"):
            self.fixture.verify()

    def test_ambiguous_raw_alias_does_not_prove_zero(self):
        self.fixture.put("symbols-raw.log", f"00000000003ebb70 t {MANGLED}\n00000000003ebb70 t alias\n")
        with self.assertRaisesRegex(ValueError, "address-type-missing-or-ambiguous"):
            self.fixture.verify()

    def test_missing_demangled_symbol_is_unavailable_not_zero(self):
        self.fixture.put("symbols.log", "00000000003ebb70 t other_function\n")
        result = self.fixture.verify()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["allocation_count"])
        self.assertEqual(result["reason"], "missing-or-ambiguous-symbol")

    def test_false_source_suffix_cannot_hide_measured_allocations(self):
        path = self.fixture.root / "allocations.folded.gz"
        self.fixture.put(path.name, gzip.compress(gzip.decompress(path.read_bytes()).replace(
            (MANGLED + " (measurement.rs)").encode(), (MANGLED + " (different.rs)").encode()), mtime=0))
        with self.assertRaisesRegex(ValueError, "folded-frame-attribution-mismatch"):
            self.fixture.verify()

    def test_mangled_name_in_a_foreign_module_cannot_be_attributed(self):
        from tools.tests.test_optimization_cache_lookup import recording
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "raw.txt"
            path.write_bytes(recording(function=MANGLED))
            _, state = allocations.replay_attribution(path, "/other/latent-wasmtime-cache-lookup", (model.SYMBOL, MANGLED))
            self.assertEqual(state.named_count, 0)
            self.assertEqual(state.unresolved_count, 2)

    def test_valid_demangled_rendering_still_matches_same_verified_function(self):
        from tools.tests.test_optimization_cache_lookup import recording
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "raw.txt"
            path.write_bytes(recording())
            _, state = allocations.replay_attribution(path, "latent-wasmtime-cache-lookup", (model.SYMBOL, MANGLED))
            self.assertEqual((state.named_count, state.named_bytes), (2, 28))

    def synthetic_other_allocations(self, ip=1):
        from tools.tests.test_optimization_cache_lookup import recording
        data = recording(ip=ip, function="cache_setup")
        original = b"latent-wasmtime-cache-lookup"
        actual = self.fixture.record["command"][3].encode()
        data = data.replace(b"s " + format(len(original), "x").encode() + b" " + original + b"\n",
                            b"s " + format(len(actual), "x").encode() + b" " + actual + b"\n")
        data = data.replace(b"X /probe --bounded\n", b"X " + " ".join(self.fixture.record["command"][3:]).encode() + b"\n")
        self.fixture.put("interpreted.heaptrack", data)
        self.fixture.put("allocations.folded.gz", gzip.compress(b"main;cache_setup 2\n", mtime=0))

    def test_verified_symbol_and_resolved_other_allocations_can_prove_zero(self):
        self.synthetic_other_allocations()
        result = self.fixture.verify()
        self.assertEqual(result["status"], "available")
        self.assertEqual((result["allocation_count"], result["allocated_bytes"]), ("0", "0"))
        self.assertEqual(result["verified_symbol"]["raw"], MANGLED)

    def test_verified_symbol_with_unresolved_ip_is_unavailable_not_zero(self):
        self.synthetic_other_allocations(ip=0)
        result = self.fixture.verify()
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["allocation_count"])
        self.assertIsNone(result["allocated_bytes"])
        self.assertEqual(result["unresolved_allocation_count"], "2")

"""Recorded debug parser input, deliberately incapable of release qualification."""
import base64
import gzip
import json
from pathlib import Path

from tools.optimization_cache_lookup.files import Artifacts, inventory
from tools.optimization_backend_revision.cache.parse import parse


class Fixture:
    def __init__(self, root, variant="control"):
        self.root, self.variant = Path(root), variant
        path = Path(__file__).with_name("fixtures") / f"cache_behavior_{variant}.json.gz"
        value = json.loads(gzip.decompress(path.read_bytes()))
        assert "not release evidence" in value["purpose"]
        self.raw = value["raw"]
        # The original debug collector did not capture host metadata. Supplying
        # its known clock resolution tests raw parsing, not official provenance.
        self.raw["identity"]["environment"] = {"clock_ticks_per_second": 100}
        for name, encoded in value["files"].items():
            target = self.root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(base64.b64decode(encoded))

    def checkpoint(self, name):
        return next(row for row in self.raw["samples"] if row.get("label") == name and row["kind"] == "checkpoint")

    def parse(self):
        # Rehash every retained input after a test's semantic mutation; rejection
        # must come from replay, not a stale outer checksum.
        path = self.root / "cache.json"
        path.write_text(json.dumps(self.raw, separators=(",", ":")) + "\n", encoding="utf-8")
        artifacts = Artifacts(self.root, inventory(self.root))
        echo = {name: artifacts.rows["fixtures/key-0/echo-" + suffix] for name, suffix in
                (("component", "component.wasm"), ("contracts", "contracts.json"))}
        return parse(self.raw, self.raw["plan"], self.raw["identity"], artifacts, path, echo, self.variant)

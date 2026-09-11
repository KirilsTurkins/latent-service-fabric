"""Source/recipe/retained-byte binding tests without invoking a compiler."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.artifact_identity_runner.files import reference, write_json
from tools.optimization_docker import build, images


class DockerBuildBindings(unittest.TestCase):
    def receipt(self, root):
        def artifact(name, data=b"synthetic unit fixture"):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return reference(path, root)
        inputs = {name: artifact("source/" + name, name.encode()) for name in build.SOURCE_FILES}
        binaries = {key: artifact("binaries/" + name) for key, name in images.BINARIES.items()}
        owner = {"exit_code": 0, "reaped": True, "output_closed": True}
        log = artifact("build.log")
        write_json(root / "build.log.process.json", owner)
        source = {"commit": "1" * 40, "tree": "2" * 40, "clean": True,
                  "cargo_lock_sha256": inputs["Cargo.lock"]["sha256"]}
        overrides = {**build.OVERRIDES,
                     "recipe_sha256": inputs["tools/phase0_build_environment.sh"]["sha256"],
                     "optimization_recipe_sha256": inputs["tools/build_optimization_bench.sh"]["sha256"]}
        return {"schema": build.SCHEMA, "source": source, "source_after": copy.deepcopy(source),
                "source_path": "/synthetic/source", "target_path": str(build.TARGET),
                "build": {"profile": "release", "overrides": overrides}, "inputs": inputs,
                "executables": binaries, "component": artifact("component.wasm", b"\0asm\x0d\0\x01\0"),
                "fixtures": {}, "command": list(build.RECIPE), "process": owner, "log": log}

    def test_source_recipe_and_exact_byte_receipt_accepts_then_tamper_rejects(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            value = self.receipt(root)
            self.assertEqual(build.validate_receipt(value, root), value)
            (root / value["executables"]["native"]["path"]).write_bytes(b"different binary")
            with self.assertRaises(ValueError):
                build.validate_receipt(value, root)

    def test_changed_source_recipe_or_unclean_owner_cannot_qualify_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self.receipt(root)
            def mutate_source(row):
                row["source_after"]["commit"] = "3" * 40
            def mutate_recipe(row):
                row["build"]["overrides"]["lto"] = "true"
            def mutate_owner(row):
                row["process"]["reaped"] = False
            for mutation in (mutate_source, mutate_recipe, mutate_owner):
                value = copy.deepcopy(original)
                mutation(value)
                with self.subTest(mutation=mutation.__name__), self.assertRaises(ValueError):
                    build.validate_receipt(value, root)

    def test_source_closure_includes_authoritative_metadata_and_excludes_historical_archives(self):
        names = [*build.SOURCE_FILES, "crates/latent-node/src/lib.rs", "api/service.proto",
                 "wit/runtime.wit", "schemas/capsule.schema.json", "examples/policies/default-log-policy.json",
                 "tools/optimization_docker/model.py", "tools/optimization-docker/app.Dockerfile",
                 "benchmarks/optimization/old/raw.tar.gz", "benchmarks/optimization/old/raw.gz.part-001"]
        with patch.object(build, "git", return_value="\n".join(names)):
            selected = build.input_names(Path("/synthetic/source"))
        self.assertEqual(set(selected), set(names[:-2]))


if __name__ == "__main__":
    unittest.main()

"""Image context/identity regression checks with small synthetic executables."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.artifact_identity_runner.files import reference
from tools.optimization_docker import images

ROOT = Path(__file__).resolve().parents[2]


class DockerImageContexts(unittest.TestCase):
    def fixture(self, root):
        (root / "binaries").mkdir()
        rows = {}
        for key, name in images.BINARIES.items():
            path = root / "binaries" / name
            path.write_bytes(("synthetic executable " + name).encode())
            rows[key] = reference(path, root)
        inputs = {}
        for name in ("app.Dockerfile", "client.Dockerfile"):
            relative = "tools/optimization-docker/" + name
            path = root / "source" / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / relative).read_bytes())
            inputs[relative] = reference(path, root)
        return {"executables": rows, "inputs": inputs}

    def test_contexts_share_wrapper_and_recipe_and_client_contains_only_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = self.fixture(root)
            contexts = images.prepare_contexts(build, root, ROOT)
            self.assertEqual(set(contexts), {"lsf", "native", "client"})
            self.assertEqual(set(contexts["lsf"]["executables"]), {"lsf", "cli", "wrapper"})
            self.assertEqual(set(contexts["native"]["executables"]), {"native", "wrapper"})
            self.assertEqual(set(contexts["client"]["executables"]), {"client"})
            for field in ("dockerfile",):
                self.assertEqual(contexts["lsf"][field]["sha256"], contexts["native"][field]["sha256"])
            self.assertEqual(contexts["lsf"]["executables"]["wrapper"]["sha256"],
                             contexts["native"]["executables"]["wrapper"]["sha256"])
            for row in contexts.values():
                recipe = (root / row["dockerfile"]["path"]).read_text()
                self.assertIn("FROM " + images.BASE, recipe)
                self.assertNotIn("apt", recipe)
                self.assertIn("--network=none", row["build_arguments"])
                self.assertIn("--pull=false", row["build_arguments"])

    def test_context_total_bound_is_checked_before_creating_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = self.fixture(root)
            with patch.object(images, "total_bytes", return_value=1024**3):
                with self.assertRaisesRegex(ValueError, "context-total-bound"):
                    images.prepare_contexts(build, root, ROOT)
            self.assertFalse((root / "images").exists())

    def test_recipe_tampering_cannot_supply_an_unbound_image_context(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            build = self.fixture(root)
            row = build["inputs"]["tools/optimization-docker/app.Dockerfile"]
            (root / row["path"]).write_bytes(b"FROM unpinned\n")
            with self.assertRaises(ValueError):
                images.prepare_contexts(build, root, ROOT)
            self.assertFalse((root / "images").exists())


class DockerImageIdentity(unittest.TestCase):
    def raw(self):
        # Engine29 can report an index digest as Id. It is deliberately distinct
        # from the manifest descriptor here; neither is called a config digest.
        return {"Id": "sha256:" + "a" * 64, "Os": "linux", "Architecture": "amd64", "Size": 100,
                "Config": {"Entrypoint": ["/opt/lsf/optimization-container"], "Env": ["PATH=/usr/bin"]},
                "RootFS": {"Type": "layers", "Layers": ["sha256:" + "b" * 64]}, "RepoDigests": [],
                "Descriptor": {"mediaType": "application/vnd.oci.image.index.v1+json",
                               "digest": "sha256:" + "c" * 64, "size": 8560}}

    def test_actual_id_config_descriptor_and_empty_repo_digests_stay_distinct(self):
        raw = self.raw()
        receipt = images.inspect_receipt("lsf", [raw], {"kind": "lsf", "base": images.BASE})
        self.assertEqual(receipt["image_id"], raw["Id"])
        self.assertEqual(receipt["descriptor"], raw["Descriptor"])
        self.assertEqual(receipt["config"], raw["Config"])
        self.assertEqual(receipt["repo_digests"], [])
        self.assertNotIn("config_digest", receipt)
        raw["Config"]["Env"].clear()
        self.assertEqual(receipt["config"]["Env"], ["PATH=/usr/bin"])

    def test_wrong_platform_entrypoint_digest_and_multiple_inspects_reject(self):
        for key, replacement in (("Architecture", "arm64"), ("Id", "sha256:short"),
                                 ("Config", {"Entrypoint": ["sh"]}), ("Size", True)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                images.inspect_receipt("lsf", {**self.raw(), key: replacement}, {"kind": "lsf", "base": images.BASE})
        with self.assertRaisesRegex(ValueError, "inspect-count"):
            images.inspect_receipt("lsf", [self.raw(), self.raw()], {"kind": "lsf", "base": images.BASE})


if __name__ == "__main__":
    unittest.main()

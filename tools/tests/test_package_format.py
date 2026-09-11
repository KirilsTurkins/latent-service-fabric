"""Independent schema and exact-byte known answers for the package format.

The graph helpers are fixture oracles, not an alternative production decoder.
Rust tests cover lexical JSON limits and consume this same small corpus.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "examples/package-format"
OCI = "application/vnd.oci.image.manifest.v1+json"
EMPTY_DIGEST = "sha256:44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
CONFIG_KEYS = ["formatVersion", "kind", "name", "version", "entrypoint"]
MANIFEST_KEYS = ["schemaVersion", "mediaType", "artifactType", "config", "layers"]


def sha256(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def compact(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_content(record: dict, data: bytes) -> None:
    require(len(data) == record["size"], "content size")
    require(sha256(data) == record["digest"], "content digest")


def check_paths(layers: list[dict]) -> None:
    paths = [layer["path"] for layer in layers]
    require(paths == sorted(paths) and len(set(paths)) == len(paths), "path order")
    folded = sorted(path.lower() for path in paths)
    require(len(set(folded)) == len(paths), "path case collision")
    for index, path in enumerate(folded):
        require(not any(other.startswith(path + "/") for other in folded[index + 1:]),
                "path prefix collision")


def check_graph(manifest_bytes: bytes, config_bytes: bytes, blobs: dict[str, bytes]) -> None:
    manifest = json.loads(manifest_bytes)
    config = json.loads(config_bytes)
    check_content(manifest["config"], config_bytes)
    require(manifest["artifactType"] == "application/vnd.latent." + config["kind"] + ".v1",
            "package kind")
    require(len(manifest["layers"]) == len(config["layers"]), "layer count")
    check_paths(config["layers"])
    for layer, descriptor in zip(config["layers"], manifest["layers"], strict=True):
        expected = {key: layer[key] for key in ("mediaType", "digest", "size")}
        expected["annotations"] = {
            "dev.latent.layer.role": layer["role"],
            "org.opencontainers.image.title": layer["path"],
        }
        require(expected == descriptor, "layer descriptor")
        check_content(layer, blobs[layer["path"]])
    entry = next((layer for layer in config["layers"] if layer["path"] == config["entrypoint"]), None)
    role = {"capsule": "component", "browser-assets": "asset", "ssr-package": "renderer"}[config["kind"]]
    require(entry is not None and entry["role"] == role, "entrypoint")
    if config["kind"] == "capsule":
        require(config["componentDigest"] == entry["digest"], "component digest")
        lock_layer = next(layer for layer in config["layers"] if layer["role"] == "wit-lock")
        check_lock(json.loads(blobs[lock_layer["path"]]), config, blobs)


def check_lock(lock: dict, config: dict, blobs: dict[str, bytes]) -> None:
    packages = lock["packages"]
    ids = [package["id"] for package in packages]
    require(ids == sorted(set(ids)), "lock package order")
    world_path, version = lock["world"].rsplit("@", 1)
    world_package = world_path.split("/", 1)[0] + "@" + version
    require(world_package in ids, "lock world membership")
    paths = [package["sourcePath"].lower() for package in packages]
    require(len(set(paths)) == len(paths), "lock source collision")
    graph = {package["id"]: package["dependencies"] for package in packages}
    for dependencies in graph.values():
        require(dependencies == sorted(set(dependencies)), "lock dependency order")
        require(all(dependency in graph for dependency in dependencies), "lock unknown dependency")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(package_id: str) -> None:
        require(package_id not in visiting, "lock cycle")
        if package_id in visited:
            return
        visiting.add(package_id)
        for dependency in graph[package_id]:
            visit(dependency)
        visiting.remove(package_id)
        visited.add(package_id)

    for package_id in ids:
        visit(package_id)
    contracts = next(layer for layer in config["layers"] if layer["role"] == "contracts")
    require(lock["contractsDigest"] == contracts["digest"], "lock contracts digest")
    layers = {layer["path"]: layer for layer in config["layers"]}
    for package in packages:
        source = layers.get(package["sourcePath"])
        require(source is not None and source["role"] == "asset" and source["mediaType"] == "text/plain",
                "lock source layer")
        require(source["digest"] == package["digest"], "lock source digest")
        content = blobs[package["sourcePath"]]
        content.decode("utf-8", errors="strict")
        check_content(source, content)


class PackageFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.index = json.loads((FIXTURES / "golden.json").read_bytes())
        cls.packages = {package["kind"]: package for package in cls.index["packages"]}
        cls.schemas = {}
        for name in ("config", "manifest", "evidence", "wit-lock"):
            schema = json.loads((ROOT / f"schemas/package-{name}.schema.json").read_bytes())
            Draft202012Validator.check_schema(schema)
            cls.schemas[name] = Draft202012Validator(schema)

    def package(self, kind: str = "capsule") -> tuple[dict, dict, dict[str, bytes]]:
        record = self.packages[kind]
        config = json.loads((FIXTURES / record["config"]["file"]).read_bytes())
        manifest = json.loads((FIXTURES / record["manifest"]["file"]).read_bytes())
        blobs = {item["path"]: (FIXTURES / item["file"]).read_bytes() for item in record["blobs"]}
        return config, manifest, blobs

    def assert_schema_invalid(self, name: str, value: dict) -> None:
        self.assertFalse(self.schemas[name].is_valid(value), f"{name} accepted {value!r}")

    def test_golden_inventory_hashes_and_byte_sizes(self) -> None:
        records = [self.index["emptyConfig"]]
        for package in self.index["packages"]:
            records.extend([package["config"], package["manifest"], *package["blobs"]])
        for evidence in self.index["evidence"]:
            records.extend([evidence["manifest"], evidence["payload"]])
        names = [record["file"] for record in records]
        self.assertEqual(len(names), len(set(names)))
        actual = {path.relative_to(FIXTURES).as_posix() for path in FIXTURES.rglob("*")
                  if path.is_file() and path.name not in {"README.md", "golden.json"}}
        self.assertEqual(set(names), actual)
        for record in records:
            with self.subTest(file=record["file"]):
                check_content(record, (FIXTURES / record["file"]).read_bytes())
        self.assertEqual(sha256(b"{}"), EMPTY_DIGEST)
        self.assertEqual((FIXTURES / self.index["emptyConfig"]["file"]).read_bytes(), b"{}")

    def test_all_package_schemas_graphs_and_canonical_known_answers(self) -> None:
        for kind, record in self.packages.items():
            with self.subTest(kind=kind):
                config, manifest, blobs = self.package(kind)
                self.schemas["config"].validate(config)
                self.schemas["manifest"].validate(manifest)
                config_bytes = (FIXTURES / record["config"]["file"]).read_bytes()
                manifest_bytes = (FIXTURES / record["manifest"]["file"]).read_bytes()
                self.assertEqual(compact(config), config_bytes)
                self.assertEqual(compact(manifest), manifest_bytes)
                keys = CONFIG_KEYS + (["componentDigest"] if kind == "capsule" else []) + ["layers", "annotations"]
                self.assertEqual(list(config), keys)
                self.assertEqual(list(manifest), MANIFEST_KEYS + ["annotations"])
                for layer, descriptor in zip(config["layers"], manifest["layers"], strict=True):
                    self.assertEqual(list(layer), ["path", "role", "mediaType", "digest", "size"])
                    self.assertEqual(list(descriptor), ["mediaType", "digest", "size", "annotations"])
                    self.assertEqual(list(descriptor["annotations"]), sorted(descriptor["annotations"]))
                check_graph(manifest_bytes, config_bytes, blobs)

    def test_detached_evidence_schemas_hashes_canonical_bytes_and_subjects(self) -> None:
        for record in self.index["evidence"]:
            with self.subTest(kind=record["kind"]):
                raw = (FIXTURES / record["manifest"]["file"]).read_bytes()
                evidence = json.loads(raw)
                self.schemas["evidence"].validate(evidence)
                self.assertEqual(compact(evidence), raw)
                self.assertEqual(list(evidence), MANIFEST_KEYS + ["subject", "annotations"])
                subject = self.packages[record["subjectKind"]]["manifest"]
                self.assertEqual(evidence["subject"], {"mediaType": OCI, "digest": subject["digest"], "size": subject["size"]})
                check_content(evidence["layers"][0], (FIXTURES / record["payload"]["file"]).read_bytes())
                check_content(evidence["config"], b"{}")
                altered = (FIXTURES / subject["file"]).read_bytes() + b"\n"
                with self.assertRaisesRegex(ValueError, "content size"):
                    check_content(evidence["subject"], altered)

    def test_wit_lock_known_answer(self) -> None:
        config, _, blobs = self.package()
        raw = blobs["wit-lock.json"]
        lock = json.loads(raw)
        self.schemas["wit-lock"].validate(lock)
        self.assertEqual(compact(lock), raw)
        self.assertEqual(list(lock), ["formatVersion", "world", "contractsDigest", "packages"])
        self.assertEqual(list(lock["packages"][0]), ["id", "sourcePath", "digest", "dependencies"])
        check_lock(lock, config, blobs)

    def test_same_size_blob_corruption_and_descriptor_divergence(self) -> None:
        config, manifest, blobs = self.package("browser-assets")
        changed = dict(blobs)
        changed["index.html"] = b"X" + changed["index.html"][1:]
        with self.assertRaisesRegex(ValueError, "content digest"):
            check_graph(compact(manifest), compact(config), changed)
        manifest["layers"][0]["size"] += 1
        with self.assertRaisesRegex(ValueError, "layer descriptor"):
            check_graph(compact(manifest), compact(config), blobs)

    def test_config_changes_require_new_raw_identity(self) -> None:
        config, manifest, blobs = self.package("browser-assets")
        original = compact(config)
        config["version"] = "1.0.1"
        self.assertEqual(len(compact(config)), len(original))
        self.schemas["config"].validate(config)
        with self.assertRaisesRegex(ValueError, "content digest"):
            check_graph(compact(manifest), compact(config), blobs)
        manifest_bytes = compact(manifest)
        pretty = json.dumps(manifest, indent=2).encode()
        self.schemas["manifest"].validate(json.loads(pretty))
        self.assertNotEqual(sha256(manifest_bytes), sha256(pretty))

    def test_schemas_reject_unknown_structural_members_and_null_options(self) -> None:
        config, manifest, blobs = self.package()
        evidence = json.loads((FIXTURES / self.index["evidence"][0]["manifest"]["file"]).read_bytes())
        lock = json.loads(blobs["wit-lock.json"])
        for name, original, routes in [
            ("config", config, [(), ("layers", 0)]),
            ("manifest", manifest, [(), ("config",), ("layers", 0), ("layers", 0, "annotations")]),
            ("evidence", evidence, [(), ("config",), ("layers", 0), ("subject",), ("layers", 0, "annotations")]),
            ("wit-lock", lock, [(), ("packages", 0)]),
        ]:
            for route in routes:
                with self.subTest(schema=name, route=route):
                    value = copy.deepcopy(original)
                    cursor = value
                    for key in route:
                        cursor = cursor[key]
                    cursor["unknown"] = "ignored?"
                    self.assert_schema_invalid(name, value)
        config["componentDigest"] = None
        self.assert_schema_invalid("config", config)
        manifest["config"]["annotations"] = None
        self.assert_schema_invalid("manifest", manifest)

    def test_kind_and_role_media_type_constraints(self) -> None:
        config, manifest, _ = self.package()
        for index, layer in enumerate(config["layers"]):
            if layer["role"] == "asset":
                continue
            with self.subTest(role=layer["role"]):
                changed = copy.deepcopy(config)
                changed["layers"][index]["mediaType"] = "text/plain"
                self.assert_schema_invalid("config", changed)
                changed = copy.deepcopy(manifest)
                changed["layers"][index]["mediaType"] = "text/plain"
                self.assert_schema_invalid("manifest", changed)
        for kind in ("browser-assets", "ssr-package"):
            changed = copy.deepcopy(config)
            changed["kind"] = kind
            self.assert_schema_invalid("config", changed)
        config["layers"].append(copy.deepcopy(next(layer for layer in config["layers"] if layer["role"] == "component")))
        self.assert_schema_invalid("config", config)
        for evidence_record in self.index["evidence"]:
            evidence = json.loads((FIXTURES / evidence_record["manifest"]["file"]).read_bytes())
            evidence["layers"][0]["mediaType"] = "text/plain"
            self.assert_schema_invalid("evidence", evidence)

    def test_invalid_path_digest_version_mime_and_annotation_shapes(self) -> None:
        invalid = {
            "entrypoint": ["/root", "../index.html", "a//b", "a/./b", "a/../b", "a\\b", "a:", "a%2fb", "a?b", "a#b",
                           "a.", "a./b", "CON", "nul.txt", "a/LpT9.txt", "a" * 65, "a\n", "café"],
            "version": ["1.0", "01.0.0", "1.0.0-01", "1.0.0+", "v1.0.0", "1.0.0\n", "1.0.0+" + "a" * 123],
            "name": ["Upper", "bad!name", "-name", "name-", "name\n", "a" * 129],
        }
        for field, values in invalid.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    config, _, _ = self.package("browser-assets")
                    config[field] = value
                    self.assert_schema_invalid("config", config)
        for field, values in {
            "digest": ["sha256:" + "A" * 64, "sha256:" + "a" * 63, "sha512:" + "a" * 64, "sha256:" + "g" * 64],
            "mediaType": ["text/HTML", "text/plain; charset=utf-8", "_text/plain", "text/+plain", "text/plain\n", "text/pl!ain", "a/" + "b" * 127],
            "size": [-1, 67108865, 1.5, "1", True],
        }.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    config, _, _ = self.package("browser-assets")
                    config["layers"][0][field] = value
                    self.assert_schema_invalid("config", config)
        for annotations in [{"": "value"}, {"bad key": "value"}, {"key": "line\n"}, {"key": "\u0080"},
                            {"key": "x" * 4097}, {"x" * 129: "value"}, {str(index): "v" for index in range(33)}]:
            config, _, _ = self.package("browser-assets")
            config["annotations"] = annotations
            self.assert_schema_invalid("config", config)

    def test_schema_array_bounds_without_large_content(self) -> None:
        config, manifest, _ = self.package("browser-assets")
        for count in (0, 257):
            changed = copy.deepcopy(config)
            changed["layers"] = [changed["layers"][0]] * count
            self.assert_schema_invalid("config", changed)
            changed = copy.deepcopy(manifest)
            changed["layers"] = [changed["layers"][0]] * count
            self.assert_schema_invalid("manifest", changed)

    def test_zero_size_is_permitted_only_for_asset_content(self) -> None:
        for kind in self.packages:
            config, manifest, _ = self.package(kind)
            for index, layer in enumerate(config["layers"]):
                with self.subTest(kind=kind, role=layer["role"]):
                    changed_config = copy.deepcopy(config)
                    changed_manifest = copy.deepcopy(manifest)
                    changed_config["layers"][index]["size"] = 0
                    changed_manifest["layers"][index]["size"] = 0
                    if layer["role"] == "asset":
                        self.schemas["config"].validate(changed_config)
                        self.schemas["manifest"].validate(changed_manifest)
                    else:
                        self.assert_schema_invalid("config", changed_config)
                        self.assert_schema_invalid("manifest", changed_manifest)
            manifest["config"]["size"] = 0
            self.assert_schema_invalid("manifest", manifest)
        for record in self.index["evidence"]:
            original = json.loads((FIXTURES / record["manifest"]["file"]).read_bytes())
            for route in (("subject",), ("layers", 0)):
                with self.subTest(evidence=record["kind"], route=route):
                    changed = copy.deepcopy(original)
                    cursor = changed
                    for key in route:
                        cursor = cursor[key]
                    cursor["size"] = 0
                    self.assert_schema_invalid("evidence", changed)

    def test_order_case_prefix_and_entrypoint_are_graph_constraints(self) -> None:
        for paths, error in [(["b", "a"], "path order"), (["a", "a"], "path order"),
                             (["A", "a"], "path case collision"), (["a", "a/b"], "path prefix collision")]:
            with self.subTest(paths=paths), self.assertRaisesRegex(ValueError, error):
                check_paths([{"path": path} for path in paths])
        config, manifest, blobs = self.package("browser-assets")
        config["entrypoint"] = "missing.html"
        self.schemas["config"].validate(config)
        raw = compact(config)
        manifest["config"].update(digest=sha256(raw), size=len(raw))
        with self.assertRaisesRegex(ValueError, "entrypoint"):
            check_graph(compact(manifest), raw, blobs)

    def test_wit_identity_and_dependency_shapes(self) -> None:
        _, _, blobs = self.package()
        original = json.loads(blobs["wit-lock.json"])
        for identity in ["example:fixture", "Example:fixture@1.0.0", "example:fixture_@1.0.0",
                         "example:fixture@01.0.0", "example:fixture@1.0.0-01", "example:fixture@1.0.0\n",
                         "example:fixture@1.0.0+" + "a" * 123, "a" * 129 + ":fixture@1.0.0"]:
            with self.subTest(identity=identity):
                lock = copy.deepcopy(original)
                lock["packages"][0]["id"] = identity
                self.assert_schema_invalid("wit-lock", lock)
        for world in ["example:fixture@1.0.0", "example:fixture/World@1.0.0", "example:fixture/world-@1.0.0"]:
            lock = copy.deepcopy(original)
            lock["world"] = world
            self.assert_schema_invalid("wit-lock", lock)
        lock = copy.deepcopy(original)
        lock["packages"][0]["dependencies"] = ["example:fixture@1.0.0"] * 2
        self.assert_schema_invalid("wit-lock", lock)

    def test_wit_graph_references_cycles_and_layer_associations(self) -> None:
        config, _, blobs = self.package()
        original = json.loads(blobs["wit-lock.json"])
        mutations = [
            ("lock world membership", lambda lock: lock.update(world="example:absent/fixture@1.0.0")),
            ("lock unknown dependency", lambda lock: lock["packages"][0].update(dependencies=["example:absent@1.0.0"])),
            ("lock cycle", lambda lock: lock["packages"][0].update(dependencies=["example:fixture@1.0.0"])),
            ("lock contracts digest", lambda lock: lock.update(contractsDigest=EMPTY_DIGEST)),
            ("lock source digest", lambda lock: lock["packages"][0].update(digest=EMPTY_DIGEST)),
            ("lock source layer", lambda lock: lock["packages"][0].update(sourcePath="component.wasm")),
        ]
        for error, mutate in mutations:
            with self.subTest(error=error):
                lock = copy.deepcopy(original)
                mutate(lock)
                self.schemas["wit-lock"].validate(lock)
                with self.assertRaisesRegex(ValueError, error):
                    check_lock(lock, config, blobs)


if __name__ == "__main__":
    unittest.main()

"""Resource objects must belong to the actual captured application inventory."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import guest_resources as resources
from tools.dev_workflow.common import digest, encode
from tools.rust_capsule_project import inventory


class ApplicationSourceMembership(unittest.TestCase):
    def fixture(self):
        payload = b"\x00captured resource\xff\n"
        files = {resources.MANIFEST: encode({"schemaVersion": resources.PROFILE, "resources": [
            {"path": "app/data.bin", "source": "assets/data.bin", "mediaType": "application/octet-stream"},
            {"path": "app/copy.bin", "source": "assets/data.bin", "mediaType": "application/octet-stream"}]}),
            "assets/data.bin": payload, "unselected.txt": b"not a resource",
            "dependencies/data.bin": payload,
            "latent.dependencies.lock.json": encode({"artifacts": [{"id": "outside:resource:1.0", "files": [
                {"path": "data.bin", "digest": digest(payload), "size": len(payload)}]}]})}
        additional = [{"path": "dependency/data.bin", "source": "dependencies/data.bin",
            "mediaType": "application/octet-stream", "owner": "outside:resource:1.0", "digest": digest(payload)}]
        source = inventory(files)
        return files, source, resources.capture(files, b"component", source, additional_resources=additional)

    def verify(self, packaged, files, raw, expected_source):
        return resources.verify(encode(packaged.index), packaged.objects,
            source_digest=digest(expected_source), source_inventory=raw, component_digest=digest(b"component"),
            manifest_digest=digest(files[resources.MANIFEST]), manifest=files[resources.MANIFEST],
            dependency_lock_digest=digest(files["latent.dependencies.lock.json"]),
            dependency_lock=files["latent.dependencies.lock.json"])

    def rehash(self, index):
        index["identity"] = digest(encode({key: value for key, value in index.items() if key != "identity"}))

    def bind_source(self, packaged, source):
        index = copy.deepcopy(packaged.index)
        index["sourceDigest"] = digest(source)
        self.rehash(index)
        return resources.PackagedResources(index, packaged.objects)

    def test_rehashed_new_payload_cannot_replace_bytes_at_a_declared_source_path(self):
        files, source, packaged = self.fixture()
        payload = b"not observed in the captured application"
        identity = digest(payload)
        object_path = "resources/objects/" + identity[7:]
        changed = copy.deepcopy(packaged.index)
        changed["resources"][0].update(digest=identity, object=object_path, size=len(payload))
        changed["bytes"] += len(payload) - len(files["assets/data.bin"])
        self.rehash(changed)
        with self.assertRaisesRegex(resources.ResourceError, "^resource-source-bytes-not-captured$") as raised:
            self.verify(resources.PackagedResources(changed, {**packaged.objects, object_path: payload}), files, source, source)
        self.assertEqual(raised.exception.category, "denied")

    def test_missing_digest_only_substituted_or_wrong_type_inventory_cannot_be_decoded(self):
        files, source, packaged = self.fixture()
        for raw, code, category in ((None, "resource-index-source-inventory-required", "missing"),
                ("not bytes", "resource-source-inventory-bytes-required", "malformed"),
                (bytearray(source), "resource-source-inventory-bytes-required", "malformed"),
                (encode({}), "resource-index-source-inventory-mismatch", "denied")):
            with self.subTest(code=code), patch.object(resources, "decode", wraps=resources.decode) as decoded, \
                    self.assertRaisesRegex(resources.ResourceError, "^" + code + "$") as raised:
                self.verify(packaged, files, raw, source)
            self.assertEqual(raised.exception.category, category)
            self.assertTrue(all(call.args[0] is not raw for call in decoded.call_args_list))

    def test_inventory_byte_count_and_document_bounds_precede_selected_entry_access(self):
        files, source, packaged = self.fixture()
        with patch.object(resources, "MAX_SOURCE_INVENTORY", len(source) - 1), \
                patch.object(resources, "decode", wraps=resources.decode) as decoded, \
                self.assertRaisesRegex(resources.ResourceError, "^resource-source-inventory-limit$"):
            self.verify(packaged, files, source, source)
        self.assertTrue(all(call.args[0] is not source for call in decoded.call_args_list))
        with patch.object(resources, "MAX_FILES", 1), \
                self.assertRaisesRegex(resources.ResourceError, "^resource-source-count-limit$") as raised:
            self.verify(packaged, files, source, source)
        self.assertEqual(raised.exception.category, "exhausted")
        for raw in (b"[]", b"null", b"{", b"\xff", b'{"same":{},"same":{}}', b'{"bad":NaN}'):
            changed = self.bind_source(packaged, raw)
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                self.verify(changed, files, raw, raw)

    def test_selected_manifest_and_source_entries_require_exact_digest_size_and_path(self):
        files, source, packaged = self.fixture()
        original = json.loads(source)
        for name in (resources.MANIFEST, "assets/data.bin"):
            variants = []
            missing = copy.deepcopy(original); missing.pop(name)
            variants.append((missing, "resource-source-not-captured"))
            alias = copy.deepcopy(original); alias[name.upper()] = alias.pop(name)
            variants.append((alias, "resource-source-not-captured"))
            wrong_digest = copy.deepcopy(original); wrong_digest[name]["digest"] = digest(b"other bytes")
            variants.append((wrong_digest, "resource-source-bytes-not-captured"))
            wrong_size = copy.deepcopy(original); wrong_size[name]["size"] += 1
            variants.append((wrong_size, "resource-source-bytes-not-captured"))
            for metadata, code in variants:
                raw = encode(metadata)
                with self.subTest(name=name, code=code), self.assertRaisesRegex(resources.ResourceError, "^" + code + "$"):
                    self.verify(self.bind_source(packaged, raw), files, raw, raw)

    def test_selected_source_metadata_has_closed_shape_and_nonboolean_integer_size(self):
        files, source, packaged = self.fixture()
        for entry in (None, [], {"digest": digest(b"value")}, {"digest": "not a digest", "size": 1},
                {"digest": digest(b"value"), "size": True}, {"digest": digest(b"value"), "size": -1},
                {"digest": digest(b"value"), "size": 1, "hostFallback": "forbidden"}):
            metadata = json.loads(source)
            metadata["assets/data.bin"] = entry
            raw = encode(metadata)
            with self.subTest(entry=entry), self.assertRaisesRegex(resources.ResourceError, "^resource-source-entry-invalid$"):
                self.verify(self.bind_source(packaged, raw), files, raw, raw)

    def test_exact_shared_binary_bytes_keep_mixed_origin_identity_and_parse_source_once(self):
        files, source, packaged = self.fixture()
        before = copy.deepcopy(files)
        with patch.object(resources, "application_sources", wraps=resources.application_sources) as parsed, \
                patch("pathlib.Path.open", side_effect=AssertionError("verification read a host path")):
            actual = self.verify(packaged, files, source, source)
        self.assertEqual(parsed.call_count, 1)
        self.assertEqual(actual, packaged.index)
        self.assertEqual(list(packaged.objects.values()), [files["assets/data.bin"]])
        self.assertEqual(actual["count"], 3)
        self.assertNotIn(b"not a resource", packaged.objects.values())
        self.assertEqual(files, before)

    def test_normal_assembly_rejects_changed_resource_or_manifest_before_writing_layers(self):
        files, source, _ = self.fixture()
        changed_manifest = encode({"schemaVersion": resources.PROFILE, "resources": [
            {"path": "app/renamed.bin", "source": "assets/data.bin", "mediaType": "application/octet-stream"}]})
        for path, payload in (("assets/data.bin", b"same path changed bytes"), (resources.MANIFEST, changed_manifest)):
            with self.subTest(path=path), tempfile.TemporaryDirectory() as owned:
                output = Path(owned)
                (output / "source-inputs.json").write_bytes(source)
                with self.assertRaisesRegex(resources.ResourceError, "^resource-source-bytes-not-captured$"):
                    resources.assemble(output, {**files, path: payload}, b"component")
                self.assertFalse((output / resources.INDEX).exists())
                self.assertFalse((output / "resources").exists())

    def test_declared_empty_manifest_still_belongs_to_the_captured_source(self):
        files, _, _ = self.fixture()
        files[resources.MANIFEST] = encode({"schemaVersion": resources.PROFILE, "resources": []})
        source = inventory(files)
        packaged = resources.capture(files, b"component", source)
        self.assertEqual(self.verify(packaged, files, source, source), packaged.index)
        with self.assertRaisesRegex(resources.ResourceError, "^resource-index-source-inventory-required$"):
            self.verify(packaged, files, None, source)

    def test_dependency_only_assembly_preserves_opaque_source_and_no_declaration_fast_path(self):
        files, _, _ = self.fixture()
        files.pop(resources.MANIFEST)
        additional = [{"path": "dependency/data.bin", "source": "dependencies/data.bin",
            "mediaType": "application/octet-stream", "owner": "outside:resource:1.0", "digest": digest(files["dependencies/data.bin"])}]
        with tempfile.TemporaryDirectory() as owned, patch.object(resources, "application_sources",
                side_effect=AssertionError("dependency-only source inventory was parsed")):
            output = Path(owned)
            (output / "source-inputs.json").write_bytes(b"opaque dependency-only source")
            self.assertEqual(len(resources.assemble(output, files, b"component", additional_resources=additional)), 2)
            self.assertEqual(resources.assemble(output, {}, b"component"), [])


if __name__ == "__main__":
    unittest.main()

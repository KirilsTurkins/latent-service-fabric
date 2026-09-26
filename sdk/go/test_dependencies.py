from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import dependencies


VERSION = "1.27.1"
CHECKSUM = "h1:" + "A" * 43 + "="


def inputs() -> tuple[list[dict], dict]:
    records = [{"Path": dependencies.MODULE, "Main": True, "GoVersion": VERSION}]
    for path in [*dependencies.TOOL_MODULES.values(), "example.com/transitive"]:
        records.append({"Path": path, "Version": "v1.2.3",
                        "Sum": CHECKSUM, "GoModSum": CHECKSUM})
    manifest = {"Module": {"Path": dependencies.MODULE}, "Go": VERSION,
                "Tool": [{"Path": path} for path in dependencies.TOOL_MODULES],
                "Require": [{"Path": "example.com/transitive", "Version": "v1.2.3"}]}
    return records, manifest


class DependencyLockTests(unittest.TestCase):
    def lock(self, records: list[dict] | None = None, manifest: dict | None = None,
             module_data: bytes = b"module\n", sum_data: bytes = b"sum\n") -> dict:
        defaults, default_manifest = inputs()
        return dependencies.make_lock(records if records is not None else defaults,
                                      manifest if manifest is not None else default_manifest,
                                      VERSION, module_data, sum_data)

    def test_all_selected_modules_and_tools_are_retained(self) -> None:
        document = self.lock()
        self.assertEqual(document["schemaVersion"], 1)
        self.assertEqual(document["goVersion"], VERSION)
        self.assertEqual(document["module"], dependencies.MODULE)
        self.assertEqual(len(document["modules"]), 2)
        self.assertEqual(document["modules"][0]["path"], "example.com/transitive")
        self.assertEqual(set(document), {"schemaVersion", "module", "goVersion",
                                        "manifestSha256", "sumSha256", "modules", "tools"})
        self.assertEqual(len(document["tools"]), 1)
        self.assertTrue(set(dependencies.TOOL_MODULES.values()).issubset(
            {entry["path"] for entry in document["modules"]}))
        self.assertNotIn(dependencies.MODULE, [entry["path"] for entry in document["modules"]])
        self.assertEqual(set(document["modules"][0]), {"path", "version", "sum", "goModSum"})

    def test_normalized_lf_hashes_are_platform_independent(self) -> None:
        document = self.lock(module_data=b"module\r\n", sum_data=b"sum\r\n")
        self.assertEqual(document["manifestSha256"], hashlib.sha256(b"module\n").hexdigest())
        self.assertEqual(document["sumSha256"], hashlib.sha256(b"sum\n").hexdigest())
        self.assertEqual(document, self.lock())
        with self.assertRaises(ValueError):
            self.lock(sum_data=b"sum\r")

    def test_missing_transitive_module_or_changed_checksum_fails_check(self) -> None:
        document = self.lock()
        for field in ("modules", "tools", "goVersion", "manifestSha256", "sumSha256"):
            changed = copy.deepcopy(document)
            if isinstance(changed[field], list):
                changed[field].pop(0)
            else:
                changed[field] += "-changed"
            with self.subTest(field=field), self.assertRaises(ValueError):
                dependencies.check_lock(document, dependencies.serialized(changed))
        changed = copy.deepcopy(document)
        changed["modules"][0]["sum"] = "changed"
        with self.assertRaises(ValueError):
            dependencies.check_lock(document, dependencies.serialized(changed))
        dependencies.check_lock(document, dependencies.serialized(document).replace(b"\n", b"\r\n"))

    def test_replacements_and_unresolved_records_fail_closed(self) -> None:
        for field in ("Replace", "Error"):
            records, manifest = inputs()
            records[-1][field] = {}
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.lock(records, manifest)

    def test_both_canonical_checksums_are_required(self) -> None:
        for field in ("Sum", "GoModSum"):
            for value in (None, "", "h1:invalid", "h1:" + "A" * 42 + "B="):
                records, manifest = inputs()
                records[-1][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                    self.lock(records, manifest)

    def test_exact_main_and_unique_dependency_identity(self) -> None:
        records, manifest = inputs()
        for changed in (records[1:], records + [records[0]], records + [records[-1]]):
            with self.subTest(records=len(changed)), self.assertRaises(ValueError):
                self.lock(changed, manifest)
        records[0]["GoVersion"] = "1.23.2"
        with self.assertRaises(ValueError):
            self.lock(records, manifest)

    def test_direct_module_and_tool_drift_fail_closed(self) -> None:
        for field, value in (("Require", [{"Path": "example.com/missing"}]),
                             ("Tool", []), ("Replace", [{}]), ("Exclude", [{}])):
            records, manifest = inputs()
            manifest[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.lock(records, manifest)

    def test_decode_concatenated_go_json_and_bound_count(self) -> None:
        records, _ = inputs()
        output = "\n".join(json.dumps(record) for record in records) + "\n"
        self.assertEqual(dependencies.decode_records(output), records)
        with self.assertRaises(ValueError):
            dependencies.decode_records("{}\n" * 257)
        with self.assertRaises(ValueError):
            dependencies.decode_records("[]")

    def test_resolution_uses_staging_without_mutating_manifests(self) -> None:
        records, manifest = inputs()
        with tempfile.TemporaryDirectory() as directory:
            sdk = Path(directory)
            (sdk / "go.mod").write_bytes(b"module\r\n")
            (sdk / "go.sum").write_bytes(b"sum\r\n")
            calls = []

            def command(arguments: list[str], working: Path) -> str:
                self.assertNotEqual(working, sdk)
                calls.append(arguments)
                if arguments == ["list", "-m", "-json", "all"]:
                    return "\n".join(json.dumps(record) for record in records)
                if arguments == ["mod", "edit", "-json"]:
                    return json.dumps(manifest)
                return ""

            with mock.patch.object(dependencies, "SDK", sdk), \
                    mock.patch.object(dependencies, "pinned_version", return_value=VERSION), \
                    mock.patch.object(dependencies, "run_go", side_effect=command):
                document = dependencies.resolved_lock()
            self.assertEqual(document, self.lock())
            self.assertEqual(calls, [["mod", "download", "-json", "all"],
                                     ["list", "-m", "-json", "all"],
                                     ["mod", "edit", "-json"]])
            self.assertEqual((sdk / "go.sum").read_bytes(), b"sum\r\n")
            self.assertEqual(list((sdk / "target").iterdir()), [])

    def test_ambient_workspace_and_proxy_overrides_are_not_used(self) -> None:
        with mock.patch.dict(dependencies.os.environ, {"GOWORK": "untrusted", "GOSUMDB": "off",
                                                       "GOTOOLCHAIN": "auto", "GOFLAGS": "-mod=mod"}):
            environment = dependencies.go_environment()
        self.assertEqual(environment["GOTOOLCHAIN"], "local")
        self.assertEqual(environment["GOWORK"], "off")
        self.assertEqual(environment["GOFLAGS"], "-mod=readonly")
        self.assertEqual(environment["GOSUMDB"], "sum.golang.org")
        self.assertEqual(environment["GOPROXY"], "https://proxy.golang.org")


if __name__ == "__main__":
    unittest.main()

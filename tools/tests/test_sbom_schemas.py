"""Closed inventory/CDX wire constraints; synthetic identities confer no trust."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest

from jsonschema import Draft202012Validator

from tools.tests.sbom_schema_support import ROOT, upstream_validator

DIGEST = "sha256:" + "a" * 64
ROLES = ("guest-dependency", "build-dependency", "proc-macro", "build-script",
         "wit-package", "build-tool", "asset", "component", "renderer")


def row(role):
    result = {"kind": role, "name": role, "version": "1.0.0", "origin": "supplied",
              "source": "https://example.org/source", "licenseExpression": "MIT OR Apache-2.0"}
    if role in ROLES[:4]:
        result.update(digest=DIGEST, digestScope="registry-archive-declared",
                      manifestDigest=DIGEST, manifestSize=1)
    else:
        scope = {"wit-package": "wit-source", "build-tool": "tool-executable"}.get(role, "output-bytes")
        result.update(digest=DIGEST, digestScope=scope, size=1)
        if role != "build-tool":
            result["path"] = f"inputs/{role}.bin"
    return result


def inventory():
    return {"formatVersion": 1, "packageKind": "capsule", "packageName": "sample",
            "packageVersion": "1.0.0", "dependencyCompleteness": "observed-units-incomplete",
            "sourceSnapshotDigest": DIGEST, "entries": [row(role) for role in ROLES]}


def prop(name, value):
    return {"name": name, "value": value}


def document():
    components = []
    for index, role in enumerate(ROLES):
        entry = row(role)
        props = [prop("lsf:role", role), prop("lsf:origin", "supplied"),
                 prop("lsf:source-status", "declared"), prop("lsf:license-status", "declared")]
        for wire, field in (("source", "source"), ("digest-scope", "digestScope"), ("size", "size"),
                            ("path", "path"), ("manifest-digest", "manifestDigest"),
                            ("manifest-size", "manifestSize")):
            if field in entry:
                props.append(prop("lsf:" + wire, str(entry[field])))
        components.append({
            "type": "file" if role == "asset" else
                    "application" if role in ("build-tool", "component", "renderer") else "library",
            # Deliberate schema-only identity: Rust must reconstruct/check the
            # actual normalized entry digest before accepting an inspection.
            "bom-ref": "urn:lsf:entry:sha256:" + f"{index:064x}",
            "name": entry["name"], "version": entry["version"],
            "hashes": [{"alg": "SHA-256", "content": "a" * 64}],
            "licenses": [{"expression": entry["licenseExpression"]}], "properties": props,
        })
    return {"bomFormat": "CycloneDX", "specVersion": "1.6", "version": 1,
            "metadata": {"component": {"type": "application", "bom-ref": "urn:lsf:package:input",
                                       "name": "sample", "version": "1.0.0"},
                         "properties": [prop("lsf:profile", "lsf-cyclonedx-embedded-1"),
                                        prop("lsf:subject-kind", "package-content"),
                                        prop("lsf:package-kind", "capsule"),
                                        prop("lsf:dependency-completeness", "observed-units-incomplete"),
                                        prop("lsf:source-snapshot-digest", DIGEST)]},
            "components": components}


def set_prop(component, name, value):
    for item in component["properties"]:
        if item["name"] == name:
            item["value"] = value
            return
    component["properties"].append(prop(name, value))


class SbomSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validators = {}
        for name in ("package-sbom", "package-sbom-inputs"):
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
            Draft202012Validator.check_schema(schema)
            cls.validators[name] = Draft202012Validator(schema)
        cls.upstream = upstream_validator()

    def check(self, name, value, valid=True):
        errors = list(self.validators[name].iter_errors(value))
        if valid:
            self.assertFalse(errors, str(errors[0]) if errors else "")
        else:
            self.assertTrue(errors)

    def test_supported_roles_and_attribution_pass_both_schema_levels(self):
        self.check("package-sbom-inputs", inventory())
        sample = document()
        self.check("package-sbom", sample)
        self.upstream.validate(sample)
        for component in sample["components"]:
            component["properties"].reverse()
            del component["licenses"]
            set_prop(component, "lsf:license-status", "unavailable")
            component["properties"] = [item for item in component["properties"] if item["name"] != "lsf:source"]
            set_prop(component, "lsf:source-status", "unavailable")
        self.check("package-sbom", sample)
        self.upstream.validate(sample)

    def test_real_rust_generated_browser_fixture_passes_offline_upstream(self):
        fixtures = ROOT / "crates/latent-packaging/tests/fixtures/sbom"
        raw = (fixtures / "browser.cdx.json").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         "e7f5b4cdf632c4c664bd718529ab8df636599c7447276ed9b1bd045a8855e2c9")
        self.check("package-sbom-inputs", json.loads((fixtures / "browser-inputs.json").read_bytes()))
        sample = json.loads(raw)
        self.check("package-sbom", sample)
        self.upstream.validate(sample)

    def test_normalized_unknown_missing_and_null_fields_fail(self):
        original = inventory()
        for field in ("formatVersion", "packageKind", "packageName", "packageVersion",
                      "dependencyCompleteness", "entries"):
            changed = copy.deepcopy(original)
            del changed[field]
            self.check("package-sbom-inputs", changed, False)
        for field in row("component"):
            changed = inventory()
            changed["entries"][0] = {**row("component"), field: None}
            self.check("package-sbom-inputs", changed, False)
        for target in ("root", "entry"):
            changed = inventory()
            (changed if target == "root" else changed["entries"][0])["trusted"] = True
            self.check("package-sbom-inputs", changed, False)

    def test_normalized_role_digest_path_and_size_rules(self):
        for role in ROLES:
            for field, value in (("digestScope", "unsupported"), ("digest", DIGEST + "\n"),
                                 ("path", "../escape"), ("path", "package/sbom.cdx.json"),
                                 ("path", "package/build-inputs.json"), ("path", "assets/CON.txt"),
                                 ("size", -1), ("size", 268435457), ("size", True),
                                 ("manifestSize", 0), ("manifestSize", 4194305)):
                sample = inventory()
                sample["entries"] = [{**row(role), field: value}]
                with self.subTest(role=role, field=field, value=value):
                    self.check("package-sbom-inputs", sample, False)
        for missing in ("digest", "digestScope", "size", "path"):
            sample = inventory()
            sample["entries"] = [row("component")]
            del sample["entries"][0][missing]
            self.check("package-sbom-inputs", sample, False)
        sample = inventory()
        sample["entries"] = [{**row("guest-dependency"), "digestScope": "source-manifest"}]
        self.check("package-sbom-inputs", sample)
        del sample["entries"][0]["manifestDigest"]
        self.check("package-sbom-inputs", sample, False)

    def test_portable_sources_and_bounded_printable_strings(self):
        valid = ["https://example.org", "https://example.org/source", "urn:lsf:registry:crates.io",
                 "urn:lsf:workspace:crates/example", "urn:lsf:wit:example:echo@1.0.0"]
        invalid = ["file:///private/path", "https://u:p@example.org/repo", "https://example.org:443/repo",
                   "https://example.org/a?key=x", "https://example.org/a#x", "https://example.org/a%20b",
                   "https://example.org/../a", "https://-bad.org/a", "urn:lsf:workspace:../a",
                   "urn:lsf:unknown:value", "urn:lsf:workspace:/absolute", "urn:lsf:workspace:a//b"]
        for source in valid + invalid:
            sample = inventory()
            sample["entries"][0]["source"] = source
            self.check("package-sbom-inputs", sample, source in valid)
        for field, maximum in (("name", 256), ("version", 128), ("licenseExpression", 1024)):
            for value in ("x" * (maximum + 1), "x\n", "é"):
                sample = inventory()
                sample["entries"][0][field] = value
                self.check("package-sbom-inputs", sample, False)

    def test_cyclonedx_closed_fields_and_unique_properties(self):
        for mutate in (
            lambda d: d.update(serialNumber="urn:uuid:00000000-0000-0000-0000-000000000000"),
            lambda d: d.update(dependencies=[]),
            lambda d: d["metadata"]["component"].update(properties=[]),
            lambda d: d["components"][0].update(purl="pkg:cargo/example@1.0.0"),
            lambda d: d["components"][0]["properties"].append(prop("unknown", "x")),
            lambda d: d["components"][0]["properties"].append(prop("lsf:origin", "package-input")),
            lambda d: d["metadata"]["properties"].append(prop("lsf:package-kind", "capsule")),
        ):
            sample = document()
            mutate(sample)
            self.check("package-sbom", sample, False)
        for name in ("lsf:role", "lsf:origin", "lsf:source-status", "lsf:license-status"):
            sample = document()
            sample["components"][0]["properties"] = [p for p in sample["components"][0]["properties"]
                                                       if p["name"] != name]
            self.check("package-sbom", sample, False)

    def test_cyclonedx_role_attribution_and_hash_combinations(self):
        for mutate in (
            lambda c: c.update(type="file"),
            lambda c: c["hashes"][0].update(alg="SHA-512"),
            lambda c: c["hashes"][0].update(content="a" * 32),
            lambda c: c["licenses"][0].update(acknowledgement="declared"),
            lambda c: c.update(licenses=[{"license": {"name": "Custom"}}]),
            lambda c: c.update(licenses=[]),
            lambda c: set_prop(c, "lsf:source-status", "unavailable"),
            lambda c: set_prop(c, "lsf:license-status", "unavailable"),
            lambda c: set_prop(c, "lsf:digest-scope", "output-bytes"),
            lambda c: set_prop(c, "lsf:size", "1"),
        ):
            sample = document()
            mutate(sample["components"][0])
            self.check("package-sbom", sample, False)

    def test_cyclonedx_decimal_strings_are_canonical_and_bounded(self):
        for field, index, maximum, minimum in (("lsf:size", 6, 268435456, 0),
                                               ("lsf:manifest-size", 0, 4194304, 1)):
            for value in (str(minimum), str(maximum), str(maximum - 1)):
                sample = document()
                set_prop(sample["components"][index], field, value)
                self.check("package-sbom", sample)
            for value in (str(maximum + 1), "01", "+1", "1.0", "1e0", " 1", "1\n", "-1"):
                sample = document()
                set_prop(sample["components"][index], field, value)
                self.check("package-sbom", sample, False)


if __name__ == "__main__":
    unittest.main()

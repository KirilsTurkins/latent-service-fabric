"""Closed build-provenance shapes; synthetic samples carry no signing authority."""
from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64
BUILD_TYPE = "https://latent.dev/build/echo-capsule/v1"
REPOSITORY = "https://github.com/KirilsTurkins/latent-service-fabric"
MATERIALS = ("source-snapshot", "dependency-lock", "build-recipe", "toolchain-config",
             "cargo", "rustc", "wasm-tools")


def samples():
    observation = {
        "formatVersion": 1, "buildType": BUILD_TYPE,
        "source": {"repository": REPOSITORY, "revision": "b" * 40,
                   "snapshotDigest": DIGEST, "repositoryTrust": "operator-asserted",
                   "capture": "git-archive-allowlist"},
        "componentDigest": DIGEST, "componentSize": 8,
        "materials": [{"name": name, "digest": DIGEST, "size": 1} for name in MATERIALS],
        "parameters": {"cargoPackage": "latent-toolchain-smoke", "cargoExample": "echo-capsule",
                       "target": "wasm32-unknown-unknown", "profile": "release",
                       "locked": True, "incremental": False},
        "startedAt": 1000, "finishedAt": 1010, "reproducibility": "not-checked",
        "hermetic": False, "dependencyCompleteness": "lockfile-only",
    }
    statement = {
        "_type": "https://in-toto.io/Statement/v1",
        "subject": [{"name": "lsf-package", "digest": {"sha256": "a" * 64}}],
        "predicateType": "https://latent.dev/provenance/v1",
        "predicate": {"formatVersion": 1, "builderId": "test:builder",
                      "packageSubject": {"mediaType": "application/vnd.oci.image.manifest.v1+json",
                                         "digest": DIGEST, "size": 100},
                      "issuedAt": 1010, "expiresAt": 1100, "observation": observation},
    }
    envelope = {
        "payloadType": "application/vnd.in-toto+json",
        "payload": base64.b64encode(json.dumps(statement).encode()).decode(),
        # Shape only: these bytes deliberately are not an authenticated signature.
        "signatures": [{"keyid": DIGEST, "sig": base64.b64encode(bytes(64)).decode()}],
    }
    policy = {
        "formatVersion": 1, "scope": "test:builds", "generation": 1,
        "validFrom": 1000, "validUntil": 2000, "maxSignatureLifetimeSeconds": 1000,
        "maxProofAgeSeconds": 60,
        "keys": [{"builderId": "test:builder", "validFrom": 1000, "validUntil": 2000,
                  "publicKey": (ROOT / "crates/latent-signing/tests/fixtures/openssl-public-key.txt")
                  .read_text().strip()}],
        "requirements": [{"builderId": "test:builder", "buildType": BUILD_TYPE,
                          "sourceRepository": REPOSITORY, "requireReproducible": False}],
    }
    revocations = {
        "formatVersion": 1, "scope": "test:builds", "generation": 1,
        "policyDigest": DIGEST, "validFrom": 1000, "validUntil": 2000,
        "revokedKeys": [], "revokedBuilders": [],
    }
    return {"build-observation": observation, "package-provenance-statement": statement,
            "package-provenance": envelope, "builder-policy": policy,
            "builder-revocations": revocations}


class BuildProvenanceSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validators = {}
        for name in samples():
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
            Draft202012Validator.check_schema(schema)
            cls.validators[name] = Draft202012Validator(schema)

    def invalid(self, name, value):
        self.assertFalse(self.validators[name].is_valid(value), name)

    def test_all_closed_fields_required_recursively(self):
        def objects(value, path=()):
            if isinstance(value, dict):
                yield path, value
                for key, child in value.items():
                    yield from objects(child, (*path, key))
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    yield from objects(child, (*path, index))

        for name, original in samples().items():
            self.validators[name].validate(original)
            for path, original_object in objects(original):
                for field in [*original_object, "unrecognized"]:
                    changed = copy.deepcopy(original)
                    current = changed
                    for part in path:
                        current = current[part]
                    if field == "unrecognized":
                        current[field] = True
                    else:
                        del current[field]
                    with self.subTest(schema=name, path=path, field=field):
                        self.invalid(name, changed)

    def test_repository_grammar_matches_observation_and_policy(self):
        invalid = ["http://example.org/repo", "https://example.org", "https://example.org/",
                   "https://u:p@example.org/repo", "https://example.org:443/repo",
                   "https://example.org/a?x=1", "https://example.org/a#x", "https://example.org/a%20b",
                   "https://example.org/a//b", "https://example.org/../b", "https://example.org/a/.",
                   "https://-bad.org/repo", "https://bad-.org/repo", "https://a..b/repo",
                   "https://" + "a" * 64 + "/repo", "https://" + ".".join(["a" * 63] * 4) + "/r",
                   "https://example.org/" + "a" * 493, "https://example.org/repo\n"]
        for repository in invalid:
            current = samples()
            current["build-observation"]["source"]["repository"] = repository
            current["builder-policy"]["requirements"][0]["sourceRepository"] = repository
            for name in ("build-observation", "builder-policy"):
                with self.subTest(repository=repository[:80], schema=name):
                    self.invalid(name, current[name])
        for repository in (REPOSITORY, "https://a/r", "https://example.org/a/..x/repo.git",
                           "https://example.org/" + "a" * (512 - len("https://example.org/"))):
            value = samples()["build-observation"]
            value["source"]["repository"] = repository
            self.validators["build-observation"].validate(value)

    def test_observation_profile_and_material_constraints(self):
        original = samples()["build-observation"]
        for field, value in (("hermetic", True), ("hermetic", 0),
                             ("dependencyCompleteness", "complete"), ("reproducibility", "claimed"),
                             ("componentSize", 0), ("componentSize", 67108865),
                             ("startedAt", -1), ("finishedAt", 2**64), ("startedAt", True)):
            self.invalid("build-observation", {**original, field: value})
        for field, value in (("locked", False), ("incremental", True),
                             ("target", "native"), ("cargoExample", "other")):
            changed = copy.deepcopy(original)
            changed["parameters"][field] = value
            self.invalid("build-observation", changed)
        for index in range(len(MATERIALS)):
            changed = copy.deepcopy(original)
            del changed["materials"][index]
            self.invalid("build-observation", changed)
        for field, value in (("name", "../source"), ("name", ".hidden"),
                             ("name", "n" * 129), ("digest", DIGEST + "\n"),
                             ("size", 0), ("size", 268435457)):
            changed = copy.deepcopy(original)
            changed["materials"][0][field] = value
            self.invalid("build-observation", changed)
        changed = copy.deepcopy(original)
        changed["materials"].append({**changed["materials"][0], "size": 2})
        self.invalid("build-observation", changed)  # Required names occur exactly once.
        for count in (64, 65):
            changed = copy.deepcopy(original)
            changed["materials"] += [{"name": f"extra-{index}", "digest": DIGEST, "size": 1}
                                     for index in range(count - len(MATERIALS))]
            self.assertEqual(self.validators["build-observation"].is_valid(changed), count == 64)

    def test_statement_subject_and_signed_shape(self):
        original = samples()["package-provenance-statement"]
        for subjects in ([], original["subject"] * 2):
            self.invalid("package-provenance-statement", {**original, "subject": subjects})
        for key, value in (("builderId", "unbounded space"), ("issuedAt", -1), ("expiresAt", 2**64)):
            changed = copy.deepcopy(original)
            changed["predicate"][key] = value
            self.invalid("package-provenance-statement", changed)
        for size in (0, 262145):
            changed = copy.deepcopy(original)
            changed["predicate"]["packageSubject"]["size"] = size
            self.invalid("package-provenance-statement", changed)
        changed = copy.deepcopy(original)
        changed["predicate"]["observation"]["hermetic"] = True
        self.invalid("package-provenance-statement", changed)

    def test_envelope_canonical_base64_and_exact_decoded_ceiling(self):
        original = samples()["package-provenance"]
        for size in (32767, 32768, 32769):
            encoded = base64.b64encode(bytes(size)).decode()
            self.assertEqual(self.validators["package-provenance"].is_valid(
                {**original, "payload": encoded}), size <= 32768)
        for payload in ("", "AA-A", "AB==", "AAB=", "AA==\n"):
            self.invalid("package-provenance", {**original, "payload": payload})
        for signatures in ([], original["signatures"] * 2):
            self.invalid("package-provenance", {**original, "signatures": signatures})
        changed = copy.deepcopy(original)
        changed["signatures"][0]["sig"] = "A" * 85 + "B=="
        self.invalid("package-provenance", changed)

    def test_explicit_builder_requirements_and_revocations(self):
        policy = samples()["builder-policy"]
        self.validators["builder-policy"].validate({**policy, "keys": [], "requirements": []})
        for field, value in (("sourceRevision", "b" * 40), ("sourceRevision", "b" * 64),
                             ("sourceSnapshotDigest", DIGEST)):
            changed = copy.deepcopy(policy)
            changed["requirements"][0][field] = value
            self.validators["builder-policy"].validate(changed)
            for invalid in (None, "", value + "\n"):
                changed["requirements"][0][field] = invalid
                self.invalid("builder-policy", changed)
        changed = copy.deepcopy(policy)
        changed["requirements"] *= 2
        self.invalid("builder-policy", changed)
        for count in (256, 257):
            self.assertEqual(self.validators["builder-policy"].is_valid(
                {**policy, "keys": policy["keys"] * count}), count == 256)
        for field, value in (("revokedKeys", DIGEST), ("revokedBuilders", "builder:test")):
            changed = samples()["builder-revocations"]
            changed[field] = [value, value]
            self.invalid("builder-revocations", changed)
        for field in ("generation", "validFrom", "validUntil"):
            for value in (-1, True, 2**64):
                self.invalid("builder-policy", {**policy, field: value})


if __name__ == "__main__":
    unittest.main()

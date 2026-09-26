"""Closed web metadata and evidence shapes; synthetic fixtures confer no trust."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
DIGEST = "sha256:" + "a" * 64
BUILD_TYPE = "https://latent.dev/build/web-package-assembly/v1"


def application():
    return {"formatVersion": 1, "profile": "lsf.web-release.v1", "assetsDigest": DIGEST,
            "assets": [{"path": "/index.html", "layer": "public/index.html", "digest": DIGEST,
                        "size": 42, "mediaType": "text/html"}],
            "routes": [{"path": "/", "mode": "client", "asset": "/index.html"}]}


def observation():
    return {"formatVersion": 1, "buildType": BUILD_TYPE,
            "source": {"repository": "https://example.com/source", "revision": "a" * 64,
                       "snapshotDigest": DIGEST, "repositoryTrust": "operator-asserted",
                       "capture": "explicit-input-files"},
            "outputsDigest": DIGEST, "outputsCount": 2, "outputsBytes": 100,
            "materials": [{"name": name, "digest": DIGEST, "size": 1}
                          for name in ("source-snapshot", "build-recipe", "toolchain-config", "package-assembler")],
            "parameters": {"assembler": "lsf-web-package-assembly", "recipeVersion": 1,
                           "inputMode": "explicit-supplied-files"},
            "startedAt": 900, "finishedAt": 1000, "reproducibility": "not-checked",
            "hermetic": False, "dependencyCompleteness": "declared-inputs-incomplete"}


def statement():
    return {"_type": "https://in-toto.io/Statement/v1",
            "subject": [{"name": "lsf-package", "digest": {"sha256": "a" * 64}}],
            "predicateType": "https://latent.dev/web-provenance/v1",
            "predicate": {"formatVersion": 1,
                          "packageSubject": {"mediaType": "application/vnd.oci.image.manifest.v1+json",
                                             "digest": DIGEST, "size": 512},
                          "builderId": "test:builder", "issuedAt": 1000, "expiresAt": 2000,
                          "observation": observation()}}


def receipt():
    generation = {"generation": 1, "digest": DIGEST}
    policy = {"generation": 1, "scope": "test", "validFrom": 1, "validUntil": 2000,
              "tenantsDigest": DIGEST, "publisher": generation,
              "publisherRevocations": generation, "builder": generation,
              "builderRevocations": generation, "sbomDigest": DIGEST}
    return {"formatVersion": 1, "profile": "lsf.web-admission.v1", "tenant": "acme",
            "package": DIGEST, "manifest": DIGEST, "assets": DIGEST,
            "publisher": "test:publisher", "publisherKey": DIGEST,
            "signatureManifest": DIGEST, "signaturePayload": DIGEST,
            "builder": "test:builder", "builderKey": DIGEST,
            "provenanceManifest": DIGEST, "provenancePayload": DIGEST,
            "sbomInventory": None, "sbomReferrer": None, "policy": policy,
            "policyDigest": DIGEST, "epoch": 1, "verifiedAt": 1000, "validUntil": 1100}


class WebAdmissionSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schemas = {}
        for name in ("web-application", "web-build-observation", "web-provenance-statement",
                     "web-admission-receipt", "package-provenance-statement", "package-admission-receipt",
                     "builder-policy"):
            schema = json.loads((ROOT / f"schemas/{name}.schema.json").read_bytes())
            Draft202012Validator.check_schema(schema)
            schemas[name] = schema
        registry = Registry().with_resources(
            (schema["$id"], Resource.from_contents(schema)) for schema in schemas.values())
        cls.schemas = schemas
        cls.validators = {name: Draft202012Validator(schema, registry=registry)
                          for name, schema in schemas.items()}

    def test_componentless_profiles_are_closed_and_keep_required_identities(self):
        for name, sample in (("web-application", application()), ("web-build-observation", observation()),
                             ("web-provenance-statement", statement()), ("web-admission-receipt", receipt())):
            validator = self.validators[name]
            validator.validate(sample)
            for key in self.schemas[name]["required"]:
                changed = copy.deepcopy(sample)
                del changed[key]
                self.assertFalse(validator.is_valid(changed), (name, key))
            for key in ("admitted", "trusted", "release", "componentDigest"):
                changed = copy.deepcopy(sample)
                changed[key] = DIGEST
                self.assertFalse(validator.is_valid(changed), (name, key))

    def test_private_asset_locations_unknown_profiles_and_unbounded_arrays_are_rejected(self):
        validator = self.validators["web-application"]
        for path in ("metadata/private.json", "server/renderer.wasm", "package/sbom.cdx.json"):
            value = application()
            value["assets"][0]["layer"] = path
            self.assertFalse(validator.is_valid(value), path)
        for field, invalid in (("profile", "lsf.web-release.v2"), ("renderer", None),
                               ("assets", application()["assets"] * 129),
                               ("routes", application()["routes"] * 129)):
            value = application()
            value[field] = invalid
            self.assertFalse(validator.is_valid(value), field)
        value = application()
        value["assets"][0]["size"] = 8 * 1024 * 1024 + 1
        self.assertFalse(validator.is_valid(value))

    def test_web_build_type_does_not_claim_compiler_or_hermetic_observation(self):
        validator = self.validators["web-build-observation"]
        for field, invalid in (("buildType", "https://latent.dev/build/echo-capsule/v1"),
                               ("hermetic", True), ("dependencyCompleteness", "complete"),
                               ("outputsCount", 0), ("outputsBytes", 0)):
            value = observation()
            value[field] = invalid
            self.assertFalse(validator.is_valid(value), field)
        value = observation()
        value["parameters"]["assembler"] = "angular-compiler"
        self.assertFalse(validator.is_valid(value))
        value = observation()
        value["materials"][-1]["name"] = "something-else"
        self.assertFalse(validator.is_valid(value))
        # Approval of this build type remains explicit in the same builder policy.
        requirements = self.schemas["builder-policy"]["properties"]["requirements"]["items"]
        self.assertIn(BUILD_TYPE, requirements["properties"]["buildType"]["enum"])

    def test_legacy_capsule_statement_and_receipt_do_not_silently_become_web(self):
        self.assertFalse(self.validators["package-provenance-statement"].is_valid(statement()))
        self.assertFalse(self.validators["package-admission-receipt"].is_valid(receipt()))
        value = statement()
        value["predicateType"] = "https://latent.dev/provenance/v1"
        self.assertFalse(self.validators["web-provenance-statement"].is_valid(value))
        value = receipt()
        value["epoch"] = 0
        self.assertFalse(self.validators["web-admission-receipt"].is_valid(value))

    def test_angular_observation_is_a_separate_closed_recipe_with_actual_output_materials(self):
        validator = self.validators['web-build-observation']
        value = observation()
        value['buildType'] = 'https://latent.dev/build/angular-component/v1'
        self.assertFalse(validator.is_valid(value))
        value['parameters'] = {'compiler': 'lsf-angular-component', 'recipeVersion': 1,
            'rendererProfile': 'angular-ssr-component-v1', 'profileDigest': DIGEST,
            'rendererDigest': DIGEST, 'rendererSize': 100, 'maxHydrationBytes': 32768,
            'lifecycleScripts': False}
        for name in ('node', 'cargo', 'rustc', 'wasm-tools', 'dependency-lock', 'npm-lock', 'npm-tree',
                     'javascript-embedding', 'async-adapter', 'adapter-source', 'public-wit', 'private-wit',
                     'renderer-component', 'angular-server-bundle', 'angular-client-bundle'):
            value['materials'].append({'name': name, 'digest': DIGEST, 'size': 1})
        validator.validate(value)
        for field in (*value['parameters'], 'extra'):
            changed = copy.deepcopy(value)
            if field == 'extra': changed['parameters'][field] = True
            else: del changed['parameters'][field]
            self.assertFalse(validator.is_valid(changed), field)
        for material in value['materials']:
            changed = copy.deepcopy(value)
            changed['materials'] = [item for item in changed['materials'] if item['name'] != material['name']]
            self.assertFalse(validator.is_valid(changed), material['name'])
        value['buildType'] = BUILD_TYPE
        self.assertFalse(validator.is_valid(value))


if __name__ == "__main__":
    unittest.main()

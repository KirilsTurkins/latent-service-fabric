"""Closed public selectors/reports must not misrepresent enforced controls."""
import json
from pathlib import Path
import unittest

import jsonschema

ROOT = Path(__file__).resolve().parents[2]


def validator(name):
    schema = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def report():
    return {"schemaVersion": "latent.standalone.config-check.v1", "profile": "external-capsule-v1",
            "threatClass": "T1", "guestBoundary": "in-process-wasmtime", "admission": "enforced",
            "protectedCredentialFile": True, "hostAbiProfile": "lsf-host-abi-phase3-v3",
            "wasmtimeVersion": "47.0.4", "target": "x86_64-unknown-linux-gnu",
            "compiler": "isolated-aot-compiler-v1", "compilerSandbox": "lsf-linux-x86_64-landlock3-seccomp-v1",
            "authenticatedNativeLoading": True}


class SecurityProfileSchema(unittest.TestCase):
    def test_selector_is_exact_and_not_a_claim_of_runtime_enforcement(self):
        schema = validator("node-security-profile.schema.json")
        for value in ("local-experimental-v1", "external-capsule-v1"):
            self.assertTrue(schema.is_valid(value))
        for value in (None, {}, True, "", "external-capsule-v1\n", "external-capsule-v2",
                      "fixed-execution-host-v1", "isolated-aot-compiler-v1"):
            self.assertFalse(schema.is_valid(value))

    def test_external_report_requires_every_observed_control(self):
        schema = validator("node-config-check.schema.json")
        self.assertTrue(schema.is_valid(report()))
        for key in report():
            incomplete = report()
            del incomplete[key]
            self.assertFalse(schema.is_valid(incomplete), key)
        for key, value in (("threatClass", "T0"), ("admission", "trusted-local"),
                           ("protectedCredentialFile", False), ("compiler", "in-process"),
                           ("compilerSandbox", None), ("authenticatedNativeLoading", False),
                           ("wasmtimeVersion", "47.0.3"), ("guestBoundary", "fixed-host"),
                           ("hostAbiProfile", "lsf-host-abi-phase3-v1"), ("token", "secret")):
            self.assertFalse(schema.is_valid(dict(report(), **{key: value})), key)

    def test_local_observations_preserve_independent_admission_and_compiler_settings(self):
        schema = validator("node-config-check.schema.json")
        local = dict(report(), profile="local-experimental-v1", threatClass="T0")
        self.assertTrue(schema.is_valid(local))
        local.update(admission="trusted-local", compiler="in-process", compilerSandbox=None,
                     authenticatedNativeLoading=False)
        self.assertTrue(schema.is_valid(local))
        self.assertFalse(schema.is_valid(dict(local, compilerSandbox="lsf-linux-x86_64-landlock3-seccomp-v1")))
        self.assertFalse(schema.is_valid(dict(local, threatClass="T2")))


if __name__ == "__main__":
    unittest.main()

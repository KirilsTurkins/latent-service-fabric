"""Authoring capture contracts; compiler and signed-node evidence are separate."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from tools.rust_capsule_project import AUTHORING_TEMPLATES, TEMPLATES, ROOT, snapshot
from tools.transaction_guest_project import TEMPLATE, package_companion


class TransactionGuestAuthoringTests(unittest.TestCase):
    def test_java_transaction_capture_closes_its_declared_runtime_clock_dependencies(self):
        from tools.java_capsule_project import create, validate
        from tools.stage_runtime_wit import REFERENCE
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / "source", TEMPLATE, "transaction-java-clock-closure")
            files = snapshot(project)
            validate(files)
            self.assertIn("latent:clock/monotonic@0.1.0", files["wit/world.wit"].decode())
            self.assertIn("latent:clock/wall@0.1.0", files["wit/world.wit"].decode())
            self.assertEqual(files["wit/deps/clock/package.wit"], files["vendor/lsf/wit/platform/clock/package.wit"])
            imported = {match.group(1) + "@" + match.group(2) for match in REFERENCE.finditer(files["wit/world.wit"].decode())}
            declared = {raw.decode().split(";", 1)[0].removeprefix("package ").strip()
                        for name, raw in files.items() if name.startswith("wit/deps/") and name.endswith("package.wit")}
            self.assertTrue(imported <= declared)

    def test_six_forbidden_http_variants_keep_profile_companion_and_sdk_capture(self):
        from tools.transaction_guest_variants import create, HTTP, LANGUAGES, SOURCES, URL
        from tools.rust_capsule_build import validate_project as rust
        from tools.c_capsule_project import validate as c
        from tools.typescript_guest.project import validate as typescript
        from tools.go_capsule_project import validate as go
        from tools.java_capsule_project import validate as java
        from tools.dotnet_guest.project import validate as dotnet
        validators = dict(zip(LANGUAGES, (rust, c, typescript, go, java, dotnet), strict=True))
        calls = ("latent_guest::http::send(", "latent_http_client_send(", "host(send(",
                 "http.Send(", "Bindings.LatentHttpClient.send(", "Http.Send(")
        with tempfile.TemporaryDirectory() as temporary:
            for language, call in zip(LANGUAGES, calls, strict=True):
                with self.subTest(language=language):
                    source = create(Path(temporary) / language, language, "forbidden-http")
                    files = snapshot(source)
                    validators[language](files)
                    project = json.loads(files["capsule-project.json"])
                    companion = json.loads(files["transaction-binding.json"])
                    # No broader profile, provider grant or compensating HTTP budget.
                    self.assertEqual(project["limits"]["outboundRequests"], 0)
                    self.assertEqual(companion["profile"], "lsf-transaction-v1")
                    self.assertEqual([item["operation"] for item in companion["operations"]], ["update", "query", "scan"])
                    self.assertEqual(companion["capsule"], project["service"])
                    self.assertEqual(files["wit/deps/http-v2/package.wit"],
                                     files["vendor/lsf/wit/platform/http-v2/package.wit"])
                    from tools.stage_runtime_wit import copy_wit_tree, dependencies, PACKAGE, source_text
                    staged = Path(temporary) / (language + "-compiler-wit")
                    copy_wit_tree(source / "wit", staged)
                    for package in dependencies(source / "wit", source / "vendor/lsf/wit/platform"):
                        copy_wit_tree(package, staged / "deps" / package.name)
                    self.assertEqual(PACKAGE.findall(source_text(staged)).count("latent:http@0.2.0"), 1)
                    self.assertEqual(files["wit/world.wit"].decode().count("import " + HTTP + ";"), 1)
                    code = files[SOURCES[language]].decode()
                    self.assertIn(call, code)
                    self.assertIn(URL, code)
                    if language == "c":
                        self.assertIn("frame->http_returned = state == LSF_ASYNC_RETURNED || state == LSF_ASYNC_CANCELLED_RETURNED", code)
                        self.assertIn("else if (frame->phase != FORBIDDEN_HTTP) lsf_state_call_retire", code)
                        self.assertIn("if (frame->http_returned && !frame->http_result.is_err)", code)

    def test_controlled_variant_rejects_unknown_inputs_and_source_drift(self):
        from tools.transaction_guest_variants import create, forbidden_http, replace_once
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "source"
            for language, variant in (("future", "forbidden-http"), ("rust", "grant-http")):
                with self.subTest(language=language, variant=variant), self.assertRaises(ValueError):
                    create(target, language, variant)
                self.assertFalse(target.exists())
        for source in ("missing", "anchor anchor"):
            with self.assertRaises(ValueError):
                replace_once(source, "anchor", "replacement")
        with self.assertRaises(ValueError):
            forbidden_http("unknown", "future")

    def test_six_creators_capture_one_exact_profile_and_linked_companion(self):
        from tools.rust_capsule_project import create as rust
        from tools.c_capsule_project import create as c
        from tools.typescript_guest.project import create as typescript
        from tools.go_capsule_project import create as go
        from tools.java_capsule_project import create as java
        from tools.dotnet_guest.project import create as dotnet
        self.assertNotIn(TEMPLATE, TEMPLATES)
        self.assertIn(TEMPLATE, AUTHORING_TEMPLATES)
        with tempfile.TemporaryDirectory() as temporary:
            for language, create in (("rust", rust), ("c", c), ("typescript", typescript),
                                     ("go", go), ("java", java), ("dotnet", dotnet)):
                with self.subTest(language=language):
                    project_path = create(Path(temporary) / language, TEMPLATE, "synthetic-aggregate")
                    files = snapshot(project_path)
                    project = json.loads(files["capsule-project.json"])
                    declaration = json.loads(files["transaction-binding.json"])
                    # Captured application budgets must permit the shared guest
                    # operation without installing application effect authority.
                    self.assertGreaterEqual(project["limits"]["stateReadBytes"], 2 * 1024 * 1024)
                    self.assertGreaterEqual(project["limits"]["stateWriteBytes"], 1024 * 1024)
                    self.assertGreater(project["limits"]["effectCount"], 0)
                    self.assertLessEqual(project["limits"]["effectCount"], 32)
                    self.assertEqual(project["limits"]["outboundRequests"], 0)
                    self.assertEqual(declaration["capsule"], project["service"])
                    self.assertEqual(declaration["deployment"], project["name"])
                    self.assertEqual(declaration["binding"], project["name"])
                    self.assertEqual(declaration["namespace"], TEMPLATE)
                    self.assertEqual(declaration["hostAbiDigest"], json.loads(files["transaction-profile.json"])["hostAbiDigest"])
                    self.assertEqual([(value["operation"], value["mode"]) for value in declaration["operations"]],
                        [("update", "strict-command"), ("query", "fresh-query"), ("scan", "fresh-query")])
                    for package in ("state", "intents"):
                        self.assertEqual(files["wit/deps/" + package + "/package.wit"],
                            (ROOT / "wit/platform" / package / "package.wit").read_bytes())
                    output = Path(temporary) / (language + "-package")
                    output.mkdir()
                    layer = package_companion(output, project, files)
                    self.assertEqual(layer[0], "transaction-binding.json")
                    self.assertEqual((output / layer[0]).read_bytes(), files["transaction-binding.json"])

    def test_packaging_rejects_mismatched_duplicate_and_unbounded_companions(self):
        from tools.rust_capsule_project import create
        with tempfile.TemporaryDirectory() as temporary:
            source = create(Path(temporary) / "source", TEMPLATE)
            files = snapshot(source)
            project = json.loads(files["capsule-project.json"])
            declaration = json.loads(files["transaction-binding.json"])
            for field in ("capsule", "deployment", "profile", "kind"):
                changed = {**declaration, field: "other"}
                invalid = {**files, "transaction-binding.json": json.dumps(changed).encode()}
                with self.subTest(field=field), self.assertRaises(ValueError):
                    package_companion(Path(temporary), project, invalid)
            for raw in (b'{"kind":"TransactionBinding","kind":"TransactionBinding"}', b" " * 131073):
                with self.assertRaises(ValueError):
                    package_companion(Path(temporary), project, {**files, "transaction-binding.json": raw})
            self.assertIsNone(package_companion(Path(temporary), project, {}))

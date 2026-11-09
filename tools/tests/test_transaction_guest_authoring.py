"""Authoring capture contracts; compiler and signed-node evidence are separate."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from tools.rust_capsule_project import AUTHORING_TEMPLATES, TEMPLATES, ROOT, snapshot
from tools.transaction_guest_project import TEMPLATE, package_companion


class TransactionGuestAuthoringTests(unittest.TestCase):
    def test_typescript_event_profile_is_explicit_and_companion_linked(self):
        from tools.compile_transaction_guests import authored_project, compile_guests
        from tools.typescript_capsule import main as ts_main
        from tools.typescript_guest.project import create, validate
        from tools.transaction_guest_project import (TYPESCRIPT_EVENT_PROFILE, GO_EVENT_PROFILE,
                                                       EVENT_REQUIREMENTS, package_effect_requirements)
        profile = 'js-window-v1:' + 'd' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(ts_main(['new', str(root / 'source'), '--template', TEMPLATE,
                                      '--name', 'transaction-typescript-aggregate', '--event-profile', profile]), 0)
            files = snapshot(root / 'source')
            project, _, _ = validate(files)
            selected = authored_project('typescript', 'aggregate', root / 'selected', typescript_current_event_profile=profile)
            self.assertEqual(snapshot(selected)[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            self.assertEqual(json.loads(files[TYPESCRIPT_EVENT_PROFILE])['idempotencyProfile'], profile)
            output = root / 'package'
            output.mkdir()
            self.assertEqual(package_effect_requirements(output, project, files)[0], EVENT_REQUIREMENTS)
            bad = dict(files)
            changed = json.loads(bad[EVENT_REQUIREMENTS])
            changed['binding'] = 'other-event'
            bad[EVENT_REQUIREMENTS] = json.dumps(changed).encode()
            with self.assertRaisesRegex(ValueError, 'requirements-drift'):
                package_effect_requirements(root, project, bad)
            with self.assertRaisesRegex(ValueError, 'closed-current-event-inputs-required'):
                package_effect_requirements(root, project, {**files, GO_EVENT_PROFILE: files[TYPESCRIPT_EVENT_PROFILE]})
            with self.assertRaisesRegex(ValueError, 'event profile'):
                create(root / 'invalid', 'greeting', event_profile=profile)
            with self.assertRaisesRegex(ValueError, 'event profile'):
                create(root / 'invalid-profile', TEMPLATE, event_profile='invalid')
            with self.assertRaisesRegex(ValueError, 'exclusive TypeScript aggregate'):
                authored_project('go', 'aggregate', root / 'foreign', typescript_current_event_profile=profile)
            with self.assertRaisesRegex(ValueError, 'exclusive explicit'):
                compile_guests('typescript', root / 'foreign-output', typescript_current_event_profile=profile,
                               go_current_event_profile=profile)
            self.assertFalse((root / 'foreign-output').exists())

    def test_go_event_profile_is_explicit_and_companion_linked(self):
        from tools.compile_transaction_guests import authored_project, compile_guests
        from tools.go_capsule import main as go_main
        from tools.go_capsule_project import create, validate
        from tools.transaction_guest_project import (GO_EVENT_PROFILE, C_EVENT_PROFILE,
                                                       EVENT_REQUIREMENTS, package_effect_requirements)
        profile = 'js-window-v1:' + 'c' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(go_main(['new', str(root / 'source'), '--template', TEMPLATE,
                                      '--name', 'transaction-go-aggregate', '--event-profile', profile]), 0)
            files = snapshot(root / 'source')
            project, _, _ = validate(files)
            selected = authored_project('go', 'aggregate', root / 'selected', go_current_event_profile=profile)
            self.assertEqual(snapshot(selected)[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            self.assertEqual(json.loads(files[GO_EVENT_PROFILE])['idempotencyProfile'], profile)
            output = root / 'package'
            output.mkdir()
            self.assertEqual(package_effect_requirements(output, project, files)[0], EVENT_REQUIREMENTS)
            bad = dict(files)
            changed = json.loads(bad[EVENT_REQUIREMENTS])
            changed['binding'] = 'other-event'
            bad[EVENT_REQUIREMENTS] = json.dumps(changed).encode()
            with self.assertRaisesRegex(ValueError, 'requirements-drift'):
                package_effect_requirements(root, project, bad)
            with self.assertRaisesRegex(ValueError, 'closed-current-event-inputs-required'):
                package_effect_requirements(root, project, {**files, C_EVENT_PROFILE: files[GO_EVENT_PROFILE]})
            with self.assertRaisesRegex(ValueError, 'event profile'):
                create(root / 'invalid', 'greeting', event_profile=profile)
            with self.assertRaisesRegex(ValueError, 'event profile'):
                create(root / 'invalid-profile', TEMPLATE, event_profile='invalid')
            with self.assertRaisesRegex(ValueError, 'exclusive Go aggregate'):
                authored_project('c', 'aggregate', root / 'foreign', go_current_event_profile=profile)
            with self.assertRaisesRegex(ValueError, 'exclusive explicit'):
                compile_guests('go', root / 'foreign-output', go_current_event_profile=profile,
                               c_current_event_profile=profile)
            self.assertFalse((root / 'foreign-output').exists())

    def test_c_event_profile_captures_and_packages_only_exact_companion_requirements(self):
        from tools.compile_transaction_guests import authored_project
        from tools.c_capsule import main as c_main
        from tools.c_capsule_project import create, validate
        from tools.transaction_guest_project import (C_EVENT_PROFILE, EVENT_REQUIREMENTS,
                                                       RUST_EVENT_PROFILE, package_effect_requirements)
        profile = 'js-window-v1:' + 'b' * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(c_main(['new', str(root / 'source'), '--template', TEMPLATE,
                                     '--name', 'transaction-c-aggregate', '--event-profile', profile]), 0)
            files = snapshot(root / 'source')
            project, _, _ = validate(files)
            selected = authored_project('c', 'aggregate', root / 'selected', c_current_event_profile=profile)
            self.assertEqual(snapshot(selected)[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            with self.assertRaisesRegex(ValueError, 'exclusive C aggregate'):
                authored_project('rust', 'aggregate', root / 'foreign', c_current_event_profile=profile)
            self.assertEqual(json.loads(files[C_EVENT_PROFILE])['idempotencyProfile'], profile)
            output = root / 'package'
            output.mkdir()
            self.assertEqual(package_effect_requirements(output, project, files)[0], EVENT_REQUIREMENTS)
            self.assertEqual((output / EVENT_REQUIREMENTS).read_bytes(), files[EVENT_REQUIREMENTS])
            with self.assertRaisesRegex(ValueError, 'closed-current-event-inputs-required'):
                package_effect_requirements(root, project, {**files, RUST_EVENT_PROFILE: files[C_EVENT_PROFILE]})
            with self.assertRaisesRegex(ValueError, 'event profile'):
                create(root / 'invalid', 'greeting', event_profile=profile)
            with self.assertRaisesRegex(ValueError, 'event profile'):
                create(root / 'invalid-profile', TEMPLATE, event_profile='invalid')

    def test_rust_event_profile_is_explicit_captured_and_checked_before_packaging(self):
        from tools.compile_transaction_guests import authored_project
        from tools.rust_capsule import main as rust_main
        from tools.rust_capsule_project import create
        from tools.rust_capsule_build import validate_project
        from tools.transaction_guest_project import (EVENT_REQUIREMENTS, RUST_EVENT_PROFILE,
                                                       CURRENT_EVENT_PROFILE, package_effect_requirements)
        profile = "js-window-v1:" + "a" * 64
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = create(root / "source", TEMPLATE, "transaction-rust-aggregate", event_profile=profile)
            files = snapshot(source)
            value, _ = validate_project(files)
            selected = authored_project("rust", "aggregate", root / "selected", rust_current_event_profile=profile)
            selected_files = snapshot(selected)
            self.assertEqual(selected_files[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            self.assertEqual(selected_files[RUST_EVENT_PROFILE], files[RUST_EVENT_PROFILE])
            self.assertEqual(rust_main(['new', str(root / 'cli'), '--template', TEMPLATE,
                                        '--name', 'transaction-rust-aggregate', '--event-profile', profile]), 0)
            self.assertEqual(snapshot(root / 'cli')[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            with self.assertRaisesRegex(ValueError, "exclusive Rust aggregate"):
                authored_project("java", "aggregate", root / "foreign", rust_current_event_profile=profile)
            self.assertEqual(json.loads(files[RUST_EVENT_PROFILE])["idempotencyProfile"], profile)
            self.assertEqual(json.loads(files[EVENT_REQUIREMENTS])["capsule"], value["service"])
            output = root / "package"
            output.mkdir()
            self.assertEqual(package_effect_requirements(output, value, files)[0], EVENT_REQUIREMENTS)
            self.assertEqual((output / EVENT_REQUIREMENTS).read_bytes(), files[EVENT_REQUIREMENTS])
            bad = dict(files)
            changed = json.loads(bad[EVENT_REQUIREMENTS])
            changed["binding"] = "other-event"
            bad[EVENT_REQUIREMENTS] = json.dumps(changed).encode()
            with self.assertRaisesRegex(ValueError, "requirements-drift"):
                package_effect_requirements(root, value, bad)
            with self.assertRaisesRegex(ValueError, "closed-current-event-inputs-required"):
                package_effect_requirements(root, value, {**files, CURRENT_EVENT_PROFILE: files[RUST_EVENT_PROFILE]})
            with self.assertRaisesRegex(ValueError, "event profile"):
                create(root / "bad", "greeting", event_profile=profile)
            with self.assertRaisesRegex(ValueError, "event profile"):
                create(root / "bad-profile", TEMPLATE, event_profile="js-window-v1:invalid")
            from tools.transaction_guest_variants import create as variant
            denial = variant(root / "denial", "rust", "forbidden-http", "transaction-rust-aggregate",
                             rust_event_profile=profile)
            denial_files = snapshot(denial)
            self.assertEqual(denial_files[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            self.assertIn(b"latent_guest::http::send(", denial_files["src/lib.rs"])
            boundary = variant(root / "boundary", "rust", "result-boundary", "transaction-rust-aggregate",
                               rust_event_profile=profile)
            self.assertEqual(snapshot(boundary)[EVENT_REQUIREMENTS], files[EVENT_REQUIREMENTS])
            with self.assertRaisesRegex(ValueError, "explicit Rust transaction variant"):
                variant(root / "other", "java", "forbidden-http", rust_event_profile=profile)

    def test_java_authored_wit_captures_runtime_clocks_before_compiler_staging(self):
        from tools.compile_transaction_guests import authored_project, JAVA_SCHEMA_VARIANTS
        from tools.java_capsule_project import validate
        from tools.stage_runtime_wit import dependencies, stage
        with tempfile.TemporaryDirectory() as temporary:
            for variant in ("aggregate", "forbidden-http", *JAVA_SCHEMA_VARIANTS):
                with self.subTest(variant=variant):
                    source = authored_project("java", variant, Path(temporary) / variant)
                    files = snapshot(source)
                    validate(files)
                    clock = files["wit/deps/clock/package.wit"]
                    self.assertEqual(clock, files["vendor/lsf/wit/platform/clock/package.wit"])
                    self.assertEqual(clock, (ROOT / "wit/platform/clock/package.wit").read_bytes())
                    # Raw WIT inspection has a complete declared dependency
                    # tree, including clocks required by both runtime worlds.
                    self.assertEqual(dependencies(source / "wit", source / "vendor/lsf/wit/platform"), [])
                    staged = Path(temporary) / (variant + "-staged")
                    stage(staged, source / "wit")
                    self.assertEqual(snapshot(staged), snapshot(source / "wit"))
                    self.assertEqual(snapshot(source), files)

    def test_rust_result_boundary_is_a_real_captured_authored_guest_with_unchanged_sdk_and_grants(self):
        from tools.transaction_guest_variants import create
        from tools.rust_capsule_build import validate_project
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / "result", "rust", "result-boundary", "transaction-rust-aggregate")
            files = snapshot(project)
            validate_project(files)
            source = ROOT / "examples/rust-capsules" / TEMPLATE
            self.assertEqual(files["src/lib.rs"], (source / "result-boundary.rs").read_bytes())
            self.assertEqual(files["wit/world.wit"], (source / "result-boundary-world.wit").read_bytes())
            self.assertIn(b'Command::acquire()', files["src/lib.rs"])
            self.assertIn(b'command.put(', files["src/lib.rs"])
            self.assertIn(b'.stage(&mut command)', files["src/lib.rs"])
            self.assertIn(b'-> tuple<string, string, string, string>;', files["wit/world.wit"])
            declaration = json.loads(files["capsule-project.json"])
            self.assertEqual(declaration["limits"]["outboundRequests"], 0)
            self.assertEqual(json.loads(files["transaction-binding.json"])["namespace"], TEMPLATE)
            with self.assertRaisesRegex(ValueError, "requires Rust"):
                create(Path(temporary) / "unsupported", "java", "result-boundary")


    def test_rust_authored_projects_select_and_pin_their_guest_binding_profile(self):
        import tomllib
        from tools.rust_capsule_project import create
        from tools.rust_capsule_build import validate_project
        with tempfile.TemporaryDirectory() as temporary:
            for template in (*TEMPLATES, TEMPLATE):
                with self.subTest(template=template):
                    project = create(Path(temporary) / template, template)
                    files = snapshot(project)
                    validate_project(files)
                    cargo = tomllib.loads(files["Cargo.toml"].decode())
                    guest = cargo["target"]['cfg(target_arch = "wasm32")']["dependencies"]["latent-guest"]
                    self.assertEqual(guest.get("features", []), ["transaction"] if template == TEMPLATE else [])
                    raw = files["Cargo.toml"]
                    if template == TEMPLATE:
                        changed = raw.replace(b', features = ["transaction"]', b"")
                    else:
                        changed = raw.replace(b'latent-guest = { path = "vendor/lsf/sdk/rust-guest" }',
                            b'latent-guest = { path = "vendor/lsf/sdk/rust-guest", features = ["transaction"] }')
                    self.assertNotEqual(changed, raw)
                    with self.assertRaisesRegex(ValueError, "pinned authoring recipe"):
                        validate_project({**files, "Cargo.toml": changed})

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
        calls = ("latent_guest::http::send(", "latent_http_client_send(", "send(",
                 "http.Send(", "Bindings.LatentHttpClient.send(", "Http.Send(")
        typed_denials = {
            "rust": "Err(latent_guest::http::HttpError::PermissionDenied)",
            "c": "frame->http_result.val.err.tag == LATENT_HTTP_CLIENT_HTTP_ERROR_PERMISSION_DENIED",
            "typescript": "forbidden.tag === 'err' && forbidden.val.tag === 'permission-denied'",
            "go": "!forbidden.IsOk() && forbidden.Err().Tag() == http.HttpErrorPermissionDenied",
            "java": "Bindings.LatentHttpClientHttpError.permissionDenied().tag()",
            "dotnet": "!forbidden.IsOk && forbidden.AsErr.Tag == HttpRaw.HttpError.Tags.PermissionDenied",
        }
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
                    self.assertIn(typed_denials[language], code)
                    staging = {"rust": '.stage(&mut command)', "c": 'lsf_intent_stage(',
                               "typescript": '.stage(command)', "go": '.Stage(command)',
                               "java": '.stage(command)', "dotnet": '.Stage(command)'}
                    self.assertLess(code.index(staging[language]), code.index(call),
                                    "real staging must precede the forbidden call so rejection tests rollback")
                    # The native schedule sends reject=false. A declared
                    # rejection therefore witnesses this exact typed error;
                    # success, another HTTP error or a trap cannot satisfy it.
                    self.assertIn("REJECTED" if language in ("c", "dotnet") else
                                  "'rejected'" if language == "typescript" else "Rejected", code)
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

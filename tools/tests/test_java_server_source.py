"""Exact selection, bridge and captured source binding; no real-node claim."""
from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from tools import java_server_source as java, server_source as source
from tools.java_capsule_project import ROOT, validate
from tools.java_server_project import create_server
from tools.rust_capsule_project import canonical, snapshot
from tools.tests.test_server_source import fixture


class JavaServerSource(unittest.TestCase):
    def test_new_project_uses_ordinary_source_and_no_application_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create_server(Path(temporary) / "outside", "independent-server")
            files = snapshot(project)
            selected, lock, _pins = validate(files)
            self.assertEqual(selected["server"], {"profile": java.PROFILE_ID, "entryPoint": "dev.latent.app.Server"})
            self.assertNotIn("src/dev/latent/app/Capsule.java", files)
            self.assertIn(b"import com.sun.net.httpserver.HttpServer;", files["src/dev/latent/app/Server.java"])
            self.assertIn("sdk/java-guest/server/analysis/ServerAnalyzer.java", lock["sdk"])
            self.assertEqual(selected["world"], "examples:independent-server/service@1.0.0")
            self.assertIn(b"export latent:web/application@0.1.0", files["wit/world.wit"])
            self.assertNotIn(b"package latent:", files["wit/world.wit"])

    def test_new_server_cli_preserves_ordinary_creation_and_dependency_authoring_dispatch(self):
        import contextlib
        import io
        from tools import java_capsule

        with tempfile.TemporaryDirectory() as temporary:
            project = Path(temporary) / 'outside-server'
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = java_capsule.main(['new-server', str(project), '--name', 'independent-cli-server'])
            self.assertEqual(result, 0, stderr.getvalue())
            files = snapshot(project)
            selected, _lock, _pins = validate(files)
            self.assertEqual(selected['server']['profile'], java.PROFILE_ID)
            self.assertIn(b'import com.sun.net.httpserver.HttpServer;', files['src/dev/latent/app/Server.java'])
            self.assertNotIn('src/dev/latent/app/Capsule.java', files)
            parsed = java_capsule.parser().parse_args(['add', str(project), 'outside:pure:1.0.0'])
            self.assertEqual((parsed.command, parsed.coordinate), ('add', 'outside:pure:1.0.0'))

    def test_selection_rejects_code_expressions_reserved_owners_and_unknown_profiles(self):
        valid = {"profile": java.PROFILE_ID, "entryPoint": "independent.RouterServer"}
        self.assertEqual(java.selection(valid), valid)
        for entry in ("independent.RouterServer(); malicious()", "java.lang.System", "dev.latent.app.Capsule", "dev.latent.guest.Server"):
            with self.subTest(entry=entry), self.assertRaises(ValueError): java.selection({**valid, "entryPoint": entry})
        with self.assertRaises(ValueError): java.selection({**valid, "profile": "unreviewed"})
        with self.assertRaises(ValueError): java.selection({**valid, "plugin": "application"})

    def test_bridge_calls_original_main_and_checks_captured_registration(self):
        _files, _profile, plan, *_rest = fixture()
        selected = {"profile": java.PROFILE_ID, "entryPoint": "independent.RouterServer"}
        plan["initializer"] = selected["entryPoint"] + ".main"
        generated = java.bridge(ROOT / "sdk/java-guest", selected, plan)
        self.assertIn(b"independent.RouterServer.main(new String[0]);", generated)
        self.assertIn(b'ServerSession.verify("wildcard", 8080, 0, new String[]{"/api/hey"});', generated)
        self.assertIn(b"finally", generated)
        self.assertNotIn(b"/*LSF_", generated)
        plan["initializer"] = "Changed.main"
        with self.assertRaises(ValueError): java.bridge(ROOT / "sdk/java-guest", selected, plan)

    def test_invalid_or_conflicting_captured_routes_cannot_be_generated(self):
        _files, _profile, plan, *_rest = fixture()
        selected = {"profile": java.PROFILE_ID, "entryPoint": "IndependentServer"}
        # Java entrypoint selection requires an explicitly qualified class.
        selected["entryPoint"] = "independent.Server"
        plan["initializer"] = "independent.Server.main"
        for path in ('/bad"; escape(); //', "/a%2Fb", "/_lsf/control", "/a//b"):
            changed = copy.deepcopy(plan)
            changed["endpoints"][0]["contexts"][0]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError): java.bridge(ROOT / "sdk/java-guest", selected, changed)
        plan["endpoints"][0]["contexts"].append(copy.deepcopy(plan["endpoints"][0]["contexts"][0]))
        with self.assertRaises(ValueError): java.bridge(ROOT / "sdk/java-guest", selected, plan)

    def test_selected_profile_cannot_advertise_fewer_owners_than_its_plan(self):
        files, profile, plan, *_rest = fixture()
        profile["limits"]["endpoints"] = 1
        second = copy.deepcopy(plan["endpoints"][0])
        second["id"] = "another"
        second["bind"]["port"] = 9090
        plan["endpoints"].append(second)
        with self.assertRaisesRegex(ValueError, "selected-profile-limit"):
            source.emit(files, b"model", canonical(profile), plan, {"types": {}, "functions": {"handle": {}}})

    def test_forged_original_main_world_or_application_bridge_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create_server(Path(temporary) / "outside")
            files = snapshot(project)
            with_bridge = {**files, "src/dev/latent/app/Capsule.java": b"// must not override generated bridge"}
            with self.assertRaisesRegex(ValueError, "original main"): validate(with_bridge)
            project_value, _lock, _pins = validate(files)
            project_value["world"] = "unrelated:world/service@1.0.0"
            changed = {**files, "capsule-project.json": canonical(project_value)}
            with self.assertRaisesRegex(ValueError, "authoritative web world"): validate(changed)

    def test_server_and_http_client_profiles_preserve_trusted_services_before_compilation(self):
        from unittest.mock import patch
        from tools.java_guest import compiler as java_compiler

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = root / 'source'; sources.mkdir()
            (sources / 'Main.java').write_text('final class Main {}\n', encoding='utf-8')
            wit = root / 'wit'; wit.mkdir()
            (wit / 'world.wit').write_text('package outside:fixture; world service {}\n', encoding='utf-8')
            owner = java_compiler.Compiler.__new__(java_compiler.Compiler)
            owner.sdk, owner.platform, owner.offline = ROOT / 'sdk/java-guest', ROOT / 'wit/platform', True

            def generated(_run, _wit, _world, destination):
                destination.mkdir()
                (destination / 'Bindings.java').write_bytes(b'// controlled binding boundary\n')
                (destination / 'probe.c').write_bytes(b'/* controlled ABI: no transaction import attributes */\n')
                return {'source': 'controlled-binding'}

            class CompileBoundary(Exception):
                pass

            invoked = []
            def stop(stage, tool, *arguments, cwd=None):
                invoked.append((stage, tool, arguments, cwd))
                raise CompileBoundary()

            owner.run = stop
            destination = root / 'compiled'
            with patch.object(java_compiler, 'generate', side_effect=generated):
                with self.assertRaises(CompileBoundary):
                    owner.compile(sources, wit, 'outside:fixture/service', destination,
                                  server_profile=True, http_client_profile=True)
            self.assertEqual(len(invoked), 1)
            self.assertEqual(invoked[0][:2], ('java-to-c', 'gradle'))
            self.assertIn('--offline', invoked[0][2])
            project = destination / 'project'
            self.assertEqual(invoked[0][3], project)
            names = set(snapshot(owner.sdk / 'server/services')) | set(snapshot(owner.sdk / 'client/services'))
            for name in names:
                expected = []
                for profile in ('server', 'client'):
                    path = owner.sdk / profile / 'services' / name
                    if path.is_file(): expected.extend(path.read_bytes().splitlines())
                self.assertEqual((project / 'src/main/resources' / name).read_bytes().splitlines(), expected)
            self.assertTrue((project / 'src/main/java/dev/latent/guest/server/http/HttpServer.java').is_file())
            self.assertTrue((project / 'src/main/java/dev/latent/guest/client/Connection.java').is_file())
            self.assertEqual((project / 'build.gradle').read_text(encoding='utf-8').count("compileOnly 'org.teavm:teavm-core:0.15.0'"), 1)

    def test_trusted_sdk_service_union_preserves_resources_and_rejects_duplicate_or_unowned_providers(self):
        from tools.java_guest.compiler import stage_sdk_service

        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'org.teavm.vm.spi.TeaVMPlugin'
            name = 'META-INF/services/org.teavm.vm.spi.TeaVMPlugin'
            profiles = (b'dev.latent.guest.resources.compiler.ImmutableResourcePlugin\n',
                        b'dev.latent.guest.server.compiler.ServerPlugin\n',
                        b'dev.latent.guest.client.compiler.HttpPlugin\n')
            for selected in profiles: stage_sdk_service(target, name, selected)
            original = target.read_bytes()
            self.assertEqual(original, b''.join(profiles))
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                stage_sdk_service(target, name, profiles[-1])
            with self.assertRaisesRegex(ValueError, 'invalid Java SDK'):
                stage_sdk_service(target, 'META-INF/services/outside.application.Plugin', b'outside.application.Plugin\n')
            self.assertEqual(target.read_bytes(), original)


if __name__ == "__main__": unittest.main()

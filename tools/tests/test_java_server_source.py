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


if __name__ == "__main__": unittest.main()

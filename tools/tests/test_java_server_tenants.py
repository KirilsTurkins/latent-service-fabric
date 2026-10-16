"""Source and policy controls; actual same-node execution is a separate gate."""
from pathlib import Path
import json
import shutil
import subprocess
import tempfile
import unittest
from types import SimpleNamespace

from tools.java_capsule_project import ROOT, validate
from tools.java_server_tenant_project import create
from tools.java_server_tenants import TenantControls
from tools.java_server_node import grant_runtime, runtime_config
from tools.rust_capsule_project import snapshot


class SharedTenantServer(unittest.TestCase):
    def test_neutral_project_retains_original_sdk_helper_and_zero_egress_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = create(Path(temporary) / "project")
            files = snapshot(project)
            declaration, _lock, _pins = validate(files)
            self.assertIsNone(declaration["tenant"])
            self.assertEqual(declaration["service"], "tenant-isolation-server")
            self.assertEqual(declaration["limits"]["outboundRequests"], 0)
            self.assertEqual(declaration["limits"]["memoryBytes"], 67108864)
            self.assertEqual(declaration["limits"]["cpuFuel"], 1000000000)
            self.assertEqual(declaration["limits"]["wallTimeLimitMillis"], 120000)
            self.assertEqual(files["src/outside/developer/routes/Router.java"],
                (ROOT / "sdk/java-guest/tests/server/Router.java").read_bytes())
            self.assertIn(b'new Object[]{marker, input}', files["src/outside/developer/routes/TenantRoutes.java"])
            self.assertNotIn(b'dev.latent.guest', files["src/outside/developer/routes/TenantRoutes.java"])

    @unittest.skipUnless(shutil.which("javac"), "native JDK source control")
    def test_original_standard_api_handler_compiles_with_published_jdk_surface(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / "project")
            result = subprocess.run(["javac", "-proc:none", "-encoding", "UTF-8", "-d", str(root / "classes"),
                *map(str, sorted((project / "src").rglob("*.java")))], capture_output=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))

    def test_second_scope_aliases_never_change_original_node_capacity_or_grant_authority(self):
        settings = {"cells": [{"capacity": 1}]}
        runtime_config(settings, "server")
        original = json.loads(json.dumps(settings["providers"]))
        observer = TenantControls(Path("unopened-fixture"))
        observer.configure(settings, "server")
        observer.configure_ingress(settings)
        self.assertIsNone(observer.grant_initial_http(None))
        self.assertEqual(settings["cells"], [{"capacity": 1}])
        self.assertEqual(settings["providers"]["bindings"][:3], original["bindings"])
        aliases = settings["providers"]["scalarAliases"]
        self.assertEqual({row["source"] for row in aliases}, {"clockMonotonic", "clockWall", "context"})
        self.assertTrue(all(row["identity"]["tenant"] == "foreign" for row in aliases))
        self.assertNotIn("activationRuntime", settings["providers"])
        self.assertNotIn("http", settings["providers"])

    def test_real_package_metadata_keeps_neutral_service_and_omits_tenant_without_rewriting_source(self):
        from unittest.mock import patch
        from tools.rust_capsule_build import package_inputs
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = create(root / "project")
            files = snapshot(project)
            declaration, _lock, _pins = validate(files)
            output = root / "package-inputs"; output.mkdir()
            # Only unrelated compatibility/resource assembly is isolated here;
            # the real shared metadata emitter and fixture inputs remain in use.
            with patch("tools.rust_capsule_build.guest_compatibility_build.package_report"), \
                    patch("tools.rust_capsule_build.guest_resources.assemble", return_value=[]):
                package_inputs(output, declaration, {"exports": [], "imports": []}, files, b"metadata-control")
            manifest = json.loads((output / "capsule.json").read_bytes())
            deployment = json.loads((output / "deployment.json").read_bytes())
            self.assertEqual(manifest["metadata"]["name"], "tenant-isolation-server")
            self.assertNotIn("tenant", manifest["metadata"])
            self.assertNotIn("tenant", deployment["metadata"])
            self.assertEqual(deployment["spec"]["service"], manifest["metadata"]["name"])
            self.assertEqual(manifest["component"]["world"], declaration["world"])
            self.assertEqual(snapshot(project), files)
            from tools.qualify_java_server_tenants import select_initial_tenant
            signed_metadata = (output / "capsule.json").read_bytes()
            select_initial_tenant(output / "deployment.json")
            selected = json.loads((output / "deployment.json").read_bytes())
            deployment["metadata"]["tenant"] = "examples"
            self.assertEqual(selected, deployment)
            self.assertEqual((output / "capsule.json").read_bytes(), signed_metadata)
            self.assertEqual(snapshot(project), files)
            selected_bytes = (output / "deployment.json").read_bytes()
            with self.assertRaisesRegex(ValueError, "tenant-isolation-neutral-deployment"):
                select_initial_tenant(output / "deployment.json")
            self.assertEqual((output / "deployment.json").read_bytes(), selected_bytes)

    def test_grants_require_exact_descriptor_tenant_and_separate_trigger_and_publication(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            class Client:
                def __init__(self):
                    self.directory = directory
                    self.calls = []
                def call(self, *arguments):
                    self.calls.append(arguments)
            node = SimpleNamespace(startup_record={"providers": [{"id": name + "-foreign", "tenant": "foreign",
                "configurationDigest": "sha256:" + "a" * 64} for name in ("clockMonotonic", "clockWall", "context")]})
            client = Client()
            grants = grant_runtime(client, node, {"service": "server"}, "foreign-publication",
                tenant="foreign", principal="foreign-caller", suffix="-foreign")
            self.assertEqual(len(grants), 3)
            self.assertEqual(len(client.calls), 6)
            for name in ("clockMonotonic", "clockWall", "context"):
                policy = json.loads((directory / (name + "-policy.json")).read_bytes())
                self.assertEqual(policy["tenant"], "foreign")
                self.assertEqual(policy["rules"][0]["publications"], ["foreign-publication"])
                self.assertEqual(policy["rules"][0]["principals"], [{"kind": "trigger", "subject": "foreign-caller"}])
            node.startup_record["providers"][0]["tenant"] = "examples"
            with self.assertRaisesRegex(RuntimeError, "runtime-provider-tenant"):
                grant_runtime(client, node, {"service": "server"}, "foreign-publication",
                    tenant="foreign", principal="foreign-caller", suffix="-foreign")


if __name__ == "__main__":
    unittest.main()

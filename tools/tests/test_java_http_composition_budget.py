"""Actual authoring captures for the finite composed drain fixture."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.java_capsule_project import create
from tools.java_http_composition import build as composition
from tools.java_http_composition.build import COMPOSITION_CPU_FUEL, qualification_budget
from tools.java_http_composition.node import configure
from tools.java_http_composition.revision import create_revision
from tools.rust_capsule_project import ROOT, digest, read_json, snapshot, write_json


class JavaCompositionBudgetTests(unittest.TestCase):
    def test_generation_obligations_precede_fixture_budget_and_revision_capture(self):
        with tempfile.TemporaryDirectory() as owned:
            directory = Path(owned)
            observed = []

            def generated(_domain, _selection, output):
                parent = create(output, "greeting", "java-http-adapter")
                fixture = ROOT / "examples/java-http-composition/adapter"
                for source, target in (("Capsule.java", "src/dev/latent/app/Capsule.java"), ("world.wit", "wit/world.wit")):
                    (parent / target).write_bytes((fixture / source).read_bytes())
                return parent

            def checked(domain, _selection, adapter, *extra):
                self.assertEqual(read_json(domain / "capsule-project.json")["limits"]["cpuFuel"], COMPOSITION_CPU_FUEL)
                self.assertEqual(read_json(adapter / "capsule-project.json")["limits"]["cpuFuel"], 1_000_000_000)
                observed.append("negatives" if extra else "check")

            with patch.object(composition, "generate", side_effect=generated), \
                    patch.object(composition, "check", side_effect=checked), \
                    patch.object(composition, "qualify_generation", side_effect=checked):
                projects = composition.projects(directory / "projects", generation_cases=directory / "generation-cases")
            self.assertEqual(observed, ["check", "negatives"])
            for name in ("domain", "adapter"):
                self.assertEqual(read_json(projects[name] / "capsule-project.json")["limits"]["cpuFuel"], COMPOSITION_CPU_FUEL)
            self.assertEqual(read_json(projects["adapter-next"] / "capsule-project.json")["limits"]["cpuFuel"], COMPOSITION_CPU_FUEL - 1)
            self.assertEqual(read_json(projects["context-required"] / "capsule-project.json")["limits"]["cpuFuel"], 1_000_000_000)

    def test_fresh_capture_preserves_source_and_every_other_budget_dimension(self):
        with tempfile.TemporaryDirectory() as owned:
            directory = Path(owned)
            project = create(directory / "domain", "greeting", "java-http-domain")
            before = snapshot(project)
            observed = qualification_budget(project)
            after = snapshot(project)
            self.assertEqual(before.keys(), after.keys())
            self.assertEqual(observed["beforeDescriptorDigest"], digest(before["capsule-project.json"]))
            self.assertEqual(observed["afterDescriptorDigest"], digest(after["capsule-project.json"]))
            for name in before.keys() - {"capsule-project.json"}:
                self.assertEqual(before[name], after[name])
            before_limits = observed["beforeLimits"]
            after_limits = observed["afterLimits"]
            self.assertEqual(before_limits["cpuFuel"], 1_000_000_000)
            self.assertEqual(after_limits["cpuFuel"], COMPOSITION_CPU_FUEL)
            for name in before_limits.keys() - {"cpuFuel"}:
                self.assertEqual(before_limits[name], after_limits[name])
            releases = directory / "releases"
            releases.mkdir()
            write_json(releases / "policy.json", {})
            node = directory / "node"
            node.mkdir()
            config, _host = configure(node, releases, http=False)
            self.assertEqual(read_json(config)["execution"]["maximumCpuFuel"], after_limits["cpuFuel"])
            self.assertFalse(observed["signedExecutionQualified"])

    def test_changed_or_repeated_input_refuses_without_overwriting_its_owner(self):
        with tempfile.TemporaryDirectory() as owned:
            project = create(Path(owned) / "domain", "greeting", "java-http-domain")
            qualification_budget(project)
            captured = snapshot(project)
            with self.assertRaisesRegex(ValueError, "java-composition-default-cpu-budget-changed"):
                qualification_budget(project)
            self.assertEqual(snapshot(project), captured)

    def test_independent_revision_retains_exact_parent_capture_and_smaller_ceiling(self):
        with tempfile.TemporaryDirectory() as owned:
            directory = Path(owned)
            parent = create(directory / "adapter", "greeting", "java-http-adapter")
            fixture = ROOT / "examples/java-http-composition/adapter"
            for source, target in (("Capsule.java", "src/dev/latent/app/Capsule.java"), ("world.wit", "wit/world.wit")):
                (parent / target).write_bytes((fixture / source).read_bytes())
            qualification_budget(parent)
            captured = snapshot(parent)
            candidate = create_revision(parent, directory / "adapter-next")
            self.assertEqual(snapshot(parent), captured)
            limits = read_json(candidate / "capsule-project.json")["limits"]
            self.assertEqual(limits["cpuFuel"], COMPOSITION_CPU_FUEL - 1)
            self.assertEqual(read_json(parent / "capsule-project.json")["limits"]["cpuFuel"], COMPOSITION_CPU_FUEL)
            self.assertEqual((candidate / "wit/world.wit").read_bytes(), captured["wit/world.wit"])
            self.assertNotEqual((candidate / "src/dev/latent/app/Capsule.java").read_bytes(), captured["src/dev/latent/app/Capsule.java"])


if __name__ == "__main__":
    unittest.main()

"""Finite startup recognizer and explicit historical protocol boundaries."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest

from jsonschema import Draft202012Validator

from tools.optimization_evidence.common import EvidenceError, canonical
from tools.optimization_kubernetes import evidence, model, resources
from tools.tests.test_optimization_docker_resources import forward
from tools.tests.test_optimization_kubernetes_resources import KubernetesFixture

FIXTURES = Path(__file__).parent / "fixtures/kubernetes-startup-records"


def historical(profile="smoke", run="smoke-03"):
    commit, tree = model.HISTORICAL_STARTUPS[profile, run]
    return {"profile": profile, "run_id": run, "owner": model.HISTORICAL_OWNER,
            "source": {"commit": commit, "tree": tree, "clean": True, "cargo_lock_sha256": model.HISTORICAL_LOCK},
            "plan": model.plan(profile, owner=model.HISTORICAL_OWNER,
                               startup_protocol=model.HISTORICAL_STARTUP_PROTOCOL)}


class StartupProtocolTests(unittest.TestCase):
    def test_original_small_records_keep_exact_bytes(self):
        manifest = json.loads((FIXTURES / "manifest.json").read_bytes())
        for row in manifest["records"]:
            data = (FIXTURES / row["path"]).read_bytes()
            self.assertEqual(len(data), row["bytes"])
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])
            self.assertEqual([json.loads(line)["event"] for line in data.splitlines()], ["started", "ready"])

    def test_historical_plan_bytes_and_four_actual_identities(self):
        original = canonical(historical()["plan"])
        self.assertEqual(len(original), 6615)
        self.assertEqual(hashlib.sha256(original).hexdigest(),
                         "6bd9820d5cd19fda7f40ab434eec5e822ab427d1002f85c63a4aa661f3335896")
        for profile, run in model.HISTORICAL_STARTUPS:
            with self.subTest(profile=profile, run=run):
                self.assertEqual(model.suite_startup_protocol(historical(profile, run)),
                                 model.HISTORICAL_STARTUP_PROTOCOL)

    def test_every_historical_identity_field_and_probe_are_bound(self):
        changes = (lambda s: s.update(owner="another-owner"), lambda s: s.update(run_id="smoke-99"),
                   lambda s: s.update(profile="full"), lambda s: s["source"].update(commit="0" * 40),
                   lambda s: s["source"].update(tree="0" * 40), lambda s: s["source"].update(clean=False),
                   lambda s: s["source"].update(cargo_lock_sha256="sha256:" + "0" * 64),
                   lambda s: s["plan"].update(startup_probe=model.startup_probe()),
                   lambda s: s["plan"].update(startup_protocol=model.HISTORICAL_STARTUP_PROTOCOL))
        for mutate in changes:
            row = historical()
            mutate(row)
            with self.subTest(mutate=mutate), self.assertRaises(EvidenceError):
                model.suite_startup_protocol(row)

    def test_new_plan_is_explicit_and_old_sources_cannot_be_relabelled(self):
        row = historical()
        row["plan"] = model.plan("smoke", owner=row["owner"])
        with self.assertRaisesRegex(EvidenceError, "relabelled"):
            model.suite_startup_protocol(row)
        row["source"]["commit"] = "a" * 40
        self.assertEqual(model.suite_startup_protocol(row), model.CURRENT_STARTUP_PROTOCOL)
        self.assertEqual(row["plan"]["schema"], model.PREFIX + "plan.v2")
        self.assertEqual(row["plan"]["startup_prefix_bytes"], 65536)
        for key, value in (("startup_protocol", model.HISTORICAL_STARTUP_PROTOCOL),
                           ("startup_prefix_bytes", 65537), ("schema", model.PREFIX + "plan.v1")):
            changed = deepcopy(row)
            changed["plan"][key] = value
            with self.subTest(key=key), self.assertRaises(EvidenceError):
                model.suite_startup_protocol(changed)

    def test_probe_action_and_exact_control_fields_cannot_cross_protocols(self):
        for protocol in (model.CURRENT_STARTUP_PROTOCOL, model.HISTORICAL_STARTUP_PROTOCOL):
            value = model.startup_probe(startup_protocol=protocol)
            model.validate_startup_probe(value, startup_protocol=protocol)
            del value["initialDelaySeconds"]
            del value["successThreshold"]
            model.validate_startup_probe(value, startup_protocol=protocol)
            other = (model.HISTORICAL_STARTUP_PROTOCOL if protocol == model.CURRENT_STARTUP_PROTOCOL
                     else model.CURRENT_STARTUP_PROTOCOL)
            with self.assertRaises(EvidenceError):
                model.validate_startup_probe(value, startup_protocol=other)
            for change in ({"timeoutSeconds": True}, {"failureThreshold": 121}, {"extra": 0},
                           {"httpGet": {"path": "/", "port": 7070}}):
                with self.subTest(change=change), self.assertRaises(EvidenceError):
                    model.validate_startup_probe({**value, **change}, startup_protocol=protocol)

    def test_residual_connection_count_is_exact_for_each_arm_and_density(self):
        for arm in ("lsf", "native"):
            for density in model.DENSITIES:
                channels = density if arm == "lsf" else 1
                current = evidence.connection_accounting(arm, density, model.CURRENT_STARTUP_PROTOCOL)
                old = evidence.connection_accounting(arm, density, model.HISTORICAL_STARTUP_PROTOCOL)
                self.assertEqual((current["client_channels"], current["observed_residual"]), (channels, 0))
                self.assertEqual((old["client_channels"], old["observed_residual"]), (channels, 1))
                self.assertIs(current["source_peer_tracing"], False)
        with self.assertRaises(EvidenceError):
            evidence.connection_accounting("native", 1, "unknown")

    def test_current_owner_rejects_extra_probe_connection_and_forward_failure(self):
        with TemporaryDirectory() as name:
            fixture = KubernetesFixture(Path(name))
            with self.assertRaises(EvidenceError):
                fixture.validate(expected_connections=1)
            for event in fixture.fixture.events[2:]:
                value = forward(count=1, live=int(event["event"] == "snapshot"))
                value["maximum_live"] = "1"
                event["detail"]["forward"] = value
            fixture.fixture.write()
            fixture.validate(expected_connections=1)
            fixture.fixture.events[-1]["detail"]["forward"].update(failed="1", completed="0")
            fixture.fixture.write()
            with self.assertRaises(EvidenceError):
                fixture.validate(expected_connections=1)

    def test_resource_pod_validation_requires_explicit_old_protocol(self):
        with TemporaryDirectory() as name:
            fixture = KubernetesFixture(Path(name))
            for pod in (fixture.pod_ready, fixture.pod_final):
                pod["spec"]["containers"][0]["startupProbe"] = model.startup_probe(
                    startup_protocol=model.HISTORICAL_STARTUP_PROTOCOL)
            with self.assertRaises(EvidenceError):
                fixture.validate()
            fixture.validate(startup_protocol=model.HISTORICAL_STARTUP_PROTOCOL)

    def test_schemas_reject_crossed_or_unbound_old_and_new_plans(self):
        for name in ("suite", "aggregate"):
            schema = json.loads((Path(__file__).parents[1] / "optimization_kubernetes/schemas" /
                                 (name + ".schema.json")).read_bytes())
            Draft202012Validator.check_schema(schema)
            validator = Draft202012Validator({"$defs": schema["$defs"], "type": "object",
                "properties": {"plan": {"$ref": "#/$defs/plan"}}, "$ref": "#/$defs/startupProtocol"})
            row = historical()
            validator.validate(row)
            row["source"]["commit"] = "a" * 40
            self.assertFalse(validator.is_valid(row))
            row["plan"] = model.plan("smoke", owner=row["owner"])
            validator.validate(row)
            for key, value in (("startup_probe", model.startup_probe(startup_protocol=model.HISTORICAL_STARTUP_PROTOCOL)),
                               ("startup_prefix_bytes", 65537), ("startup_protocol", "other")):
                changed = deepcopy(row)
                changed["plan"][key] = value
                with self.subTest(schema=name, key=key):
                    self.assertFalse(validator.is_valid(changed))


@unittest.skipUnless(os.name == "posix" and Path("/bin/sh").is_file() and Path("/usr/bin/head").is_file(),
                     "executes the exact POSIX startup command; Windows retains pure protocol tests")
class StartupCommandTests(unittest.TestCase):
    def invoke(self, path):
        command = model.startup_probe()["exec"]["command"]
        result = subprocess.run([*command[:-1], str(path)], capture_output=True, timeout=3, check=False)
        self.assertEqual(result.stdout, b"")
        self.assertLessEqual(len(result.stderr), 4096)
        return result.returncode

    def check(self, data, success):
        with TemporaryDirectory() as name:
            path = Path(name) / "events.ndjson"
            if data is not None:
                path.write_bytes(data)
            self.assertEqual(self.invoke(path) == 0, success)
            if data is not None:
                self.assertEqual(path.read_bytes(), data)

    def test_actual_original_both_arms_and_later_records(self):
        for arm in ("lsf", "native"):
            actual = (FIXTURES / (arm + ".ndjson")).read_bytes()
            with self.subTest(arm=arm):
                self.check(actual, True)
                self.check(actual + b"unread-later-record\n" * 10000, True)

    def test_absent_empty_started_only_and_each_partial_ready_record_fail(self):
        actual = (FIXTURES / "native.ndjson").read_bytes()
        started, ready = actual.splitlines(keepends=True)
        for data in (None, b"", started, started[:-1], started + ready[:20], actual[:-1], actual[:-2],
                     b"x" * model.STARTUP_PREFIX_BYTES + actual):
            with self.subTest(size=None if data is None else len(data)):
                self.check(data, False)

    def test_malformed_or_crossed_complete_lines_fail(self):
        actual = (FIXTURES / "native.ndjson").read_bytes()
        started, ready = actual.splitlines(keepends=True)
        for data in (actual.replace(b"\n", b"\r\n"), ready + started, started + ready[:-2] + b"\n",
                     actual.replace(b'"sequence":1', b'"sequence":0'),
                     actual.replace(b'"wrapper_pid":1', b'"wrapper_pid":2'),
                     actual.replace(b'"event":"started"', b'"event":"ready"'),
                     actual.replace(b'"maximum_connections":32', b'"maximum_connections":31'),
                     actual.replace(b'"child_pid":13', b'"child_pid":013'),
                     actual.replace(b'container-event.v1', b'container-event.v2'),
                     started + ready.replace(b'"child_pid":13', b'"child_pid":14'),
                     started + ready.replace(b'"app":"native"', b'"app":"lsf"'),
                     started + ready.replace(b'"elapsed_nanos":"9497304"', b'"elapsed_nanos":"0"'),
                     started + ready.replace(b'"implementation":"native-reference"', b'"implementation":"other"')):
            with self.subTest(data=data[-150:]):
                self.check(data, False)

    def test_directory_and_symlink_are_rejected(self):
        with TemporaryDirectory() as name:
            directory = Path(name)
            self.assertNotEqual(self.invoke(directory), 0)
            target = directory / "target"
            target.write_bytes((FIXTURES / "lsf.ndjson").read_bytes())
            link = directory / "events.ndjson"
            link.symlink_to(target)
            self.assertNotEqual(self.invoke(link), 0)


if __name__ == "__main__":
    unittest.main()

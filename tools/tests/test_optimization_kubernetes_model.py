"""Pure manifest and count checks; no cluster or fabricated benchmark evidence."""
import unittest

from tools.optimization_docker import model as docker
from tools.optimization_evidence.common import EvidenceError
from tools.optimization_kubernetes import model


OWNER = "lsf-112-abcdef012345"
RUN = "smoke-01"
IMAGE_PREFIX = "lsf111-images-fc45a33903fb46eea767:"


class KubernetesModelTests(unittest.TestCase):
    def pod(self, arm="lsf", density=1, **changes):
        fields = {"image": IMAGE_PREFIX + arm, "command": ["--output", "/output"],
                  "arm": arm, "density": density, "owner": OWNER, "run_id": RUN,
                  "role": model.client_role(0) if arm == "client" else model.application_role(0, 0, arm),
                  "fixtures": model.host_path(OWNER, RUN, "fixtures"),
                  "output": model.host_path(OWNER, RUN, "output/owner-0"),
                  "data": model.host_path(OWNER, RUN, "data/owner-0") if arm == "lsf" else None}
        fields.update(changes)
        return model.pod(**fields)

    def test_workload_and_order_are_exactly_the_docker_population(self):
        for profile, offers, pairs in (("smoke", "300", 1), ("full", "9926", 7)):
            with self.subTest(profile=profile):
                plan = model.plan(profile, owner=OWNER)
                self.assertEqual(plan["workload"], docker.plan(profile))
                self.assertEqual(plan["workload"]["logical_offers"], offers)
                self.assertEqual(plan["measured_services"], 82 * pairs)
                self.assertEqual(sum(len(model.groups(profile, pair)) for pair in range(pairs)), 6 * pairs)
                for pair in range(pairs):
                    self.assertEqual(model.groups(profile, pair), docker.groups(profile, pair))

    def test_seed_reuse_does_not_claim_new_setup_calls(self):
        plan = model.plan("full", owner=OWNER)
        self.assertEqual(plan["seed_reuse"], {"source": "docker-stopped-pristine-catalogs",
            "densities": [1, 8, 32], "new_lsf_starts": 0, "new_management_rpcs": 0, "new_guest_invokes": 0})
        self.assertEqual(plan["workload"]["seed_management_rpcs"], 88)
        plan["workload"]["groups"][0][0]["phases"].clear()
        self.assertTrue(model.plan("full", owner=OWNER)["workload"]["groups"][0][0]["phases"])

    def test_native_resource_partitions_match_cohort_totals(self):
        for density in (1, 8, 32):
            native = model.resources("native", density)
            shared = model.resources("lsf", density)
            for field, suffix in (("cpu", "m"), ("memory", "Mi")):
                self.assertEqual(int(native["limits"][field].removesuffix(suffix)) * density,
                                 int(shared["limits"][field].removesuffix(suffix)))
            self.assertEqual(native["requests"], native["limits"])
        self.assertEqual(model.resources("native", 32)["limits"], {"cpu": "125m", "memory": "64Mi"})
        self.assertEqual(model.resources("client")["limits"], {"cpu": "2000m", "memory": "256Mi"})
        value = model.resources("native", 8)
        value["requests"]["cpu"] = "1m"
        self.assertEqual(value["limits"]["cpu"], "500m")

    def test_invalid_selectors_and_boolean_density_are_rejected(self):
        for arm, density in (("other", 1), ("native", True), ("native", 2), ("lsf", 0)):
            with self.subTest(arm=arm, density=density), self.assertRaises(EvidenceError):
                model.resources(arm, density)
        for profile in ("large", None, True):
            with self.assertRaises(EvidenceError):
                model.plan(profile, owner=OWNER)
        for owner in (None, True, "other_owner", "a" * 49):
            with self.subTest(owner=owner), self.assertRaises(EvidenceError):
                model.plan("smoke", owner=owner)

    def test_namespace_and_labels_bind_both_owner_and_run(self):
        value = model.namespace(OWNER, RUN)
        self.assertEqual(value["metadata"], {"name": OWNER + "-" + RUN,
            "labels": {model.OWNER_LABEL: OWNER, model.RUN_LABEL: RUN}})
        for owner, run in (("other_owner", RUN), (OWNER, "../run"), ("A", RUN),
                           ("a" * 48, "b" * 24), ("a-", RUN)):
            with self.subTest(owner=owner, run=run), self.assertRaises(EvidenceError):
                model.namespace(owner, run)

    def test_host_paths_are_canonical_owned_descendants(self):
        base = "/var/local/lsf112/" + OWNER + "/" + RUN
        self.assertEqual(model.host_path(OWNER, RUN), base)
        self.assertEqual(model.host_path(OWNER, RUN, "output/client-p0/plan.json"), base + "/output/client-p0/plan.json")
        for relative in ("", "/etc", "../foreign", "a/../b", "a//b", "a/", "a\\b", ".", "a/./b", "a\x00b"):
            with self.subTest(relative=relative), self.assertRaises(EvidenceError):
                model.host_path(OWNER, RUN, relative)

    def test_pod_mounts_cannot_escape_or_overlap(self):
        for changes in ({"output": "/etc"},
                        {"output": model.host_path(OWNER, "other", "output")},
                        {"output": model.host_path(OWNER, RUN)},
                        {"output": model.host_path(OWNER, RUN, "fixtures/child")},
                        {"data": model.host_path(OWNER, RUN, "output")},
                        {"data": None}):
            with self.subTest(changes=changes), self.assertRaises(EvidenceError):
                self.pod(**changes)
        for arm in ("native", "client"):
            with self.assertRaises(EvidenceError):
                self.pod(arm, data=model.host_path(OWNER, RUN, "data"))

    def test_fixed_security_and_tmp_do_not_invent_runtime_limits(self):
        value = self.pod()
        spec, container = value["spec"], value["spec"]["containers"][0]
        self.assertEqual(spec["nodeSelector"], {model.WORKER_LABEL: OWNER})
        self.assertEqual(model.plan("smoke", owner=OWNER)["node_selector"], spec["nodeSelector"])
        self.assertNotEqual(model.plan("smoke", owner="other-owner")["node_selector"], spec["nodeSelector"])
        self.assertNotIn("nodeName", spec)
        self.assertNotIn("runtimeClassName", spec)
        self.assertEqual(spec["restartPolicy"], "Never")
        self.assertEqual(spec["terminationGracePeriodSeconds"], 40)
        for field in ("automountServiceAccountToken", "hostNetwork", "hostPID", "hostIPC", "shareProcessNamespace"):
            self.assertIs(spec[field], False)
        self.assertEqual(container["securityContext"], {"readOnlyRootFilesystem": True,
            "allowPrivilegeEscalation": False, "privileged": False, "capabilities": {"drop": ["ALL"]}})
        self.assertEqual(set(container["resources"]["limits"]), {"cpu", "memory"})
        self.assertEqual(spec["volumes"][-1], {"name": "tmp", "emptyDir": {"medium": "Memory", "sizeLimit": "16Mi"}})
        self.assertTrue(all(row["hostPath"]["type"] == "Directory" for row in spec["volumes"][:-1]))
        self.assertIs(container["volumeMounts"][0]["readOnly"], True)
        self.assertIs(container["volumeMounts"][1]["readOnly"], False)
        self.assertEqual(model.plan("full", owner=OWNER)["pod_pids_limit"], 512)

    def test_app_has_only_one_startup_probe_and_preserves_entrypoint(self):
        for arm in ("lsf", "native"):
            value = self.pod(arm)["spec"]["containers"][0]
            self.assertEqual(value["name"], arm)
            self.assertEqual(value["args"], ["--output", "/output"])
            self.assertNotIn("command", value)
            self.assertEqual(value["imagePullPolicy"], "Never")
            self.assertEqual(value["startupProbe"], {"tcpSocket": {"port": 7070}, "initialDelaySeconds": 0,
                "periodSeconds": 1, "timeoutSeconds": 1, "failureThreshold": 120, "successThreshold": 1})
            self.assertNotIn("readinessProbe", value)
            self.assertNotIn("livenessProbe", value)
            self.assertIs(value["stdin"], False)

    def test_client_is_attachable_without_probe_or_app_port(self):
        value = self.pod("client")["spec"]["containers"][0]
        self.assertEqual(value["name"], "client")
        self.assertIs(value["stdin"], True)
        self.assertIs(value["stdinOnce"], False)
        self.assertIs(value["tty"], False)
        for key in ("startupProbe", "readinessProbe", "livenessProbe", "ports"):
            self.assertNotIn(key, value)

    def test_bounded_arguments_and_original_role_image_tags(self):
        for image in ("debian:latest", "lsf111-images-fc45a33903fb46eea767:native", "sha256:" + "a" * 64):
            with self.subTest(image=image), self.assertRaises(EvidenceError):
                self.pod(image=image)
        for command in ([], [""], ["hello\nworld"], ["a" * 4097], ["a"] * 33, "--output"):
            with self.subTest(command=str(command)[:40]), self.assertRaises(EvidenceError):
                self.pod(command=command)

    def test_every_service_selects_the_exact_pod_and_logical_service(self):
        for density in (1, 8, 32):
            for arm in ("lsf", "native"):
                values = model.services(owner=OWNER, run_id=RUN, pair=2, group=4, arm=arm, density=density)
                self.assertEqual(len(values), density)
                selected = set()
                for index, value in enumerate(values):
                    self.assertEqual(value["metadata"]["name"], f"p2-g4-s{index}")
                    self.assertEqual(value["metadata"]["annotations"]["latent.benchmark.service"], docker.SERVICES[index])
                    role = model.application_role(2, 4, arm, index if arm == "native" else 0)
                    selector = value["spec"]["selector"]
                    self.assertEqual(selector, model.labels(OWNER, RUN, role))
                    selected.add(selector[model.ROLE_LABEL])
                    self.assertEqual(value["spec"]["type"], "ClusterIP")
                    self.assertEqual(value["spec"]["sessionAffinity"], "None")
                    self.assertIs(value["spec"]["publishNotReadyAddresses"], False)
                    self.assertEqual(value["spec"]["ports"], [{"name": "grpc", "port": 7070, "targetPort": 7070, "protocol": "TCP"}])
                    self.assertNotIn("clusterIP", value["spec"])
                    self.assertNotIn("externalIPs", value["spec"])
                self.assertEqual(len(selected), 1 if arm == "lsf" else density)

    def test_role_and_service_indices_are_strict_finite_values(self):
        for args in ((True, 0, 0), (7, 0, 0), (0, 6, 0), (0, 0, 32)):
            with self.subTest(args=args), self.assertRaises(EvidenceError):
                model.service_name(*args)
        with self.assertRaises(EvidenceError):
            model.application_role(0, 0, "lsf", 1)
        with self.assertRaises(EvidenceError):
            model.service(owner=OWNER, run_id=RUN, pair=0, group=0, arm="native", density=8, index=8)
        with self.assertRaises(EvidenceError):
            model.services(owner=OWNER, run_id=RUN, pair=0, group=0, arm="native", density=True)


if __name__ == "__main__":
    unittest.main()

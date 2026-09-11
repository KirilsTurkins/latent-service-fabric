"""Synthetic kernel/provider DTOs exercise replay; they are not measured evidence."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.optimization_docker import model as docker_model
from tools.optimization_evidence.common import EvidenceError
from tools.optimization_kubernetes import model, resources
from tools.tests.test_optimization_docker_resources import CONTAINER_ID, Fixture, raw

UID = "11111111-2222-3333-4444-555555555555"
WORKER = {"name": "unit-worker", "uid": "unit-node-uid", "container_id": "c" * 64}


class KubernetesFixture:
    def __init__(self, directory, arm="native", density=32):
        self.fixture = Fixture(directory, arm=arm, density=density)
        controls = docker_model.resources(arm, density)
        root = "/var/local/lsf112/unit/run/"
        self.pod_ready = model.pod("lsf111-images-" + "a" * 20 + ":" + arm, ["--app", arm], arm=arm,
            density=density, owner="unit", run_id="run", role="unit-app", fixtures=root + "fixtures",
            output=root + "output", data=root + "data" if arm == "lsf" else None)
        self.pod_ready["metadata"]["uid"] = UID
        self.pod_ready["spec"]["nodeName"] = WORKER["name"]
        status = {"name": arm, "restartCount": 0, "ready": True, "started": True, "lastState": {},
                  "containerID": "containerd://" + CONTAINER_ID, "imageID": "sha256:" + "b" * 64,
                  "state": {"running": {"startedAt": "2026-09-11T00:00:00Z"}}}
        self.pod_ready["status"] = {"phase": "Running", "containerStatuses": [status]}
        self.pod_final = deepcopy(self.pod_ready)
        self.pod_final["status"].update(phase="Succeeded")
        self.pod_final["status"]["containerStatuses"][0].update(ready=False, started=False,
            state={"terminated": {"exitCode": 0, "signal": 0, "reason": "Completed",
                                  "startedAt": "2026-09-11T00:00:00Z", "finishedAt": "2026-09-11T00:00:01Z"}})
        pod_component = "kubepods-pod" + UID.replace("-", "_") + ".slice"
        leaf = "/sys/fs/cgroup/kubepods.slice/" + pod_component + "/cri-containerd-" + CONTAINER_ID + ".scope"
        membership = "0::" + leaf.removeprefix("/sys/fs/cgroup") + "\n"
        spec = {"root": {"readonly": True}, "process": {"args": ["/opt/lsf/optimization-container", "--app", arm],
                "noNewPrivileges": True, "capabilities": {"bounding": [], "effective": [], "permitted": []}},
                "linux": {"cgroupsPath": pod_component + ":cri-containerd:" + CONTAINER_ID,
                          "resources": {"cpu": {"quota": controls["cpu_quota"], "period": controls["cpu_period"]},
                                        "memory": {"limit": controls["memory"]}}}}
        self.cri_ready = {"status": {"id": CONTAINER_ID, "state": "CONTAINER_RUNNING",
            "metadata": {"name": arm, "attempt": 0}, "createdAt": "1", "startedAt": "2", "finishedAt": "0",
            "imageRef": "sha256:" + "d" * 64,
            "labels": {"io.kubernetes.pod." + key: self.pod_ready["metadata"][key] for key in ("name", "namespace", "uid")}},
            "info": {"runtimeType": "io.containerd.runc.v2", "pid": 500, "removing": False,
                     "sandboxID": "e" * 64, "runtimeSpec": spec}}
        self.cri_final = deepcopy(self.cri_ready)
        self.cri_final["status"].update(state="CONTAINER_EXITED", finishedAt="3", exitCode=0, reason="Completed")
        self.cri_final["info"]["pid"] = 0
        self.observations = []
        for index, event in enumerate(self.fixture.events[2:-1], 1):
            event["detail"]["cgroup"]["files"]["pids.max"] = raw("max\n")
            node_processes = {}
            for role, pid, parent in (("wrapper", 500, 200), ("child", 507, 500)):
                mounted = event["detail"][role]
                proc_stat = f"{pid} (synthetic) " + " ".join(["S", str(parent)] + ["0"] * 17
                                                            + [mounted["start_time_ticks"]]) + "\n"
                node_processes[role] = {"pid": pid, "stat": raw(proc_stat), "stat_after": raw(proc_stat),
                    "status": raw(f"NSpid:\t{pid}\t{mounted['pid']}\n"),
                    "limits": raw("Max open files            1048576              1048576              files\n"),
                    "cgroup": raw(membership), "namespaces": deepcopy(mounted["namespaces"]),
                    "mountinfo": raw("1 0 0:1 / /tmp rw,nosuid,nodev - tmpfs tmpfs rw,size=16384k\n")}
            ancestors = []
            path = resources.PurePosixPath(leaf)
            while path.is_relative_to(resources.ROOT):
                values = {"cpu.max": "max 100000", "memory.max": "max", "memory.swap.max": "max",
                          "pids.max": "max", "pids.current": "6"}
                if not ancestors:
                    values.update({"cpu.max": f"{controls['cpu_quota']} {controls['cpu_period']}",
                                   "memory.max": str(controls["memory"]), "memory.swap.max": "0"})
                elif path.name == pod_component:
                    values["pids.max"] = "512"
                ancestors.append({"path": str(path), "files": {key: raw(value + "\n") for key, value in values.items()}})
                path = path.parent
            self.observations.append({"snapshot_index": index, "started_nanos": str(index * 1000),
                                      "finished_nanos": str(index * 1000 + 50), **node_processes, "cgroups": ancestors})
        self.fixture.write()

    def validate(self):
        return resources.validate(self.fixture.directory, arm=self.fixture.arm, density=self.fixture.density,
            pod_ready=self.pod_ready, pod_final=self.pod_final, cri_ready=self.cri_ready, cri_final=self.cri_final,
            worker=WORKER, observations=self.observations, expected_connections=2)


class KubernetesResources(unittest.TestCase):
    def test_actual_provider_facts_bind_namespace_and_ancestor_limits(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = KubernetesFixture(Path(directory))
            result = fixture.validate()
            self.assertEqual(result["identity"]["host_wrapper_pid_at_ready"], 500)
            self.assertEqual(result["identity"]["image_id"], "sha256:" + "b" * 64)
            self.assertEqual(result["identity"]["cri_image_ref"], "sha256:" + "d" * 64)
            row = result["snapshots"][0]
            self.assertEqual(row["cgroup"]["limits"]["pids.max"], "max")
            self.assertEqual(row["provider"]["cgroup"]["effective_pids_max"], "512")
            self.assertEqual(row["provider"]["wrapper"]["nofile"], {"soft": "1048576", "hard": "1048576"})
            self.assertEqual(row["provider"]["child"]["namespace_pids"], [507, 7])
            self.assertNotIn("nofile_soft", result["effective_controls"])
            self.assertTrue(result["shutdown"]["child_reaped"])

    def test_equivalent_api_quantities_keep_exact_resource_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = KubernetesFixture(Path(directory), arm="lsf", density=8)
            for pod in (fixture.pod_ready, fixture.pod_final):
                pod["spec"]["containers"][0]["resources"] = {name: {"cpu": "4", "memory": "2Gi"}
                                                             for name in ("limits", "requests")}
            self.assertEqual(fixture.validate()["effective_controls"]["memory"], 2 * 1024**3)
            for pod in (fixture.pod_ready, fixture.pod_final):
                pod["spec"]["containers"][0]["resources"]["limits"]["cpu"] = "4.0000000000000000000000000001"
            with self.assertRaisesRegex(EvidenceError, "pod-resource"):
                fixture.validate()

    def test_optional_process_fields_remain_unavailable_not_docker_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = KubernetesFixture(Path(directory))
            fixture.observations[0]["child"].update(limits=raw(), mountinfo=raw())
            child = fixture.validate()["snapshots"][0]["provider"]["child"]
            self.assertIsNone(child["nofile"])
            self.assertIsNone(child["tmp"])
            self.assertEqual(child["nofile_unavailable_reason"], "open-failed")

    def test_pod_cri_runtime_identity_and_cleanup_mutations_reject(self):
        self.reject((lambda f: f.pod_final["metadata"].update(uid="foreign"),
                     lambda f: f.pod_final["status"]["containerStatuses"][0]["state"]["terminated"].update(exitCode=137),
                     lambda f: f.cri_final["status"].update(id="f" * 64),
                     lambda f: f.cri_ready["info"].update(runtimeType="io.containerd.kata.v2"),
                     lambda f: f.cri_final["status"].update(reason="OOMKilled"),
                     lambda f: f.pod_ready["spec"]["containers"][0]["resources"]["limits"].update(cpu="124m"),
                     lambda f: f.cri_ready["info"]["runtimeSpec"]["linux"]["resources"]["memory"].update(limit=1)))

    def test_node_process_cannot_borrow_mounted_pid_or_namespace(self):
        self.reject((lambda f: f.observations[0]["wrapper"].update(pid=501),
                     lambda f: f.observations[0]["child"].update(status=raw("NSpid:\t507\t9\n")),
                     lambda f: f.observations[0]["child"]["namespaces"].update(pid=raw("pid:[999]")),
                     lambda f: f.observations[0]["child"].update(stat_after=raw("507 (x) S 500 " + "0 " * 17 + "999\n")),
                     lambda f: f.observations[0]["child"].update(cgroup=raw("0::/foreign\n"))))

    def test_effective_limits_require_complete_matching_ancestry(self):
        self.reject((lambda f: f.observations[0]["cgroups"].pop(1),
                     lambda f: f.observations[0]["cgroups"].pop(),
                     lambda f: f.observations[0]["cgroups"][1]["files"].update({"pids.max": raw("max\n")}),
                     lambda f: f.observations[0]["cgroups"][0]["files"].update({"memory.swap.max": raw("1\n")}),
                     lambda f: f.observations[0]["cgroups"][0]["files"].update({"cpu.max": raw("12000 100000\n")}),
                     lambda f: f.observations[0]["cgroups"][2]["files"].update({"memory.max": raw("1\n")}),
                     lambda f: f.observations[0]["cgroups"][1]["files"].update({"cpu.max": raw()})))

    def test_bounded_observation_population_and_controller_clock_are_independent(self):
        self.reject((lambda f: f.observations.pop(),
                     lambda f: f.observations.append(deepcopy(f.observations[0])),
                     lambda f: f.observations[1].update(started_nanos="1"),
                     lambda f: f.observations[0].update(snapshot_index=True),
                     lambda f: f.observations[0]["wrapper"].update(limits=raw("x" * (65536 + 1)))))

    def test_root_missing_limit_files_are_not_synthetic_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = KubernetesFixture(Path(directory))
            for row in fixture.observations:
                row["cgroups"][-1]["files"] = {key: raw() for key in resources.ANCESTOR_FILES}
            last = fixture.validate()["snapshots"][0]["provider"]["cgroup"]["ancestors"][-1]
            self.assertIsNone(last["limits"]["pids.max"])
            self.assertEqual(last["files"]["pids.max"]["unavailable_reason"], "open-failed")

    def reject(self, mutations):
        for mutation in mutations:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                fixture = KubernetesFixture(Path(directory))
                mutation(fixture)
                with self.assertRaises(EvidenceError):
                    fixture.validate()


if __name__ == "__main__":
    unittest.main()

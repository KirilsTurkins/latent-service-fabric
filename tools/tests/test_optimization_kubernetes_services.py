"""Synthetic API topology negatives, never a qualifying workload fixture."""
import copy
import unittest

from tools.optimization_evidence.common import EvidenceError
from tools.optimization_kubernetes import model, services

OWNER = "lsf-112-abcdef012345"
RUN = "smoke-01"
WORKER = OWNER + "-worker"
STAMP = "2026-09-11T12:00:00Z"


def uid(number):
    return f"{number:08x}-1111-4111-8111-000000000000"


def metadata(value, number):
    value["metadata"].update(uid=uid(number), resourceVersion=str(1000 + number), creationTimestamp=STAMP)


def fixture(arm="lsf", density=1):
    pod_rows = []
    for index in range(1 if arm == "lsf" else density):
        role = model.application_role(0, 0, arm, index)
        pod = model.pod("lsf111-images-fc45a33903fb46eea767:" + arm, ["--output", "/output"],
            arm=arm, density=density, owner=OWNER, run_id=RUN, role=role,
            fixtures=model.host_path(OWNER, RUN, "fixtures"), output=model.host_path(OWNER, RUN, "output/" + role),
            data=model.host_path(OWNER, RUN, "data/" + role) if arm == "lsf" else None)
        metadata(pod, index + 1)
        pod["spec"]["nodeName"] = WORKER
        ip = "10.244.1." + str(index + 2)
        pod["status"] = {"phase": "Running", "podIP": ip, "podIPs": [{"ip": ip}], "startTime": STAMP,
            "conditions": [{"type": name, "status": "True", "lastTransitionTime": STAMP}
                           for name in ("PodScheduled", "Initialized", "ContainersReady", "Ready")],
            "containerStatuses": [{"name": arm, "restartCount": 0, "lastState": {}, "ready": True, "started": True,
                                   "state": {"running": {"startedAt": STAMP}},
                                   "containerID": "containerd://" + f"{index + 1:064x}",
                                   "imageID": "docker.io/library/retained@sha256:" + "a" * 64}]}
        pod_rows.append(pod)
    service_rows = model.services(owner=OWNER, run_id=RUN, pair=0, group=0, arm=arm, density=density)
    slices = []
    for index, service in enumerate(service_rows):
        metadata(service, 100 + index)
        ip = "10.96.0." + str(index + 10)
        service["spec"].update(clusterIP=ip, clusterIPs=[ip])
        pod = pod_rows[0 if arm == "lsf" else index]
        name = service["metadata"]["name"]
        value = {"apiVersion": "discovery.k8s.io/v1", "kind": "EndpointSlice", "addressType": "IPv4",
            "metadata": {"name": name + "-abcde", "namespace": model.namespace_name(OWNER, RUN),
                "labels": {"kubernetes.io/service-name": name,
                           "endpointslice.kubernetes.io/managed-by": "endpointslice-controller.k8s.io"},
                "ownerReferences": [{"apiVersion": "v1", "kind": "Service", "name": name,
                                     "uid": service["metadata"]["uid"], "controller": True, "blockOwnerDeletion": True}]},
            "ports": [{"name": "grpc", "protocol": "TCP", "port": 7070}],
            "endpoints": [{"addresses": [pod["status"]["podIP"]], "nodeName": WORKER,
                           "conditions": {"ready": True, "serving": True, "terminating": False},
                           "targetRef": {"apiVersion": "v1", "kind": "Pod", "namespace": model.namespace_name(OWNER, RUN),
                                         "name": pod["metadata"]["name"], "uid": pod["metadata"]["uid"]}}]}
        metadata(value, 200 + index)
        slices.append(value)
    return service_rows, slices, pod_rows


def replay(rows, arm="lsf", density=1):
    return services.graph(*rows, owner=OWNER, run_id=RUN, pair=0, group=0, arm=arm, density=density, worker_name=WORKER)


class KubernetesServiceGraphTests(unittest.TestCase):
    def test_all_densities_bind_service_addresses_to_expected_pod_owners(self):
        for density in (1, 8, 32):
            for arm in ("lsf", "native"):
                with self.subTest(arm=arm, density=density):
                    rows = fixture(arm, density)
                    before = copy.deepcopy(rows)
                    result = replay(rows, arm, density)
                    self.assertEqual(rows, before)
                    self.assertEqual(len(result["targets"]), density)
                    self.assertEqual(len(result["pods"]), 1 if arm == "lsf" else density)
                    self.assertEqual(sum(map(len, result["service_endpoints"].values())), density)
                    for index, target in enumerate(result["targets"]):
                        self.assertEqual(target["service"], model.SERVICES[index])
                        self.assertEqual(target["endpoint"], "http://10.96.0." + str(index + 10) + ":7070")
                        self.assertNotEqual(target["cluster_ip"], target["pod_ip"])
                        self.assertNotIn("app_process_id", target)
                    reversed_rows = tuple(list(reversed(values)) for values in rows)
                    self.assertEqual(replay(reversed_rows, arm, density), result)

    def test_declared_api_defaults_can_be_omitted_without_relaxing_security(self):
        rows = fixture()
        spec = rows[2][0]["spec"]
        for key in ("hostNetwork", "hostPID", "hostIPC"):
            del spec[key]
        container = spec["containers"][0]
        for key in ("stdin", "stdinOnce", "tty"):
            del container[key]
        del container["startupProbe"]["initialDelaySeconds"]
        for mount in container["volumeMounts"]:
            if mount["readOnly"] is False:
                del mount["readOnly"]
        del rows[0][0]["spec"]["publishNotReadyAddresses"]
        # Admitted quantities may be normalized; the resource replay owns their value proof.
        container["resources"] = {"requests": {"cpu": "4", "memory": "2Gi"},
                                  "limits": {"cpu": "4", "memory": "2Gi"}}
        rows[0][0]["metadata"]["managedFields"] = [{"manager": "kube-apiserver"}]
        rows[0][0]["status"] = {"loadBalancer": {}}
        replay(rows)
        del container["securityContext"]["allowPrivilegeEscalation"]
        with self.assertRaises(EvidenceError):
            replay(rows)

    def test_every_matching_slice_is_retained_including_empty_owned_slice(self):
        rows = fixture()
        empty = copy.deepcopy(rows[1][0])
        empty["metadata"]["name"] += "-empty"
        metadata(empty, 500)
        empty["endpoints"] = []
        rows[1].append(empty)
        result = replay(rows)
        self.assertEqual(len(result["slices"]), 2)
        self.assertEqual(len(result["targets"][0]["all_slice_uids"]), 2)
        empty["endpoints"] = copy.deepcopy(rows[1][0]["endpoints"])
        with self.assertRaises(EvidenceError):
            replay(rows)

    def test_service_controls_and_exact_selector_are_required(self):
        mutations = [
            lambda row: row["spec"].update(type="NodePort"),
            lambda row: row["spec"].update(sessionAffinity="ClientIP"),
            lambda row: row["spec"].update(publishNotReadyAddresses=True),
            lambda row: row["spec"]["ports"][0].update(port=True),
            lambda row: row["spec"]["ports"][0].update(targetPort=7071),
            lambda row: row["spec"]["selector"].update(extra="unbound"),
            lambda row: row["spec"]["selector"].update({model.RUN_LABEL: "other"}),
            lambda row: row["metadata"]["annotations"].update({"latent.benchmark.service": "foreign/service"}),
            lambda row: row["spec"].update(clusterIP="None"),
            lambda row: row["spec"].update(clusterIPs=["10.96.0.99"]),
            lambda row: row["spec"].update(externalIPs=["192.0.2.1"]),
            lambda row: row["metadata"].update(namespace="foreign"),
            lambda row: row["metadata"].update(deletionTimestamp=STAMP),
        ]
        for index, change in enumerate(mutations):
            rows = fixture()
            change(rows[0][0])
            with self.subTest(index=index), self.assertRaises(EvidenceError):
                replay(rows)

    def test_missing_extra_or_reused_objects_reject(self):
        rows = fixture("native", 8)
        for item in (0, 1, 2):
            for extra in (False, True):
                changed = copy.deepcopy(rows)
                if extra:
                    changed[item].append(copy.deepcopy(changed[item][0]))
                else:
                    changed[item].pop()
                with self.subTest(item=item, extra=extra), self.assertRaises(EvidenceError):
                    replay(changed, "native", 8)
        for kind in (0, 1, 2):
            changed = copy.deepcopy(rows)
            changed[kind][1]["metadata"]["uid"] = changed[kind][0]["metadata"]["uid"]
            with self.subTest(kind=kind), self.assertRaises(EvidenceError):
                replay(changed, "native", 8)

    def test_endpoint_ownership_and_stale_pod_references_reject(self):
        mutations = [
            lambda row: row["metadata"]["ownerReferences"][0].update(uid=uid(999)),
            lambda row: row["metadata"]["ownerReferences"][0].update(controller=False),
            lambda row: row["metadata"]["labels"].update({"kubernetes.io/service-name": "foreign"}),
            lambda row: row["metadata"]["labels"].update({model.OWNER_LABEL: "foreign"}),
            lambda row: row["metadata"].update(deletionTimestamp=STAMP),
            lambda row: row["endpoints"][0]["targetRef"].update(uid=uid(998)),
            lambda row: row["endpoints"][0]["targetRef"].update(name="foreign-pod"),
            lambda row: row["endpoints"][0]["targetRef"].update(namespace="foreign"),
            lambda row: row["endpoints"][0].update(nodeName="foreign-worker"),
            lambda row: row["endpoints"][0].update(addresses=["10.244.1.99"]),
            lambda row: row["endpoints"][0]["addresses"].append("10.244.1.99"),
            lambda row: row["endpoints"].append(copy.deepcopy(row["endpoints"][0])),
            lambda row: row["ports"][0].update(port=7071),
        ]
        for index, change in enumerate(mutations):
            rows = fixture()
            change(rows[1][0])
            with self.subTest(index=index), self.assertRaises(EvidenceError):
                replay(rows)

    def test_unknown_or_unready_endpoint_conditions_cannot_qualify(self):
        for key, value in (("ready", False), ("serving", None), ("terminating", True),
                           ("ready", "true"), ("terminating", 0)):
            rows = fixture()
            rows[1][0]["endpoints"][0]["conditions"][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(EvidenceError):
                replay(rows)
        rows = fixture()
        del rows[1][0]["endpoints"][0]["conditions"]["terminating"]
        with self.assertRaises(EvidenceError):
            replay(rows)

    def test_pod_status_restart_placement_and_control_failures_reject(self):
        mutations = [
            lambda row: row["spec"].update(nodeName="foreign-worker"),
            lambda row: row["spec"].update(hostNetwork=True),
            lambda row: row["spec"].update(runtimeClassName="changed"),
            lambda row: row["spec"]["containers"][0]["securityContext"].update(allowPrivilegeEscalation=True),
            lambda row: row["spec"]["containers"][0].update(readinessProbe={"tcpSocket": {"port": 7070}}),
            lambda row: row["status"].update(phase="Failed"),
            lambda row: row["status"]["containerStatuses"][0].update(restartCount=1),
            lambda row: row["status"]["containerStatuses"][0].update(restartCount=False),
            lambda row: row["status"]["containerStatuses"][0].update(started=False),
            lambda row: row["status"]["containerStatuses"][0].update(lastState={"terminated": {"exitCode": 1}}),
            lambda row: row["status"]["containerStatuses"][0].update(containerID="containerd://short"),
            lambda row: row["status"]["containerStatuses"][0].update(imageID=""),
            lambda row: row["status"]["conditions"][0].update(status="False"),
            lambda row: row["status"]["conditions"].append(copy.deepcopy(row["status"]["conditions"][0])),
            lambda row: row["spec"]["volumes"][0]["hostPath"].update(path="/etc"),
        ]
        for index, change in enumerate(mutations):
            rows = fixture()
            change(rows[2][0])
            with self.subTest(index=index), self.assertRaises(EvidenceError):
                replay(rows)

    def test_raw_wall_timestamps_are_preserved_without_cross_clock_ordering(self):
        rows = fixture()
        row = rows[2][0]
        row["status"]["conditions"][-1]["lastTransitionTime"] = "2026-09-11T11:59:59.123456789Z"
        row["status"]["containerStatuses"][0]["state"]["running"]["startedAt"] = "2026-09-11T14:00:00+02:00"
        result = replay(rows)
        stamps = next(iter(result["pods"].values()))["timestamps"]
        self.assertEqual(stamps["ready_at"], "2026-09-11T11:59:59.123456789Z")
        self.assertEqual(stamps["container_started_at"], "2026-09-11T14:00:00+02:00")
        self.assertEqual(result["timestamp_scope"], "original-api-wall-times-no-cross-clock-subtraction")
        row["metadata"]["creationTimestamp"] = "not-a-time"
        with self.assertRaises(EvidenceError):
            replay(rows)


if __name__ == "__main__":
    unittest.main()

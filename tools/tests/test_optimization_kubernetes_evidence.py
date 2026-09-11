"""Synthetic component associations; no Kubernetes or workload success is mocked."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.optimization_evidence.common import EvidenceError, canonical, sha256
from tools.optimization_kubernetes import collect, evidence, model, services

CID = "a" * 64
CONFIG, MANIFEST, INDEX = ("sha256:" + digit * 64 for digit in "bcd")


def encoded(value):
    return canonical(value) + b"\n"


def images():
    return {"images": {"client": {"tag": "lsf111-images-" + "a" * 20 + ":client",
        "original_docker_image_id": MANIFEST, "imported": {"config_digest": CONFIG,
            "manifest_digest": MANIFEST, "status_id": CONFIG, "archive_index_digest": INDEX}}}}


def image_cri(bootstrap, reference=MANIFEST):
    return {"status": {"imageRef": reference}, "info": {"config": {"image": {
        "image": CONFIG, "user_specified_image": bootstrap["images"]["client"]["tag"]}}}}


def client_pods():
    manifest = model.pod(images()["images"]["client"]["tag"], ["--session", "/output/plan.json", "--output", "/output"],
        arm="client", density=1, owner="unit", run_id="run", role="client-p0",
        fixtures=model.host_path("unit", "run", "fixtures"), output=model.host_path("unit", "run", "clients/0"))
    ready = deepcopy(manifest)
    ready["metadata"]["uid"] = "unit-uid"
    ready["spec"]["nodeName"] = "unit-worker"
    ready["status"] = {"phase": "Running", "containerStatuses": [{"name": "client", "restartCount": 0,
        "containerID": "containerd://" + CID, "imageID": CONFIG,
        "state": {"running": {"startedAt": "2026-09-11T00:00:00Z"}}}]}
    final = deepcopy(ready)
    final["status"]["phase"] = "Succeeded"
    final["status"]["containerStatuses"][0]["state"] = {"terminated": {"startedAt": "2026-09-11T00:00:00Z",
        "exitCode": 0, "reason": "Completed", "signal": 0}}
    return manifest, ready, final


def endpoint_slice(service, service_uid):
    return {"apiVersion": "discovery.k8s.io/v1", "kind": "EndpointSlice", "metadata": {
        "name": service + "-slice", "uid": service + "-slice-uid", "namespace": "unit-run",
        "labels": {"kubernetes.io/service-name": service,
                   "endpointslice.kubernetes.io/managed-by": "endpointslice-controller.k8s.io"},
        "ownerReferences": [{"apiVersion": "v1", "kind": "Service", "name": service,
                             "uid": service_uid, "controller": True}]},
        "endpoints": [{"conditions": {"ready": True}}]}


def attachment(root):
    directory = root / "clients/0"
    directory.mkdir(parents=True)
    lines = [encoded({"event": "ready"}), encoded({"event": "complete"})]
    commands = [{"line": '{"command":"finish"}\n', "sent_nanos": "20"}]
    actual = {"stdin": commands[0]["line"].encode(), "stdout": lines[1], "stderr": b""}
    (directory / "attach-stdout.ndjson").write_bytes(actual["stdout"])
    (directory / "attach-stderr.bin").write_bytes(actual["stderr"])
    receipt = {"argv": ["/owned/kubectl", "attach"], "process_id": 120, "start_time_ticks": "99",
        "started_nanos": "10", "finished_nanos": "30", "exit_code": 0, "reaped": True,
        "output_closed": True, "forced_kill": False, "failure": None, "process_group_gone": True,
        "descendant_reaps": [], "subreaper": {"previous": 0, "enabled": True, "restored": True},
        "streams": {key: {"bytes": str(len(data)), "sha256": sha256(data)} for key, data in actual.items()}}
    (directory / "attachment.json").write_bytes(encoded(receipt))
    return {"parent_directory": "clients/0", "commands": commands, "attach": receipt}, lines


class KubernetesEvidenceTests(unittest.TestCase):
    def test_embedded_slice_type_comes_only_from_validated_list(self):
        row = endpoint_slice("current", "current-service-uid")
        del row["apiVersion"]
        del row["kind"]
        known = {"current": "current-service-uid"}
        envelope = {"apiVersion": "discovery.k8s.io/v1", "kind": "EndpointSliceList", "metadata": {}, "items": [row]}
        items = services.list_items(envelope, "EndpointSlice")
        for select in (collect._current_slices, evidence._current_slices):
            with self.assertRaises(EvidenceError):
                select(items, known, known, owner="unit", run_id="run")
            self.assertEqual(select(items, known, known, owner="unit", run_id="run", embedded_items=True), [row])
        self.assertNotIn("apiVersion", row)
        self.assertNotIn("kind", row)

    def test_cleanup_embedded_pod_keeps_namespace_and_role_owner_checks(self):
        campaign = object.__new__(collect.Campaign)
        campaign.owner, campaign.run_id, campaign.namespace = "unit", "run", "unit-run"
        row = {"metadata": {"name": "client-p0", "namespace": "unit-run",
                            "labels": model.labels("unit", "run", "client-p0")}}
        envelope = {"apiVersion": "v1", "kind": "PodList", "metadata": {}, "items": [row]}
        items = services.list_items(envelope, "Pod")
        with self.assertRaises(EvidenceError):
            campaign._namespace_pod(row)
        campaign._namespace_pod(items[0], embedded=True)
        row["metadata"]["namespace"] = "foreign"
        with self.assertRaises(EvidenceError):
            campaign._namespace_pod(items[0], embedded=True)

    def test_prior_ready_slice_cannot_trigger_next_same_density_group(self):
        original = [endpoint_slice("previous", "previous-service-uid")]
        before = deepcopy(original)
        known = {"previous": "previous-service-uid", "current": "current-service-uid"}
        for select in (collect._current_slices, evidence._current_slices):
            self.assertEqual(select(original, {"current": known["current"]}, known, owner="unit", run_id="run"), [])
        self.assertEqual(original, before)

    def test_current_and_known_prior_slices_preserve_full_list_and_order(self):
        original = [endpoint_slice("previous", "previous-service-uid"), endpoint_slice("current", "current-service-uid")]
        before = deepcopy(original)
        known = {"previous": "previous-service-uid", "current": "current-service-uid"}
        for select in (collect._current_slices, evidence._current_slices):
            selected = select(original, {"current": known["current"]}, known, owner="unit", run_id="run")
            self.assertEqual(selected, [original[1]])
            self.assertIs(selected[0], original[1])
        self.assertEqual(original, before)

    def test_unknown_or_replaced_prior_slice_owner_is_not_ignored(self):
        for mutation in (lambda row: row["metadata"]["ownerReferences"][0].update(uid="foreign-service-uid"),
                         lambda row: row["metadata"]["ownerReferences"][0].update(name="unknown"),
                         lambda row: row["metadata"]["labels"].update({"kubernetes.io/service-name": "unknown"}),
                         lambda row: row["metadata"]["labels"].update({model.OWNER_LABEL: "foreign"}),
                         lambda row: row["metadata"].update(namespace="foreign"),
                         lambda row: row["metadata"].update(ownerReferences=[])):
            for select in (collect._current_slices, evidence._current_slices):
                original = endpoint_slice("previous", "previous-service-uid")
                mutation(original)
                with self.subTest(mutation=mutation, select=select), self.assertRaises(EvidenceError):
                    select([original], {"current": "current-service-uid"},
                           {"current": "current-service-uid", "previous": "previous-service-uid"}, owner="unit", run_id="run")

    def test_slice_duplicate_and_namespace_population_bound_reject(self):
        original = endpoint_slice("current", "current-service-uid")
        for rows in ([original, deepcopy(original)], [deepcopy(original) for _ in range(129)]):
            for select in (collect._current_slices, evidence._current_slices):
                with self.subTest(select=select), self.assertRaises(EvidenceError):
                    select(rows, {"current": "current-service-uid"}, {"current": "current-service-uid"}, owner="unit", run_id="run")

    def test_selected_config_or_manifest_is_required_not_shared_index(self):
        bootstrap = images()
        pod = {"spec": {"containers": [{"image": bootstrap["images"]["client"]["tag"]}]},
               "status": {"containerStatuses": [{"imageID": CONFIG}]}}
        cri = image_cri(bootstrap)
        evidence._image(pod, cri, "client", bootstrap)
        for replacement in (INDEX, "sha256:" + "e" * 64):
            cri["status"]["imageRef"] = replacement
            with self.subTest(replacement=replacement), self.assertRaisesRegex(EvidenceError, "running-image"):
                evidence._image(pod, cri, "client", bootstrap)

    def test_image_repository_alias_is_closed(self):
        bootstrap = images()
        tag = bootstrap["images"]["client"]["tag"]
        pod = {"spec": {"containers": [{"image": tag}]}, "status": {"containerStatuses": [{"imageID": CONFIG}]}}
        cri = image_cri(bootstrap, "docker-pullable://docker.io/library/" + tag + "@" + MANIFEST)
        evidence._image(pod, cri, "client", bootstrap)
        cri["status"]["imageRef"] = "foreign/image@" + MANIFEST
        with self.assertRaisesRegex(EvidenceError, "image-repository"):
            evidence._image(pod, cri, "client", bootstrap)

    def test_recorded_shared_index_alias_requires_actual_per_arm_config_selection(self):
        bootstrap = images()
        selected = bootstrap["images"]["client"]
        alias = "docker.io/library/import-unit@" + INDEX
        selected["imported"].update(repo_digest_scope="archive-index", repo_digests=[alias])
        pod = {"spec": {"containers": [{"image": selected["tag"]}]},
               "status": {"containerStatuses": [{"imageID": alias}]}}
        cri = image_cri(bootstrap, alias)
        evidence._image(pod, cri, "client", bootstrap)
        cri["info"]["config"]["image"]["image"] = "sha256:" + "e" * 64
        with self.assertRaisesRegex(EvidenceError, "cri-selected-image"):
            evidence._image(pod, cri, "client", bootstrap)
        cri = image_cri(bootstrap, alias)
        selected["imported"]["repo_digests"] = ["docker.io/library/other@" + INDEX]
        with self.assertRaises(EvidenceError):
            evidence._image(pod, cri, "client", bootstrap)

    def test_cri_stats_keep_two_clocks_and_explicit_missing_fields(self):
        value = {"stats": [{"attributes": {"id": CID}, "cpu": {"timestamp": "101", "usageCoreNanoSeconds": {"value": "0"}},
                             "memory": {"timestamp": 99, "workingSetBytes": {"value": 1200}}}]}
        actual = evidence._client_stats(value, CID)
        self.assertEqual((actual["cpu_timestamp_nanos"], actual["memory_timestamp_nanos"]), ("101", "99"))
        self.assertEqual(actual["cpu_usage_nanos"], "0")
        del value["stats"][0]["memory"]["workingSetBytes"]
        missing = evidence._client_stats(value, CID)
        self.assertIsNone(missing["memory_working_set_bytes"])
        self.assertEqual(missing["memory_working_set_bytes_unavailable_reason"], "cri-field-not-reported")

    def test_cri_stats_crossed_owner_duplicate_rows_and_boolean_reject(self):
        for value in ({"stats": [{"attributes": {"id": "f" * 64}}]}, {"stats": []},
                      {"stats": [{"attributes": {"id": CID}, "cpu": {"timestamp": True}}]}):
            with self.subTest(value=value), self.assertRaises(EvidenceError):
                evidence._client_stats(value, CID)

    def test_client_actual_quantities_are_equivalent_without_docker_pid_defaults(self):
        manifest, ready, final = client_pods()
        for pod in (ready, final):
            pod["spec"]["containers"][0]["resources"] = {key: {"cpu": "2", "memory": "0.25Gi"}
                                                        for key in ("requests", "limits")}
        evidence._client_pods(ready, final, manifest, {"name": "unit-worker"})

    def test_client_pod_replacement_controls_and_unclean_exit_reject(self):
        for mutate in (lambda r, f: f["metadata"].update(uid="foreign"),
                       lambda r, f: r["spec"]["containers"][0].update(startupProbe=model.startup_probe()),
                       lambda r, f: f["status"]["containerStatuses"][0]["state"]["terminated"].update(exitCode=137),
                       lambda r, f: r["spec"]["containers"][0]["resources"]["limits"].update(cpu="1999m")):
            manifest, ready, final = client_pods()
            mutate(ready, final)
            with self.subTest(mutate=mutate), self.assertRaises(EvidenceError):
                evidence._client_pods(ready, final, manifest, {"name": "unit-worker"})

    def test_attach_hashes_original_consumed_output_and_cleanup(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            parent, lines = attachment(root)
            result = evidence._attachment(root, parent, parent["attach"]["argv"], lines)
            self.assertTrue(result["subreaper"]["restored"])
            self.assertEqual(result["streams"]["stdout"]["sha256"], sha256(lines[1]))

    def test_attach_missing_reap_forced_kill_or_stream_substitution_reject(self):
        for mutate in (lambda p: p["attach"].update(reaped=False), lambda p: p["attach"].update(forced_kill=True),
                       lambda p: p["attach"]["subreaper"].update(restored=False),
                       lambda p: p["attach"]["streams"]["stdout"].update(sha256=sha256(b"changed"))):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                parent, lines = attachment(root)
                mutate(parent)
                (root / "clients/0/attachment.json").write_bytes(encoded(parent["attach"]))
                with self.assertRaises(EvidenceError):
                    evidence._attachment(root, parent, parent["attach"]["argv"], lines)

    def test_attach_ready_ack_must_come_from_pod_log_not_attach(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            parent, lines = attachment(root)
            data = b"".join(lines)
            (root / "clients/0/attach-stdout.ndjson").write_bytes(data)
            parent["attach"]["streams"]["stdout"] = {"bytes": str(len(data)), "sha256": sha256(data)}
            with self.assertRaisesRegex(EvidenceError, "attach-original-output"):
                evidence._attachment(root, parent, parent["attach"]["argv"], lines)

    def test_tail_partial_reads_bind_every_event_to_actual_source_call(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            raw = root / "owner/raw"
            raw.mkdir(parents=True)
            lines = [encoded({"sequence": index}) for index in range(9)]
            original = b"".join(lines)
            (raw / "events.ndjson").write_bytes(original)
            chunks = [original[:3], original[3:]]
            rows, offset = [], 0
            for ordinal, chunk in enumerate(chunks):
                rows.append({"raw": {"ordinal": ordinal, "provider": "docker", "operation": "worker-exec",
                    "argv": ["tail", "-c", "+" + str(offset + 1), "/owned/events.ndjson"], "timeout_seconds": 20},
                    "stdout": chunk, "finished_nanos": str(ordinal + 10)})
                offset += len(chunk)
            replay = object.__new__(evidence.Replay)
            replay.root, replay.upper, replay.used, replay.journal = root, 100, set(), {"rows": rows}
            parent = {"raw_directory": "owner/raw", "remote_output": "/owned", "event_observations": [
                {"sequence": index, "observed_nanos": "20", "call": 1} for index in range(9)]}
            self.assertEqual(len(replay.events(parent)), 9)
            self.assertEqual(replay.used, {0, 1})
            parent["event_observations"][0]["call"] = 0
            with self.assertRaisesRegex(EvidenceError, "event-clock"):
                replay.events(parent)


if __name__ == "__main__":
    unittest.main()

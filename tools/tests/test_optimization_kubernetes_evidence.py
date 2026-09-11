"""Synthetic component associations; no Kubernetes or workload success is mocked."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.optimization_evidence.common import EvidenceError, canonical, sha256
from tools.optimization_kubernetes import evidence, model

CID = "a" * 64
CONFIG, MANIFEST, INDEX = ("sha256:" + digit * 64 for digit in "bcd")


def encoded(value):
    return canonical(value) + b"\n"


def images():
    return {"images": {"client": {"tag": "lsf111-images-" + "a" * 20 + ":client",
        "original_docker_image_id": MANIFEST, "imported": {"config_digest": CONFIG,
            "manifest_digest": MANIFEST, "status_id": CONFIG, "archive_index_digest": INDEX}}}}


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
    def test_selected_config_or_manifest_is_required_not_shared_index(self):
        bootstrap = images()
        pod = {"spec": {"containers": [{"image": bootstrap["images"]["client"]["tag"]}]},
               "status": {"containerStatuses": [{"imageID": CONFIG}]}}
        cri = {"status": {"imageRef": MANIFEST}}
        evidence._image(pod, cri, "client", bootstrap)
        for replacement in (INDEX, "sha256:" + "e" * 64):
            cri["status"]["imageRef"] = replacement
            with self.subTest(replacement=replacement), self.assertRaisesRegex(EvidenceError, "running-image"):
                evidence._image(pod, cri, "client", bootstrap)

    def test_image_repository_alias_is_closed(self):
        bootstrap = images()
        tag = bootstrap["images"]["client"]["tag"]
        pod = {"spec": {"containers": [{"image": tag}]}, "status": {"containerStatuses": [{"imageID": CONFIG}]}}
        cri = {"status": {"imageRef": "docker-pullable://docker.io/library/" + tag + "@" + MANIFEST}}
        evidence._image(pod, cri, "client", bootstrap)
        cri["status"]["imageRef"] = "foreign/image@" + MANIFEST
        with self.assertRaisesRegex(EvidenceError, "image-repository"):
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

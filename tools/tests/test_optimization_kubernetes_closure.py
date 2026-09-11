"""Bounded synthetic call-closure negatives; no Kubernetes/workload execution."""
import copy
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from tools.optimization_docker.owned import encoded
from tools.optimization_evidence.common import EvidenceError
from tools.optimization_kubernetes import closure, model

OWNER, RUN = "lsf-112-abcdef012345", "smoke-01"
NAMESPACE = model.namespace_name(OWNER, RUN)
UID = "11111111-1111-4111-8111-111111111111"


def pod(phase="Pending", *, ready=False):
    return {"kind": "Pod", "metadata": {"name": "client-p0", "namespace": NAMESPACE, "uid": UID,
        "labels": model.labels(OWNER, RUN, "client-p0")},
        "status": {"phase": phase, "containerStatuses": [{"restartCount": 0, "ready": ready, "started": ready,
            "state": {"terminated": {"exitCode": 0}} if phase == "Succeeded" else {"running": {}}}]}}


def api(index, response, *, absent=False, deletion=False):
    return {"raw": {"ordinal": index, "provider": "kubernetes", "method": "GET",
            "path": "/api/v1/namespaces/" + NAMESPACE + "/pods/client-p0", "status": 404 if absent else 200,
            "timeout_seconds": 15, "expected_statuses": [200, 404] if deletion else [200]},
            "response_json": response, "started_nanos": str(index * 100), "finished_nanos": str(index * 100 + 50)}


def base_suite():
    return {"owner": OWNER, "run_id": RUN, "profile": "smoke", "namespace": NAMESPACE,
            "started_nanos": "0", "finished_nanos": "10000000000"}


class KubernetesClosureTests(unittest.TestCase):
    def test_progress_preserves_original_framing_sequence_and_source_values(self):
        expected = [("created", {"uid": UID}, 10, 30), ("closed", {"count": 1}, 30, 50)]
        values = [{"ordinal": index, "kind": item[0], "observed_nanos": str(20 + index * 20), "value": item[1]}
                  for index, item in enumerate(expected)]
        with TemporaryDirectory() as temporary:
            path = Path(temporary) / "progress.ndjson"
            path.write_bytes(b"".join(map(encoded, values)))
            closure._progress(path, expected, 0, 100)
            for kind in ("duplicate", "missing", "wrong-value", "early", "boolean-ordinal", "whitespace"):
                changed = copy.deepcopy(values)
                if kind == "duplicate":
                    changed[1]["ordinal"] = 0
                elif kind == "missing":
                    changed.pop()
                elif kind == "wrong-value":
                    changed[1]["value"]["count"] = True
                elif kind == "early":
                    changed[1]["observed_nanos"] = "29"
                elif kind == "boolean-ordinal":
                    changed[0]["ordinal"] = False
                data = b"".join(map(encoded, changed))
                path.write_bytes(b" " + data if kind == "whitespace" else data)
                with self.subTest(kind=kind), self.assertRaises(EvidenceError):
                    closure._progress(path, expected, 0, 100)

    def test_ready_poll_is_consumed_only_until_first_success(self):
        parents = {"create": {"pod": pod()}}
        rows = [api(0, pod()), api(1, pod()), api(2, pod("Running", ready=True))]
        used = {0, 2}
        replay = closure.Closure(base_suite(), Path("."), {"rows": rows}, {}, used)
        replay._poll_window(parents, first=0, last=2, lower=50, phase="Running")
        self.assertEqual(used, {0, 1, 2})
        rows[1]["response_json"] = pod("Running", ready=True)
        with self.assertRaisesRegex(EvidenceError, "after-success"):
            replay._poll_window(parents, first=0, last=2, lower=50, phase="Running")

    def test_poll_rejects_crossed_uid_restarts_early_clock_and_wrong_endpoint(self):
        for kind in ("uid", "restart", "boolean-restart", "clock", "path", "expected-status"):
            rows = [api(0, pod()), api(1, pod("Running", ready=True))]
            if kind == "uid":
                rows[1]["response_json"]["metadata"]["uid"] = "replacement"
            elif kind in ("restart", "boolean-restart"):
                rows[1]["response_json"]["status"]["containerStatuses"][0]["restartCount"] = 1 if kind == "restart" else False
            elif kind == "clock":
                rows[1]["started_nanos"] = "1"
            elif kind == "path":
                rows[1]["raw"]["path"] += "-foreign"
            else:
                rows[1]["raw"]["expected_statuses"] = [200, 404]
            replay = closure.Closure(base_suite(), Path("."), {"rows": rows}, {}, {0})
            with self.subTest(kind=kind), self.assertRaises(EvidenceError):
                replay._poll_window({"create": {"pod": pod()}}, first=0, last=1, lower=50, phase="Running")

    def test_delete_poll_requires_owned_uid_then_final_absence(self):
        rows = [api(0, pod()), api(1, pod("Succeeded"), deletion=True),
                api(2, {"kind": "Status", "code": 404}, absent=True, deletion=True)]
        replay = closure.Closure(base_suite(), Path("."), {"rows": rows}, {}, {0, 2})
        replay._poll_window({"create": {"pod": pod()}}, first=0, last=2, lower=50, phase="Succeeded", deletion=True)
        self.assertEqual(replay.used, {0, 1, 2})
        rows[1]["response_json"]["metadata"]["uid"] = "replacement"
        with self.assertRaises(EvidenceError):
            replay._poll_window({"create": {"pod": pod()}}, first=0, last=2, lower=50, phase="Succeeded", deletion=True)

    def test_preparation_allows_only_one_exact_adjacent_owned_mkdir_parent(self):
        suite = base_suite()
        suite.update(remote_create_call=1, preparations=[])
        rows = [{"raw": {"provider": "docker", "operation": "worker-identity"}},
                {"raw": {"provider": "docker", "operation": "worker-exec"}}]
        used = set()
        for relative in ("fixtures", "tools", "clients/0"):
            destination = model.host_path(OWNER, RUN, relative)
            index = len(rows)
            for offset, argv in enumerate((["mkdir", "-p", str(closure.PurePosixPath(destination).parent)],
                                            ["mkdir", "-m", "700", destination], [])):
                rows.append({"raw": {"ordinal": index + offset, "provider": "docker", "operation": "worker-exec",
                                      "argv": argv, "timeout_seconds": 20}, "stdout": b""})
            suite["preparations"].append({"relative": relative, "destination": destination, "create_call": index + 1,
                                           "upload_call": index + 2, "transfer": {"synthetic": True}})
            used.update((index + 1, index + 2))
        with patch.object(model, "groups", return_value=[]):
            replay = closure.Closure(suite, Path("."), {"rows": rows}, {}, set(used))
            replay.preparation_order()
            self.assertTrue({2, 5, 8} <= replay.used)
            rows[2]["raw"]["argv"][-1] = "/var/local/lsf112/foreign"
            replay = closure.Closure(suite, Path("."), {"rows": rows}, {}, set(used))
            with self.assertRaises(EvidenceError):
                replay.preparation_order()

    def test_unconsumed_workload_or_mutation_cannot_pass_final_gate(self):
        # Isolate the final closure gate after already-tested owned-call handlers.
        for argv in (["latent", "invoke"], ["sh", "-c", "extra mutation"], ["mkdir", "-p", "/foreign"]):
            journal = {"rows": [{"raw": {"provider": "docker", "operation": "worker-exec", "argv": argv}}]}
            with patch.object(closure.Closure, "initialize"), patch.object(closure.Closure, "background"), \
                    patch.object(closure.Closure, "polling"), patch.object(closure.Closure, "progress"):
                with self.subTest(argv=argv), self.assertRaisesRegex(EvidenceError, "unconsumed-call"):
                    closure.validate(base_suite(), Path("."), journal, {}, set())

    def test_background_binds_each_original_node_sample_and_baseline_window(self):
        suite = base_suite()
        suite.update(namespace_create_call=0, groups=[], clients=[{"delete": {"absence_call": 7}}],
                     preparations=[{}, {}, {"create_call": 6}], cleanup={"started_nanos": "4000000000"}, background=[])
        bootstrap = {"nodes": {"control-plane": {"container_id": "a" * 64}, "worker": {"container_id": "b" * 64}}}
        journal = {"rows": [{"raw": {"provider": "docker", "operation": "unused"},
                             "started_nanos": "0", "finished_nanos": "100"} for _ in range(12)]}
        journal["rows"][5]["started_nanos"] = "1000000000"
        journal["rows"][7]["finished_nanos"] = "2000000000"
        for stage, start, ordinal in (("idle-before-start", 1000, 1), ("idle-before-end", 300003000, 3),
                                      ("idle-after-start", 3000000000, 8), ("idle-after-end", 3300003000, 10)):
            observation = {"stage": stage, "observations": []}
            for index, (role, identity) in enumerate(bootstrap["nodes"].items()):
                now, call = start + index * 1000, ordinal + index
                stats = {"id": identity["container_id"], "memory_stats": {"usage": 17}}
                journal["rows"][call] = {"raw": {"ordinal": call, "provider": "docker", "operation": "node-stats", "role": role},
                    "response_json": copy.deepcopy(stats), "started_nanos": str(now), "finished_nanos": str(now + 100)}
                observation["observations"].append({"role": role, "container_id": identity["container_id"], "call": call,
                    "stats": stats, "observed_nanos": str(now + 200)})
            suite["background"].append(observation)
        replay = closure.Closure(suite, Path("."), journal, bootstrap, {0, 5, 6, 7})
        replay.background()
        self.assertEqual(replay.used, set(range(12)))
        for change in ("raw", "node-order", "too-short"):
            changed, calls = copy.deepcopy(suite), copy.deepcopy(journal)
            if change == "raw":
                changed["background"][0]["observations"][0]["stats"]["memory_stats"]["usage"] = 18
            elif change == "node-order":
                changed["background"][0]["observations"].reverse()
            else:
                for row in calls["rows"][3:5]:
                    row["started_nanos"] = str(int(row["started_nanos"]) - 250000000)
                    row["finished_nanos"] = str(int(row["finished_nanos"]) - 250000000)
                for row in changed["background"][1]["observations"]:
                    row["observed_nanos"] = str(int(row["observed_nanos"]) - 250000000)
            replay = closure.Closure(changed, Path("."), calls, bootstrap, {0, 5, 6, 7})
            with self.subTest(change=change), self.assertRaises(EvidenceError):
                replay.background()


if __name__ == "__main__":
    unittest.main()

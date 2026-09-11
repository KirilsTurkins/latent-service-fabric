"""Small synthetic protocol fixtures, never measurements or archive receipts."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from tools.optimization_docker import model, resources
from tools.optimization_evidence.common import canonical, sha256
from tools.phase1_compiler_shutdown import COUNTERS, LIMITS, ZERO
from tools.tests.phase1_measurement_fixtures import shutdown


CONTAINER_ID = "a" * 64


def raw(value=None, reason="open-failed"):
    return {"value": value, "unavailable_reason": reason if value is None else None}


def forward(count=2, live=0):
    return {"capacity": 32, "buffer_bytes_per_direction": 16384,
            "accepted": str(count), "rejected": "0", "completed": str(count-live),
            "failed": "0", "joined": str(count-live), "aborted": "0", "live": str(live),
            "maximum_live": "2", "byte_count_scope": "completed-forward-tasks-only",
            "client_to_app_bytes": str((count-live)*10), "app_to_client_bytes": str((count-live)*20)}


def process(pid, tick, start):
    suffix = ["S", "0" if pid == 1 else "1"] + ["0"] * 17 + [str(tick)]
    proc_stat = f"{pid} (synthetic ) name) " + " ".join(suffix) + "\n"
    address = "00000000:1B9E" if pid == 1 else "0100007F:1B9F"
    listener = f" 0: {address} 00000000:0000 0A 00000000:00000000 00:00000000 00000000 0 0 {pid+100}"
    status = f"Name:\tsynthetic\nVmRSS:\t{pid*4} kB\nThreads:\t3\n"
    return {"pid": pid, "started_nanos": str(start), "finished_nanos": str(start+1),
            "identity_stable": True, "start_time_ticks": str(tick), "start_time_ticks_after": str(tick),
            "stat": raw(proc_stat), "stat_after": raw(proc_stat), "status": raw(status),
            "rss_bytes": str(pid*4096), "threads": "3", "rss_unavailable_reason": None,
            "threads_unavailable_reason": None, "fd_count": "8", "socket_descriptors": {"6": str(pid+100)},
            "fd_unavailable_reason": None, "tcp": raw("header\n"+listener+"\n"), "tcp6": raw("header\n"),
            "listener_rows": [listener], "listeners_unavailable_reason": None,
            "namespaces": {name: raw(f"{name}:[123]") for name in ("pid", "mnt", "net", "user")},
            "cgroup": raw("0::/\n")}


def cgroup(arm, density, start, index):
    controls = model.resources(arm, density)
    files = {name: raw() for name in resources.CGROUP_FILES}
    for name, value in {
        "cpu.max": f"{controls['cpu_quota']} {controls['cpu_period']}\n",
        "cpu.stat": f"usage_usec {index*100}\nuser_usec {index*60}\nsystem_usec {index*40}\n"
                    f"nr_periods {index}\nnr_throttled 0\nthrottled_usec 0\n",
        "cpuset.cpus.effective": "0-3\n", "memory.max": str(controls["memory"])+"\n",
        "memory.current": "65536\n", "memory.peak": "131072\n",
        "memory.events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n",
        "memory.swap.max": "0\n", "memory.swap.current": "0\n",
        "pids.max": str(controls["pids_limit"])+"\n", "pids.current": "6\n", "cgroup.procs": "1\n7\n",
    }.items():
        files[name] = raw(value)
    return {"started_nanos": str(start), "finished_nanos": str(start+1),
            "membership": raw("0::/\n"), "mountinfo": raw("1 0 0:1 / /sys/fs/cgroup rw - cgroup2 cgroup rw\n"),
            "directory": "/sys/fs/cgroup/", "mapping_unavailable_reason": None, "files": files}


def inspect_pair(arm, density):
    controls = model.resources(arm, density)
    host = {name: controls[key] for name, key in (("CpuPeriod", "cpu_period"), ("CpuQuota", "cpu_quota"),
        ("Memory", "memory"), ("MemorySwap", "memory_swap"), ("PidsLimit", "pids_limit"))}
    host.update(CapDrop=["ALL"], Privileged=False, SecurityOpt=["no-new-privileges"], PidMode="", Init=None,
                Ulimits=[{"Name": "nofile", "Soft": 1024, "Hard": 1024}])
    ready = {"Id": CONTAINER_ID, "Image": "sha256:"+"b"*64, "HostConfig": host,
             "Config": {"Entrypoint": ["/opt/lsf/optimization-container"]}, "RestartCount": 0,
             "State": {"Status": "running", "Running": True, "Pid": 500, "Paused": False, "Restarting": False,
                "Dead": False, "OOMKilled": False, "Error": "", "ExitCode": 0,
                "StartedAt": "2026-09-11T12:00:00.000000001Z", "FinishedAt": "0001-01-01T00:00:00Z"}}
    final = deepcopy(ready)
    final["State"].update(Status="exited", Running=False, Pid=0, FinishedAt="2026-09-11T12:01:00.000000001Z")
    return ready, final


def lsf_shutdown():
    result = shutdown()
    compiler = dict.fromkeys(LIMITS + ZERO + COUNTERS, 0)
    compiler.update(maximum_jobs=4, maximum_workers=2, maximum_queued_jobs=2,
                    maximum_waiters=8, maximum_waiters_per_job=4, maximum_ready_preparations=4,
                    maximum_document_bytes=65536, workers_quiescent=2, workers_joined=2,
                    accepting=False, failed=False)
    result["compiler"] = compiler
    result["cleanup"] = {"capacity": 4, "reserved": 0, "queued": 0, "running": 0, "handoffs": 0,
        "completed": 0, "timedOut": 0, "panicked": 0, "fallbacks": 0,
        "accepting": False, "driverAlive": False, "driverJoined": True, "failed": False}
    return result


class Fixture:
    def __init__(self, directory, arm="native", density=32, snapshots=6):
        self.directory, self.arm, self.density, self.snapshots = directory, arm, density, snapshots
        self.ready_inspect, self.final_inspect = inspect_pair(arm, density)
        if arm == "native":
            ready = {"event": "ready", "implementation": "native-reference", "address": "http://127.0.0.1:7071"}
            stopped = {"event": "stopped", "implementation": "native-reference", "clean": True}
        else:
            ready = {"schemaVersion": "latent.standalone.status.v1", "event": "ready", "nodeId": "optimization-node",
                     "endpoint": "127.0.0.1:7071", "ready": True}
            stopped = {"schemaVersion": "latent.standalone.status.v1", "event": "stopped", "clean": True,
                       "report": lsf_shutdown()}
        self.child_records = [ready, stopped]
        self.stderr = b"synthetic diagnostic\n"
        self.events = []
        self.emit("started", deepcopy(resources.STARTED), 1)
        self.emit("ready", {"listen": "0.0.0.0:7070", "child_listen": "127.0.0.1:7071", "child_status": ready}, 2)
        for index in range(1, snapshots+1):
            start = 10*index
            self.emit("snapshot", {"snapshot_index": index, "started_nanos": str(start), "finished_nanos": str(start+7),
                "wrapper": process(1, 100, start+1), "child": process(7, 110, start+3),
                "cgroup": cgroup(arm, density, start+5, index), "forward": forward(live=2)}, start+8)
        self.emit("stopped", {"clean": True, "failure": None, "stop_requested": True,
            "child": {"reaped": True, "term_sent": True, "kill_sent": False, "exit_code": 0, "signal": None, "error": None},
            "forward": forward(), "copy_tasks_joined": True, "output_tasks_joined": True,
            "stdout": None, "stderr": None, "snapshots": snapshots}, 80)
        self.write()

    def emit(self, event, detail, elapsed):
        self.events.append({"schema": resources.SCHEMA, "sequence": len(self.events), "event": event,
            "app": self.arm, "wrapper_pid": 1, "child_pid": 7, "elapsed_nanos": str(elapsed), "detail": detail})

    def write(self, *, logs=True):
        if logs:
            for name, data, ready, stopped in (
                ("child-stdout.bin", b"".join(canonical(row)+b"\n" for row in self.child_records), *self.child_records[:2]),
                ("child-stderr.bin", self.stderr, None, None)):
                (self.directory/name).write_bytes(data)
                key = "stdout" if name == "child-stdout.bin" else "stderr"
                self.events[-1]["detail"][key] = {"path": name, "bytes": str(len(data)), "lines_processed": str(data.count(b"\n")),
                    "sha256": sha256(data), "eof": True, "error": None, "ready": ready, "stopped": stopped,
                    "maximum_bytes": 262144, "maximum_line_bytes": 16384}
        (self.directory/"events.ndjson").write_bytes(b"".join(canonical(row)+b"\n" for row in self.events))

    def validate(self, **kwargs):
        return resources.validate(self.directory, arm=self.arm, density=self.density, container_id=CONTAINER_ID,
            ready_inspect=self.ready_inspect, final_inspect=self.final_inspect, expected_snapshots=self.snapshots,
            expected_connections=kwargs.get("connections", 2))


class DockerResources(unittest.TestCase):
    def test_provider_extraction_keeps_docker_projection_exact(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            expected = fixture.validate()
            controls = model.resources(fixture.arm, fixture.density)
            identity = resources._inspect(fixture.ready_inspect, fixture.final_inspect, CONTAINER_ID, controls)
            actual = resources.validate_observations(fixture.directory, arm=fixture.arm, density=fixture.density,
                container_id=CONTAINER_ID, identity=identity, controls=controls, expected_connections=2)
            self.assertEqual(actual, expected)
            self.assertNotIn("wrapper_pid", identity)

    def test_docker_still_rejects_unbounded_leaf_pids(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            fixture.events[2]["detail"]["cgroup"]["files"]["pids.max"] = raw("max\n")
            fixture.write()
            with self.assertRaises(ValueError):
                fixture.validate()

    def test_root_cgroup_mapping_preserves_actual_empty_join_spelling(self):
        mounts = "1287 1286 0:23 / /sys/fs/cgroup ro,nosuid,nodev,noexec,relatime - cgroup2 cgroup rw\n"
        self.assertEqual(resources._directory("0::/\n", mounts), "/sys/fs/cgroup/")
        self.assertEqual(resources._directory("0::/owned\n", mounts), "/sys/fs/cgroup/owned")
        subtree = mounts.replace("0:23 / ", "0:23 /owned ")
        self.assertEqual(resources._directory("0::/owned\n", subtree), "/sys/fs/cgroup/")
        self.assertEqual(resources._directory("0::/owned/child\n", subtree), "/sys/fs/cgroup/child")
        self.assertIsNone(resources._directory("0::/foreign\n", subtree))
        self.assertIsNone(resources._directory("0::/../foreign\n", mounts))
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            self.assertEqual(fixture.validate()["snapshots"][0]["cgroup"]["directory"], "/sys/fs/cgroup/")
            fixture.events[2]["detail"]["cgroup"]["directory"] = "/sys/fs/cgroup/foreign"
            fixture.write()
            with self.assertRaisesRegex(ValueError, "cgroup-mapping"):
                fixture.validate()

    def test_six_snapshots_bind_identity_and_separate_process_rss_from_one_cgroup(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            result = fixture.validate()
            self.assertEqual(len(result["snapshots"]), 6)
            row = result["snapshots"][0]
            self.assertEqual(row["wrapper"]["rss_bytes"], "4096")
            self.assertEqual(row["child"]["rss_bytes"], "28672")
            self.assertEqual(row["cgroup"]["memory.current"], "65536")
            self.assertEqual(result["identity"]["host_wrapper_pid_at_ready"], 500)
            self.assertEqual(result["identity"]["wrapper_pid"], 1)
            self.assertEqual(row["cgroup"]["cpu_stat"]["usage_usec"], "100")
            self.assertEqual(row["cgroup"]["limits"]["cpu.max"], {"quota": "12500", "period": "100000"})
            self.assertNotIn("active", result["shutdown"]["child_stopped"])

    def test_seed_has_no_fabricated_start_namespace_or_connection_count(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory), arm="lsf", density=1, snapshots=0)
            result = fixture.validate(connections=None)
            self.assertEqual(result["snapshots"], [])
            self.assertIsNone(result["identity"]["processes"])
            self.assertEqual(result["identity"]["process_identity_unavailable_reason"], "seed-without-snapshots")

    def test_optional_unavailable_metrics_remain_null_with_reasons(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            row = fixture.events[2]["detail"]
            child = row["child"]
            child.update(status=raw(), rss_bytes=None, threads=None, rss_unavailable_reason="status-field-unavailable",
                         threads_unavailable_reason="status-field-unavailable", fd_count=None, socket_descriptors=None,
                         fd_unavailable_reason="fd-raced-or-unavailable", listener_rows=None,
                         listeners_unavailable_reason="socket-table-or-fd-unavailable")
            row["cgroup"]["files"]["cpu.max"] = raw()
            row["cgroup"]["files"]["memory.current"] = raw()
            fixture.write()
            result = fixture.validate()["snapshots"][0]
            self.assertIsNone(result["child"]["rss_bytes"])
            self.assertIsNone(result["cgroup"]["limits"]["cpu.max"])
            self.assertIsNone(result["cgroup"]["memory.current"])
            self.assertEqual(result["cgroup"]["unavailable_reasons"]["memory.current"], "open-failed")

    def test_unmapped_cgroup_cannot_lend_observed_control_values(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            group = fixture.events[2]["detail"]["cgroup"]
            group.update(mountinfo=raw(), directory=None, mapping_unavailable_reason="cgroup-v2-mapping-unavailable")
            group["files"] = {name: raw(reason="cgroup-v2-mapping-unavailable") for name in resources.CGROUP_FILES}
            fixture.write()
            self.assertIsNone(fixture.validate()["snapshots"][0]["cgroup"]["directory"])
            group["files"]["cpu.max"] = raw("12500 100000\n")
            fixture.write()
            with self.assertRaisesRegex(ValueError, "unmapped-cgroup-file"):
                fixture.validate()

    def test_changed_child_ticks_namespace_and_outer_pid_reject(self):
        changes = (
            lambda f: f.events[3]["detail"]["child"].update(start_time_ticks="999"),
            lambda f: f.events[3]["detail"]["child"]["namespaces"].update(net=raw("net:[999]")),
            lambda f: f.events[3].update(child_pid=8),
            lambda f: f.events[3].update(wrapper_pid=500),
        )
        self.reject_changes(changes)

    def test_derived_rss_fd_and_socket_rows_are_bound_to_raw(self):
        changes = (
            lambda f: f.events[2]["detail"]["child"].update(rss_bytes="1"),
            lambda f: f.events[2]["detail"]["child"].update(fd_count="0"),
            lambda f: f.events[2]["detail"]["child"].update(listener_rows=[]),
            lambda f: f.events[2]["detail"]["child"]["socket_descriptors"].update({"6": "999"}),
            lambda f: f.events[2]["detail"]["child"].update(threads_unavailable_reason="open-failed"),
        )
        self.reject_changes(changes)

    def test_cgroup_controls_foreign_membership_unowned_process_and_regressed_cpu_reject(self):
        changes = (
            lambda f: f.events[2]["detail"]["cgroup"]["files"].update({"cpu.max": raw("400000 100000\n")}),
            lambda f: f.events[2]["detail"]["cgroup"]["files"].update({"memory.swap.max": raw("1\n")}),
            lambda f: f.events[2]["detail"]["cgroup"]["files"].update({"pids.max": raw("512\n")}),
            lambda f: f.events[2]["detail"]["cgroup"]["files"].update({"cgroup.procs": raw("1\n7\n8\n")}),
            lambda f: f.events[2]["detail"]["child"].update(cgroup=raw("0::/foreign\n")),
            lambda f: f.events[3]["detail"]["cgroup"]["files"].update({"cpu.stat": raw("usage_usec 0\n")}),
        )
        self.reject_changes(changes)

    def test_copy_join_conservation_forced_kill_and_output_eof_reject(self):
        changes = (
            lambda f: f.events[-1]["detail"].update(copy_tasks_joined=False),
            lambda f: f.events[-1]["detail"].update(output_tasks_joined=False),
            lambda f: f.events[-1]["detail"]["child"].update(kill_sent=True),
            lambda f: f.events[-1]["detail"]["forward"].update(live="1"),
            lambda f: f.events[-1]["detail"]["forward"].update(rejected="1"),
            lambda f: f.events[-1]["detail"]["stdout"].update(eof=False),
        )
        self.reject_changes(changes, logs=False)

    def test_actual_lsf_compiler_cleanup_and_quarantine_failures_reject(self):
        for field, replacement in (("quarantinedCells", 1), ("liveStores", 1)):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(Path(directory), arm="lsf")
                fixture.child_records[1]["report"][field] = replacement
                fixture.write()
                with self.assertRaises(ValueError):
                    fixture.validate()
        for owner, field, replacement in (("compiler", "workers_joined", 1), ("cleanup", "driverJoined", False)):
            with self.subTest(owner=owner), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(Path(directory), arm="lsf")
                fixture.child_records[1]["report"][owner][field] = replacement
                fixture.write()
                with self.assertRaises(ValueError):
                    fixture.validate()

    def test_inspect_controls_restart_oom_and_host_pid_confusion_reject(self):
        changes = (
            lambda f: f.ready_inspect["HostConfig"].update(CpuQuota=400000),
            lambda f: f.final_inspect["State"].update(OOMKilled=True),
            lambda f: f.final_inspect.update(RestartCount=1),
            lambda f: f.final_inspect["State"].update(Pid=500),
            lambda f: f.final_inspect["State"].update(StartedAt="2026-09-11T12:00:01Z"),
            lambda f: f.final_inspect.update(Id="c"*64),
        )
        self.reject_changes(changes)

    def test_log_original_bytes_duplicate_records_and_line_bound_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            path = Path(directory)/"child-stderr.bin"
            path.write_bytes(path.read_bytes()+b"tamper")
            with self.assertRaisesRegex(ValueError, "log-receipt"):
                fixture.validate()
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            fixture.child_records.append(fixture.child_records[1])
            fixture.write()
            with self.assertRaisesRegex(ValueError, "child-stopped"):
                fixture.validate()
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            fixture.stderr = b"x"*16384+b"\n"
            fixture.write()
            with self.assertRaisesRegex(ValueError, "line-bound"):
                fixture.validate()

    def test_connections_events_snapshot_count_and_clock_bounds_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "connection-count"):
                fixture.validate(connections=3)
        self.reject_changes((
            lambda f: f.events[3].update(sequence=2),
            lambda f: f.events[2]["detail"].update(finished_nanos="999"),
            lambda f: f.events[2]["detail"].update(snapshot_index=2),
            lambda f: f.events[-1]["detail"].update(snapshots=5),
        ))

    def reject_changes(self, changes, *, logs=True):
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(Path(directory))
                change(fixture)
                fixture.write(logs=logs)
                with self.assertRaises(ValueError):
                    fixture.validate()


if __name__ == "__main__":
    unittest.main()

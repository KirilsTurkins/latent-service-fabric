"""Synthetic partial protocol fixtures; no fake qualified comparison campaign."""
import base64
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import tarfile
import unittest

from tools.optimization_docker import evidence
from tools.optimization_evidence.common import canonical, sha256


CID, NET, CONTROLLER = "a"*64, "b"*64, "c"*64


def api(ordinal, method, path, response=None, *, request=None, status=200):
    raw = b"" if response is None else json.dumps(response, separators=(",", ":")).encode()
    request_raw = b"" if request is None else json.dumps(request, separators=(",", ":")).encode()
    return {"ordinal": ordinal, "method": method, "path": path, "request": request, "response": response,
        "receipt": {"method": method, "path": "/v1.54"+path, "begin_nanos": str(ordinal*10+1),
            "end_nanos": str(ordinal*10+2), "status": status, "request_bytes": str(len(request_raw)),
            "request_sha256": sha256(request_raw), "response_bytes": str(len(raw)), "response_sha256": sha256(raw),
            "response_complete": True, "connection_closed": True, "failure": None},
        "error": None, "response_bytes_base64": base64.b64encode(raw).decode()}


def write_rows(root, rows):
    (root/"engine.ndjson").write_bytes(b"".join(canonical(row)+b"\n" for row in rows))


def mini_protocol():
    # A single seed lifecycle exercises the state machine, not the full preset.
    labels = {evidence.LABEL: "unit", evidence.ROLE: "bridge"}
    body = {"Name": "unit-bridge", "CheckDuplicate": True, "Driver": "bridge", "Internal": True,
            "Attachable": False, "EnableIPv6": False, "Labels": labels}
    network = {"Id": NET, "Labels": labels, "Driver": "bridge", "Internal": True, "Containers": {}}
    config = {"Image": "sha256:"+"d"*64, "Labels": {evidence.LABEL: "unit", evidence.ROLE: "seed-d1"}}
    controller = {"Id": CONTROLLER, "State": {"Running": True},
                  "Config": {"Labels": {evidence.LABEL: "issue111-controller-01"}}}
    inspected = {"Id": CID, "Name": "/unit-seed-d1", "Image": config["Image"],
                 "Config": {"Labels": config["Labels"]}, "State": {"OOMKilled": False, "Running": True, "ExitCode": 0}}
    stopped = deepcopy(inspected)
    stopped["State"]["Running"] = False
    rows = []
    def add(method, path, response=None, request=None, status=200):
        rows.append(api(len(rows), method, path, response, request=request, status=status))
    add("GET", "/networks/unit-bridge", {"message": "not found"}, status=404)
    add("POST", "/networks/create", {"Id": NET}, body, 201)
    add("GET", "/networks/unit-bridge", network)
    add("GET", "/networks/"+NET, network)
    add("GET", "/containers/"+CONTROLLER+"/json", controller)
    add("POST", "/networks/"+NET+"/connect", request={"Container": CONTROLLER})
    add("GET", "/containers/unit-seed-d1/json", {"message": "not found"}, status=404)
    add("POST", "/containers/create?name=unit-seed-d1", {"Id": CID, "Warnings": []}, config, 201)
    add("GET", "/containers/unit-seed-d1/json", inspected)
    add("POST", "/containers/"+CID+"/start", status=204)
    add("GET", "/containers/"+CID+"/json", inspected)
    add("POST", "/containers/"+CID+"/stop?t=30", status=204)
    add("POST", "/containers/"+CID+"/wait?condition=not-running", {"StatusCode": 0})
    add("GET", "/containers/"+CID+"/json", stopped)
    add("DELETE", "/containers/"+CID+"?v=false&force=false", status=204)
    add("GET", "/containers/"+CID+"/json", {"message": "not found"}, status=404)
    add("POST", "/networks/"+NET+"/disconnect", request={"Container": CONTROLLER, "Force": False})
    add("GET", "/networks/"+NET, network)
    add("DELETE", "/networks/"+NET, status=204)
    add("GET", "/networks/"+NET, {"message": "not found"}, status=404)
    suite = {"cleanup": {"network_id": NET}, "run_id": "unit", "environment": {"controller": controller}, "images": {}}
    return rows, suite, {"seed-d1": (CID, config)}


class DockerOuterEvidence(unittest.TestCase):
    def test_context_tar_digest_replays_original_ustar_bytes_without_retaining_another_tar(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"Dockerfile").write_bytes(b"FROM synthetic\n")
            (root/"app").write_bytes(b"synthetic executable")
            members = [{"path": ".", "kind": "directory", "mode": "0755"}]
            for name, mode in (("Dockerfile", "0644"), ("app", "0755")):
                data = (root/name).read_bytes()
                members.append({"path": name, "kind": "file", "mode": mode, "bytes": str(len(data)), "sha256": sha256(data)})
            with tempfile.TemporaryFile() as output:
                with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as target:
                    for row in members[1:]:
                        info = tarfile.TarInfo(row["path"])
                        info.mode, info.size = int(row["mode"], 8), int(row["bytes"])
                        with (root/row["path"]).open("rb") as original:
                            target.addfile(info, original)
                output.seek(0)
                data = output.read()
            self.assertEqual(evidence.context_tar_hash(root, members), (sha256(data), str(len(data))))
            members[2]["mode"] = "0644"
            with self.assertRaisesRegex(ValueError, "context-executable-mode"):
                evidence.context_tar_hash(root, members)

    def test_unversioned_negotiation_is_separate_bounded_closed_evidence(self):
        row = api(0, "GET", "/version", {"Version": "29.0", "MinAPIVersion": "1.44", "ApiVersion": "1.54"})
        row["receipt"]["path"] = "/version"
        value = {key: row[key] for key in ("response", "receipt", "response_bytes_base64")}
        evidence.negotiation(value, 0, 10)
        value["receipt"]["connection_closed"] = False
        with self.assertRaisesRegex(ValueError, "negotiation-receipt"):
            evidence.negotiation(value, 0, 10)

    def test_engine_receipt_binds_original_entity_bytes_and_parsed_value(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [api(0, "POST", "/unit", {"answer": 7}, request={"query": 3})]
            write_rows(root, rows)
            self.assertEqual(evidence.journal(root, 0, 100), rows)

    def test_engine_json_reformat_or_crossed_request_response_reject(self):
        changes = (
            lambda row: row.update(response={"answer": 8}),
            lambda row: row.update(request={"query": 4}),
            lambda row: row.update(response_bytes_base64=base64.b64encode(b'{ "answer": 7 }').decode()),
            lambda row: row["receipt"].update(response_sha256=sha256(b"other")),
            lambda row: row["receipt"].update(request_bytes="0"),
        )
        self.reject_journal(changes)

    def test_engine_unclosed_failure_version_and_nonmonotonic_calls_reject(self):
        self.reject_journal((
            lambda row: row["receipt"].update(connection_closed=False),
            lambda row: row["receipt"].update(response_complete=False),
            lambda row: row["receipt"].update(failure="timeout"),
            lambda row: row["receipt"].update(path="/v1.53/unit"),
            lambda row: row["receipt"].update(begin_nanos="3", end_nanos="2"),
            lambda row: row.update(ordinal=1),
        ))

    def reject_journal(self, changes):
        for change in changes:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                row = api(0, "POST", "/unit", {"answer": 7}, request={"query": 3})
                change(row)
                write_rows(root, [row])
                with self.assertRaises(ValueError):
                    evidence.journal(root, 0, 100)

    def test_duplicate_json_noncanonical_base64_and_incomplete_line_reject(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            row = api(0, "GET", "/unit", {"a": 1})
            raw = b'{"a":1,"a":2}'
            row.update(response_bytes_base64=base64.b64encode(raw).decode())
            row["receipt"].update(response_bytes=str(len(raw)), response_sha256=sha256(raw))
            write_rows(root, [row])
            with self.assertRaisesRegex(ValueError, "duplicate-json-key"):
                evidence.journal(root, 0, 100)
            write_rows(root, [api(0, "GET", "/unit")])
            path = root/"engine.ndjson"
            path.write_bytes(path.read_bytes()[:-1])
            with self.assertRaisesRegex(ValueError, "journal-bound"):
                evidence.journal(root, 0, 100)

    def test_private_network_and_reaped_container_have_one_complete_lifecycle(self):
        rows, suite, configs = mini_protocol()
        self.assertEqual(evidence.api_protocol(rows, suite, configs), {CID: []})

    def test_volume_probe_must_bind_the_owned_volume_before_containers(self):
        rows, suite, configs = mini_protocol()
        suite["volume"] = "owned-volume"
        suite["environment"]["volume"] = {"Name": "owned-volume"}
        probe = api(6, "GET", "/volumes/owned-volume", {"Name": "owned-volume"})
        rows.insert(6, probe)
        self.assertEqual(evidence.api_protocol(rows, suite, configs), {CID: []})
        probe["response"] = {"Name": "foreign-volume"}
        with self.assertRaisesRegex(ValueError, "volume-inspect-binding"):
            evidence.api_protocol(rows, suite, configs)

    def test_applied_manifest_normalizes_codec_defaults_without_changing_limits(self):
        source = {"spec": {"grants": [], "resources": {"cpuFuel": 10, "wallTimeLimitMillis": None},
                           "placement": {"architectures": ["x86_64", "aarch64"]}}}
        expected = {"spec": {"resources": {"cpuFuel": 10},
                             "placement": {"architectures": ["aarch64", "x86_64"]}}}
        self.assertEqual(evidence.applied_manifest(source), expected)
        self.assertIn("grants", source["spec"])
        source["spec"]["resources"]["wallTimeLimitMillis"] = 1000
        self.assertEqual(evidence.applied_manifest(source)["spec"]["resources"]["wallTimeLimitMillis"], 1000)

    def test_force_removal_unowned_signal_hidden_exec_and_changed_config_reject(self):
        changes = (
            lambda rows: rows[14].update(path=f"/containers/{CID}?v=false&force=true"),
            lambda rows: rows[11].update(path=f"/containers/{CID}/kill?signal=SIGKILL"),
            lambda rows: rows[11].update(path=f"/containers/{CID}/exec"),
            lambda rows: rows[7]["request"].update(HostConfig={"Privileged": True}),
            lambda rows: rows[1]["request"].update(Internal=False),
            lambda rows: rows[12]["response"].update(StatusCode=137),
        )
        for change in changes:
            with self.subTest(change=change):
                rows, suite, configs = mini_protocol()
                # Separate expected configuration from journal's synthetic input.
                configs = deepcopy(configs)
                change(rows)
                with self.assertRaises(ValueError):
                    evidence.api_protocol(rows, suite, configs)

    def test_remove_before_wait_and_missing_absence_cannot_claim_cleanup(self):
        for indices in ((12,), (15,), (19,)):
            with self.subTest(indices=indices):
                rows, suite, configs = mini_protocol()
                rows = [row for index, row in enumerate(rows) if index not in indices]
                with self.assertRaises(ValueError):
                    evidence.api_protocol(rows, suite, configs)

    def test_wrong_api_ordinal_cannot_bind_a_signal_to_an_inspect(self):
        rows, _, _ = mini_protocol()
        with self.assertRaisesRegex(ValueError, "crossed-api-reference"):
            evidence.Calls(rows).at(10, "POST", f"/containers/{CID}/kill?signal=SIGUSR1")

    def test_inventory_original_bytes_and_recorded_modes_are_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"data").write_bytes(b"original")
            value = {"entries": [{"path": ".", "kind": "directory", "mode": "0755"},
                {"path": "data", "kind": "file", "mode": "0600", "bytes": "8", "sha256": sha256(b"original")}], "bytes": "8"}
            evidence.inventory(root, value)
            (root/"data").write_bytes(b"modified")
            with self.assertRaises(ValueError):
                evidence.inventory(root, value)
            # Removed measured directories are represented by a checked retained
            # inventory, never by pretending their bytes are still available.
            evidence.inventory(root/"absent", value, retained=False)

    def test_inventory_escape_duplicate_total_and_mode_reject(self):
        changes = (
            lambda value: value["entries"][1].update(path="../escape"),
            lambda value: value["entries"][1].update(path="."),
            lambda value: value["entries"][1].update(mode="7777"),
            lambda value: value.update(bytes="2"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for change in changes:
                with self.subTest(change=change):
                    value = {"entries": [{"path": ".", "kind": "directory", "mode": "0755"},
                        {"path": "data", "kind": "file", "mode": "0600", "bytes": "1", "sha256": sha256(b"x")}], "bytes": "1"}
                    change(value)
                    with self.assertRaises(ValueError):
                        evidence.inventory(Path(directory), value, retained=False)

    def test_snapshot_window_cannot_cross_phase_or_borrow_another_owner(self):
        commands = [{"line": json.dumps({"group": 0, "command": "inventory", "barrier": stage}), "sent_nanos": str(index*100)}
                    for index, stage in enumerate(("ready", "served", "final"))]
        commands.append({"line": json.dumps({"group": 0, "command": "finish-group", "barrier": None}), "sent_nanos": "400"})
        # A malformed window is rejected before it could be mistaken for a real 250ms witness.
        group = {"group": 0, "started_nanos": "0", "finished_nanos": "400", "windows": [
            {"stage": "ready", "started_nanos": "1", "finished_nanos": "3", "before": [], "after": [],
             "sleep_begin_nanos": "1", "sleep_end_nanos": "2"}]*3}
        parent = {"commands": commands, "acknowledgements": []}
        with self.assertRaisesRegex(ValueError, "window-clock"):
            evidence.windows(group, [], evidence.Calls([]), parent)

    def test_three_actual_window_brackets_bind_all_six_owner_snapshot_receipts(self):
        parent = {"commands": [], "acknowledgements": []}
        group = {"group": 0, "started_nanos": "0", "finished_nanos": "4000000000", "windows": []}
        snapshots = []
        for index, stage in enumerate(("ready", "served", "final")):
            start = (index+1)*10**9
            command = {"group": 0, "command": "inventory", "barrier": stage}
            parent["commands"].append({"line": json.dumps(command), "sent_nanos": str(start-2)})
            parent["acknowledgements"].append({"ack": {"event": "inventory", "command_ordinal": index*2},
                                                "received_nanos": str(start-1)})
            command = {"group": 0, "command": "phase" if index < 2 else "finish-group", "barrier": None}
            parent["commands"].append({"line": json.dumps(command), "sent_nanos": str(start+300000004)})
            before = {"snapshot_index": 2*index+1, "signal_before_nanos": str(start+1), "observed_nanos": str(start+2)}
            after = {"snapshot_index": 2*index+2, "signal_before_nanos": str(start+300000001),
                     "observed_nanos": str(start+300000002)}
            snapshots.extend((before, after))
            group["windows"].append({"stage": stage, "started_nanos": str(start), "before": [before],
                "sleep_begin_nanos": str(start+3), "sleep_end_nanos": str(start+300000000), "after": [after],
                "finished_nanos": str(start+300000003)})
        applications = [{"parent": {"snapshots": snapshots}}]
        evidence.windows(group, applications, evidence.Calls([]), parent)
        group["windows"][1]["before"] = [snapshots[0]]
        with self.assertRaisesRegex(ValueError, "window-before-binding"):
            evidence.windows(group, applications, evidence.Calls([]), parent)

    def test_original_root_cannot_alias_host_or_escape_bench(self):
        self.assertEqual(str(evidence.original_root("/bench/run-01")), "/bench/run-01")
        for value in ("/bench", "/etc", "/bench/../etc", "C:/bench/run", "/bench/run/../other"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evidence.original_root(value)


if __name__ == "__main__":
    unittest.main()

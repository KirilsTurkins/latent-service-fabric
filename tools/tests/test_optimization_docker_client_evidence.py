"""Small protocol primitives only; these unit inputs are not measured sessions."""

import copy
from pathlib import Path
import tempfile
import unittest

from tools.optimization_docker import client_evidence as evidence, model
from tools.optimization_evidence.common import EvidenceError, canonical, sha256


def protocol(profile="smoke", pair=0):
    """Enumerate parent control shapes, without inventing RPC or resource results."""
    plan = {"schema": model.CLIENT_PREFIX + "plan.v1", "run_id": "unit-protocol", "profile": profile,
            "pair": pair, "token_file": "/fixtures/token"}
    groups = model.groups(profile, pair)
    plan_digest = sha256(canonical(plan) + b"\n")
    owners, targets = {}, {}
    for group in groups:
        index, density, arm = group["ordinal"], group["density"], group["arm"]
        rows = []
        for target in range(density):
            owner_ref = f"unit-owner-{index}-{target if arm == 'native' else 0}"
            endpoint = f"http://unit-{index}-{target if arm == 'native' else 0}:8080"
            rows.append({"service": model.SERVICES[target], "endpoint": endpoint,
                         "owner_ref": owner_ref, "app_process_id": 7})
            if owner_ref not in owners:
                owner = {"app_process_id": 7, "endpoint": endpoint, "arm": arm, "density": density,
                         "group": index, "container_id": f"{len(owners) + 1:064x}"}
                if arm == "lsf":
                    owner["release_digests"] = {service: sha256(service.encode()) for service in model.SERVICES[:density]}
                owners[owner_ref] = owner
        targets[index] = rows
    commands = []
    for ordinal, (command, group, phase, barrier) in enumerate(evidence._sequence(groups)):
        value = {"schema": model.CLIENT_PREFIX + "command.v1", "ordinal": ordinal, "plan_sha256": plan_digest,
                 "command": command, "group": group, "phase": phase, "barrier": barrier,
                 "targets": targets[group] if command == "begin-group" else None}
        commands.append({"line": (canonical(value) + b"\n").decode(), "sent_nanos": str(ordinal + 1)})
    return plan, groups, plan_digest, owners, commands


class ClientEvidenceTests(unittest.TestCase):
    def test_explicit_service_map_allows_distinct_lsf_services_on_one_process(self):
        _, groups, _, owners, commands = protocol()
        group = next(group for group in groups if group["arm"] == "lsf" and group["density"] == 8)
        command = next(evidence.decode(row["line"].encode()) for row in commands
                       if evidence.decode(row["line"].encode())["command"] == "begin-group"
                       and evidence.decode(row["line"].encode())["group"] == group["ordinal"])
        targets = command["targets"]
        owner_ref = targets[0]["owner_ref"]
        endpoints = {target["service"]: f"http://service-{index}.example:7070"
                     for index, target in enumerate(targets)}
        owners[owner_ref].update(endpoint=next(iter(endpoints.values())), service_endpoints=endpoints)
        for target in targets:
            target["endpoint"] = endpoints[target["service"]]
        self.assertEqual(evidence._targets(targets, group, owners), {owner_ref})
        for mutate in (lambda row: row.pop("service_endpoints"),
                       lambda row: row["service_endpoints"].pop(model.SERVICES[1]),
                       lambda row: row["service_endpoints"].update({model.SERVICES[1]: endpoints[model.SERVICES[0]]}),
                       lambda row: row.update(endpoint="http://unowned.example:7070")):
            changed = copy.deepcopy(owners)
            mutate(changed[owner_ref])
            with self.assertRaises(EvidenceError):
                evidence._targets(targets, group, changed)
        crossed = copy.deepcopy(targets)
        crossed[1]["endpoint"] = crossed[0]["endpoint"]
        with self.assertRaises(EvidenceError):
            evidence._targets(crossed, group, owners)

    def test_native_service_map_cannot_borrow_another_owner_service(self):
        _, groups, _, owners, commands = protocol()
        group = next(group for group in groups if group["arm"] == "native" and group["density"] == 8)
        command = next(evidence.decode(row["line"].encode()) for row in commands
                       if evidence.decode(row["line"].encode())["command"] == "begin-group"
                       and evidence.decode(row["line"].encode())["group"] == group["ordinal"])
        targets = command["targets"]
        for target in targets:
            owners[target["owner_ref"]]["service_endpoints"] = {target["service"]: target["endpoint"]}
        self.assertEqual(len(evidence._targets(targets, group, owners)), 8)
        owner = owners[targets[0]["owner_ref"]]
        owner["service_endpoints"][targets[1]["service"]] = targets[1]["endpoint"]
        with self.assertRaises(EvidenceError):
            evidence._targets(targets, group, owners)

    def test_exact_control_population_requires_three_barriers_before_drop(self):
        for profile, pair in (("smoke", 0), *(('full', pair) for pair in range(7))):
            _, groups, digest, owners, commands = protocol(profile, pair)
            parsed, receipts, targets = evidence._commands(commands, groups, digest, owners)
            self.assertEqual(len(parsed), 61)
            self.assertEqual(len(receipts), 61)
            self.assertEqual(len(owners), 44)
            self.assertEqual(sum(len(value) for value in targets.values()), 82)
            self.assertEqual(sum(row["command"] == "inventory" for row in parsed), 18)
            self.assertEqual(parsed[-2]["command"], "finish-group")
            self.assertEqual(parsed[-3]["barrier"], "final")

    def test_duplicate_command_or_hidden_workload_override_rejected(self):
        _, groups, digest, owners, commands = protocol()
        duplicated = copy.deepcopy(commands)
        duplicated[1] = duplicated[0]
        with self.assertRaises(EvidenceError):
            evidence._commands(duplicated, groups, digest, owners)
        command = evidence.decode(commands[1]["line"].encode())
        command["offered_count"] = 1
        changed = copy.deepcopy(commands)
        changed[1]["line"] = (canonical(command) + b"\n").decode()
        with self.assertRaises(EvidenceError):
            evidence._commands(changed, groups, digest, owners)

    def test_missing_explicit_null_and_bool_ordinal_rejected(self):
        _, groups, digest, owners, commands = protocol()
        for change in (lambda value: value.pop("phase"), lambda value: value.update(ordinal=True)):
            parsed = evidence.decode(commands[1]["line"].encode())
            change(parsed)
            changed = copy.deepcopy(commands)
            changed[1]["line"] = (canonical(parsed) + b"\n").decode()
            with self.assertRaises(EvidenceError):
                evidence._commands(changed, groups, digest, owners)

    def test_actual_namespace_pid_and_fixture_release_map_required(self):
        _, groups, digest, owners, commands = protocol()
        key = next(iter(owners))
        for alter in (lambda owner: owner.update(app_process_id=99), lambda owner: owner.pop("release_digests")):
            changed = copy.deepcopy(owners)
            alter(changed[key])
            with self.assertRaises(EvidenceError):
                evidence._commands(commands, groups, digest, changed)

    def test_hashes_cover_original_bytes_not_reformatted_json(self):
        data = b'{ "status" : "example" }\n'
        ref = {"path": "summary.json", "bytes": str(len(data)), "sha256": sha256(data)}
        evidence._reference(ref, "summary.json", data)
        with self.assertRaises(EvidenceError):
            evidence._reference(ref, "summary.json", canonical(evidence.decode(data)) + b"\n")
        with self.assertRaises(EvidenceError):
            evidence._reference(ref, "../summary.json", data)

    def test_lines_reject_truncated_oversized_or_duplicate_fields(self):
        self.assertEqual(len(evidence._lines(b'{"x":1}\n', 8, 1)), 1)
        for data, width, count in ((b'{"x":1}', 8, 1), (b'{"x":1}\n', 7, 1),
                                   (b'{"x":1}\n{"x":2}\n', 8, 1), (b'{"x":1,"x":2}\n', 32, 1)):
            with self.assertRaises(EvidenceError):
                evidence._lines(data, width, count)

    def test_changed_plan_bytes_cannot_borrow_original_decoded_plan(self):
        plan, _, _, _, _ = protocol()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            altered = {**plan, "pair": 1}
            (path / "plan.json").write_bytes(canonical(altered) + b"\n")
            with self.assertRaisesRegex(EvidenceError, "original-plan"):
                evidence.validate(path, plan, [], [], {})

    def test_native_barrier_cannot_claim_a_management_response(self):
        group = {"ordinal": 0, "arm": "native", "density": 32}
        value = {"status": "passed", "barrier": "ready", "rpc_calls": 0, "inventory": None,
                 "reason": "native-no-management-api", "channel_index": None,
                 "started_nanos": "100", "finished_nanos": "101"}
        self.assertEqual(evidence._inventory(value, group, "ready", 90, 110)["rpc_calls"], 0)
        for changed in ({**value, "rpc_calls": 1}, {**value, "channel_index": 0},
                        {**value, "inventory": {}}, {**value, "finished_nanos": "99"}):
            with self.assertRaises(EvidenceError):
                evidence._inventory(changed, group, "ready", 90, 110)

    def test_bounded_file_read_stops_before_oversized_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "small"
            path.write_bytes(b"12345")
            self.assertEqual(evidence._read(path, 5), b"12345")
            with self.assertRaises(EvidenceError):
                evidence._read(path, 4)


if __name__ == "__main__":
    unittest.main()

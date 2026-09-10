"""Replay every fixed catalog operation and the actual ownership checkpoints."""
from pathlib import Path

from tools.optimization_backend_revision.cache.accounting import runtime
from tools.optimization_backend_revision.engine.measurements import cpu, cpu_delta
from tools.optimization_backend_revision.engine.resources import memory
from tools.optimization_evidence.common import canonical, distribution, fields, require, uint
from tools.phase1_evidence.resources import Samples, idle, shutdown
from . import data, model, oracle, policy, sampler

HEADER = ("schema plan identity plan_sha256 identity_sha256 fixture_template configuration startup clock data_identity reopen_receipt "
          "population bounds configured_runtimes before_node_memory effective_engine samples status reason work operations shutdown "
          "runtime_threads_after_join catalog_owners_released data_identity_after_shutdown final_preparation final_compiler "
          "final_runtime_accounting final_verification sampler after_shutdown_memory elapsed_nanos")
CHECKPOINT = "kind label count old_pin node verification compiler accounting preparation cleanup memory cpu"


def decimals(value):
    if type(value) is int:
        return str(value)
    if isinstance(value, dict):
        return {key: decimals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decimals(item) for item in value]
    return value


class Replay:
    def __init__(self, value, selected, identity, fixture):
        self.value, self.selected, self.identity, self.fixture = value, selected, identity, fixture
        self.elapsed = uint(value["elapsed_nanos"])
        self.rows = value["samples"]
        require(isinstance(self.rows, list) and len(self.rows) <= model.MAX_SAMPLES
                and all(isinstance(row, dict) and len(canonical(row)) <= model.MAX_ROW_BYTES for row in self.rows),
                "catalog-raw-row-bound")
        self.position = self.clock = self.generation = 0
        self.operations = oracle.Operations()
        self.nodes = Samples()
        self.checkpoints, self.resolves, self.applies, self.proofs, self.anchors = [], [], [], [], []
        self.published = self.metadata_reads = 0
        if selected["mode"] == "reopen":
            self.generation = len(model.scales(selected["profile"])) + 1
            self.published = self.metadata_reads = model.scales(selected["profile"])[-1]

    def take(self, kind, names):
        require(self.position < len(self.rows), "catalog-missing-planned-row")
        row = self.rows[self.position]
        self.position += 1
        fields(row, "kind " + names)
        require(row["kind"] == kind, "catalog-row-order")
        return row

    def window(self, row):
        start, finish = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(self.clock <= start <= finish <= self.elapsed, "catalog-operation-clock")
        self.clock = finish
        return start, finish

    def verification(self):
        reads = self.published + self.metadata_reads
        return {"full_fetch_attempts": "0", "metadata_fetch_attempts": str(self.metadata_reads),
                "component_verification_attempts": str(reads),
                "component_bytes_hashed": str(reads * (len(self.fixture.base) + 31)),
                "metadata_fingerprint_attempts": str(self.published)}

    def checkpoint(self, label, count, old_pin=False):
        row = self.take("checkpoint", CHECKPOINT.removeprefix("kind "))
        require(row["label"] == label and row["count"] == str(count) and row["old_pin"] is old_pin,
                "catalog-checkpoint-identity")
        node = row["node"]
        self.nodes.check(node)
        idle(node, dormant=True)
        start, finish = uint(node["started_micros"]) * 1000, uint(node["finished_micros"]) * 1000
        require(self.clock <= start + 999 and finish <= self.elapsed, "catalog-checkpoint-clock")
        inventory = node["inventory"]
        cells = inventory["cellCapacity"]
        require(node["label"] == label and inventory["nodeId"] == "catalog-comparison"
                and inventory["routeGeneration"] == str(self.generation) and len(cells) == 1
                and cells[0]["class"] == "standard" and cells[0]["total"] == 2
                and cells[0]["queueCapacity"] == 3 and cells[0]["quarantined"] == 0
                and node["resources"]["descendants"] == [], "catalog-node-generation-or-ownership")
        require(node["work"] == {"commands": str(self.operations.commands), "invoke_attempts": "0", "budget_exhausted": False},
                "catalog-node-command-counter")
        require(node["ownership"]["journal"]["maximum_retained_bytes"] == "20971520"
                and node["ownership"]["journal"]["maximum_terminal"] == "64", "catalog-retention-controls")
        require(row["verification"] == self.verification(), "catalog-verification-checkpoint")
        policy.accounting(row["accounting"], node)
        policy.cleanup(row["cleanup"])
        self.anchors.append(policy.preparation(row["preparation"], finish, self.elapsed))
        require(row["compiler"] == row["preparation"]["snapshot"]["compiler"], "catalog-compiler-projection-crossed")
        observed = memory(row["memory"], label, self.nodes.identity,
                          uint(row["preparation"]["collector_finished_nanos"]), self.elapsed,
                          operating_system=self.identity["environment"]["os"])
        cpu(row["cpu"], self.nodes.identity, uint(row["memory"]["collector_finished_nanos"]), self.elapsed)
        self.clock = uint(row["cpu"]["collector_finished_nanos"]) if row["cpu"] is not None else uint(row["memory"]["collector_finished_nanos"])
        self.checkpoints.append({**row, "memory_values": observed})
        return row

    def publish(self, first, count):
        for begin in range(first, count, 256):
            amount = min(256, count - begin)
            row = self.take("publication-chunk", "first planned_count completed started_nanos finished_nanos digest failure")
            self.window(row)
            require(row["first"] == str(begin) and row["planned_count"] == row["completed"] == str(amount)
                    and row["failure"] is None
                    and row["digest"] == self.fixture.publication_digest(begin, amount, self.selected["shape"]),
                    "catalog-publication-chunk-digest")
            self.operations.add("publications", count=amount)
            self.published += amount

    def apply(self, previous, count):
        row = self.take("apply", "mode first count generation_before started_nanos finished_nanos verification_before verification_after result")
        self.window(row)
        require(row["mode"] == "growth" and row["first"] == str(previous) and row["count"] == str(count - previous)
                and row["generation_before"] == str(self.generation) and row["verification_before"] == self.verification(),
                "catalog-growth-apply-input")
        self.operations.add("applies")
        self.metadata_reads += count
        self.generation += 1
        require(row["result"] == {"generation": str(self.generation)} and row["verification_after"] == self.verification(),
                "catalog-growth-apply-result")
        self.applies.append(dict(row))

    def normal(self, count):
        expected = oracle.Oracle(self.fixture, count, self.selected["shape"], self.generation)
        for case, samples in model.case_counts(self.selected["profile"]).items():
            elapsed_values, windows = [], []
            for first in range(0, samples, 128):
                amount = min(128, samples - first)
                row = self.take("resolve-chunk", "count case first started_nanos finished_nanos observations")
                start, finish = self.window(row)
                require(row["count"] == str(count) and row["case"] == case and row["first"] == str(first)
                        and isinstance(row["observations"], list) and len(row["observations"]) == amount,
                        "catalog-resolve-chunk-population")
                lengths = []
                for sample, observed in enumerate(row["observations"], first):
                    succeeded = expected.check(observed, case, sample, extra="ordinal index elapsed_nanos")
                    self.operations.add("resolves", succeeded, ordinal=observed["ordinal"])
                    lengths.append(uint(observed["elapsed_nanos"]))
                require(sum(lengths) <= finish - start, "catalog-resolve-latencies-outside-batch")
                elapsed_values.extend(lengths)
                windows.append(finish - start)
            self.resolves.append({"count": str(count), "case": case, "attempts": str(samples),
                "returned_ok": str(samples if case.endswith("success") else 0),
                "returned_error": str(0 if case.endswith("success") else samples),
                "elapsed_nanos": distribution(elapsed_values), "chunk_elapsed_nanos": distribution(windows),
                "boundary": "directory-deployment-resolver.resolve-to-return-before-validation-and-drop"})

    def proof(self, label, operation, expected, *, succeeded=True):
        row = self.take("proof-operation", "label operation ordinal started_nanos finished_nanos " + next(iter(expected)))
        self.window(row)
        require(row["label"] == label and row["operation"] == operation
                and all(row[key] == value for key, value in expected.items()), "catalog-pin-policy-proof")
        self.operations.add({"pin": "pins", "resolve": "resolves", "policy": "policies", "apply": "applies"}[operation],
                            succeeded, ordinal=row["ordinal"])
        self.proofs.append(row)
        return row

    def policy_result(self):
        template = self.fixture.template()
        return {"result": decimals({"deployment_ceiling": template["deployment"]["spec"]["resources"],
                                    "execution": template["capsule"]["execution"],
                                    "placement": template["deployment"]["spec"]["placement"]})}

    def update(self, count):
        before = oracle.Oracle(self.fixture, 1, self.selected["shape"], self.generation).outcome("named-success", 0)
        self.proof("update-old-pin", "pin", {"result": {"generation": str(self.generation)}})
        self.proof("update-old-resolve-before", "resolve", before)
        self.proof("update-old-policy-before", "policy", self.policy_result())
        self.generation += 1
        applied = self.proof("update-apply", "apply", {"result": {"generation": str(self.generation)}})
        self.applies.append({**applied, "mode": "weight-update", "catalog_count": str(count)})
        self.metadata_reads += count
        self.proof("update-old-resolve-after", "resolve", before)
        self.proof("update-old-policy-after", "policy", self.policy_result())
        self.proof("update-new-pin", "pin", {"result": {"generation": str(self.generation)}})
        after = oracle.Oracle(self.fixture, 1, self.selected["shape"], self.generation, updated=True).outcome("named-success", 0)
        self.proof("update-new-resolve", "resolve", after)
        self.proof("update-new-policy", "policy", self.policy_result())
        self.checkpoint("old-pin-overlap", count, True)
        self.checkpoint("old-pin-released", count)

    def reopen(self, count):
        self.checkpoint("reopened-idle", count)
        expected = oracle.Oracle(self.fixture, count, self.selected["shape"], self.generation, updated=True)
        self.proof("reopen-pin", "pin", {"result": {"generation": str(self.generation)}})
        for case, label, policy_label in (("default-success", "reopen-default-resolve", "reopen-default-policy"),
                ("named-success", "reopen-named-resolve", "reopen-named-policy"),
                ("route-miss", "reopen-route-miss", None), ("export-miss", "reopen-export-miss", None)):
            self.proof(label, "resolve", expected.outcome(case, 0), succeeded=case.endswith("success"))
            if policy_label:
                self.proof(policy_label, "policy", self.policy_result())
        self.checkpoint("reopened-output-released", count)

    def allocation(self):
        case = self.selected["case"]
        expected = oracle.Oracle(self.fixture, 16, self.selected["shape"], 1)
        preflight = expected.outcome(case, 0)
        row = self.take("allocation-preflight", "case count index ordinal started_nanos finished_nanos " + next(iter(preflight)))
        self.window(row)
        require(row["case"] == case and row["count"] == "16", "catalog-allocation-preflight-case")
        succeeded = expected.check(row, case, 0, extra="kind case count index ordinal started_nanos finished_nanos")
        self.operations.add("resolves", succeeded, ordinal=row["ordinal"])
        row = self.take("allocation-frame", "case count index key symbol preflight_calls preflight warmup_attempted warmup_returned_ok "
            "warmup_returned_error warmup_validated frame_invocations samples attempted returned_ok returned_error validated contained_calls "
            "full_result_equality started_nanos finished_nanos")
        self.window(row)
        samples = model.counts(self.selected["profile"], "allocation")["measured_resolves"]
        require(row["case"] == case and row["count"] == "16" and row["index"] == "0" and row["key"] == "catalog-key-00000"
                and row["symbol"] == model.SYMBOLS[case].split("::")[-1] and row["preflight_calls"] == "1"
                and row["preflight"] == preflight and row["frame_invocations"] == "1" and row["full_result_equality"] is True,
                "catalog-allocation-frame-boundary")
        require(all(row[key] == "16" for key in ("warmup_attempted", "warmup_validated"))
                and row["warmup_returned_ok"] == ("16" if succeeded else "0")
                and row["warmup_returned_error"] == ("0" if succeeded else "16")
                and all(row[key] == str(samples) for key in ("samples", "attempted", "validated", "contained_calls"))
                and row["returned_ok"] == str(samples if succeeded else 0)
                and row["returned_error"] == str(0 if succeeded else samples), "catalog-allocation-frame-population")
        self.operations.add("resolves", succeeded, count=16 + samples)
        return row


def parse(value, selected, identity, fixture, record, artifacts):
    fields(value, HEADER)
    require(value["schema"] == "latent.optimization.catalog-arm.v1" and value["plan"] == selected and value["identity"] == identity
            and value["status"] == "passed" and value["reason"] is None, "catalog-raw-not-qualified")
    require(value["plan_sha256"] == record["plan"]["sha256"] and value["identity_sha256"] == record["identity"]["sha256"]
            and value["fixture_template"] == fixture.template(), "catalog-input-or-fixture-binding")
    policy.configuration(value["configuration"], selected)
    policy.engine(value["effective_engine"], identity)
    expected = model.counts(selected["profile"], selected["mode"])
    require(value["population"] == {key: str(expected[key]) for key in ("commands", "invokes", "publications", "applies", "resolves", "pins", "policies")}
            and value["work"] == {"commands": str(expected["commands"]), "invoke_attempts": "0", "budget_exhausted": False},
            "catalog-raw-operation-population")
    require(value["bounds"] == {"arm_seconds": str(model.run_seconds(selected["profile"], selected["mode"])), "raw_bytes": "33554432",
                               "raw_records": "2048", "raw_record_bytes": "262144", "publication_chunk": "256", "resolve_chunk": "128"},
            "catalog-source-bounds")
    policy.owners(value["configured_runtimes"], value["runtime_threads_after_join"], value["catalog_owners_released"])
    data.validate_identity(value["data_identity"], selected, identity["source"]["commit"])
    require(value["data_identity_after_shutdown"] == value["data_identity"]
            and value["data_identity"]["marker"] == artifacts.json(record["data_owner"]), "catalog-data-owner-crossed")
    require(value["reopen_receipt"] == (None if record["reopen_input"] is None else artifacts.json(record["reopen_input"])),
            "catalog-reopen-input-crossed")
    fields(value["clock"], "unix_origin_nanos clock_anchor_uncertainty_nanos")
    for item in value["clock"].values():
        uint(item)
    elapsed = uint(value["elapsed_nanos"])
    require(elapsed <= model.run_seconds(selected["profile"], selected["mode"]) * 10**9, "catalog-source-time-bound")
    startup = fields(value["startup"], "catalog_open_nanos node_start_nanos client_connect_nanos excluded comparable_to_historical_startup")
    require(startup["excluded"] == ["fixture-loading", "runtime-construction"] and startup["comparable_to_historical_startup"] is False,
            "catalog-startup-scope")
    for key in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        require(uint(startup[key]) <= elapsed, "catalog-startup-bound")
    state = Replay(value, selected, identity, fixture)
    count = 16 if selected["mode"] == "allocation" else model.scales(selected["profile"])[-1]
    frame = None
    if selected["mode"] == "reopen":
        state.reopen(count)
    else:
        state.checkpoint("empty", 0)
        previous = 0
        for current in ([16] if selected["mode"] == "allocation" else model.scales(selected["profile"])):
            state.publish(previous, current)
            state.checkpoint("artifact-only", current)
            state.apply(previous, current)
            state.checkpoint("post-publication-idle", current)
            if selected["mode"] == "allocation":
                frame = state.allocation()
            else:
                state.normal(current)
            state.checkpoint("after-resolver-output-drop", current)
            previous = current
        if selected["mode"] == "initial":
            state.update(count)
    state.checkpoint("before-shutdown", count)
    require(state.position == len(state.rows), "catalog-unplanned-row")
    state.operations.complete(value["operations"], expected)
    require(value["final_verification"] == state.verification(), "catalog-final-verification")
    owner = state.nodes.identity
    before = memory(value["before_node_memory"], "before-node", owner, 0,
                    uint(state.checkpoints[0]["node"]["started_micros"]) * 1000 + 999, operating_system=identity["environment"]["os"])
    state.anchors.append(policy.preparation(value["final_preparation"], state.clock, elapsed, final=True))
    require(max(low for low, _ in state.anchors) <= min(high for _, high in state.anchors), "catalog-preparation-origin-crossed")
    final_compiler = policy.compiler(value["final_compiler"], final=True)
    require(value["final_preparation"]["snapshot"]["compiler"] == value["final_compiler"], "catalog-final-compiler-crossed")
    shutdown(value["shutdown"], cells=2)
    require(value["shutdown"]["quarantinedCells"] == 0 and value["shutdown"]["compiler"] == final_compiler, "catalog-final-quarantine-or-compiler")
    policy.cleanup(value["shutdown"]["cleanup"], final=True)
    runtime(value["final_runtime_accounting"], "candidate", zero=True)
    after = memory(value["after_shutdown_memory"], "after-shutdown", owner,
                   uint(value["final_preparation"]["collector_finished_nanos"]), elapsed, operating_system=identity["environment"]["os"])
    sampled = sampler.validate(value["sampler"], selected["mode"], artifacts,
                               artifacts.path(record["raw"]).parent, owner, elapsed,
                               uint(value["before_node_memory"]["collector_started_nanos"]),
                               uint(value["final_preparation"]["collector_started_nanos"]))
    for row in state.applies:
        row["sampled_memory"] = sampler.phase(sampled, uint(row["started_nanos"]), uint(row["finished_nanos"])) if sampled else None
    return {"validated_commands": str(expected["commands"]), "validated_resolves": str(expected["resolves"]),
            "validated_invocations": "0", "attempt_count_complete": True, "elapsed_nanos": str(elapsed),
            "process_identity": list(owner), "operations": value["operations"], "startup": startup,
            "effective_engine": value["effective_engine"], "data_identity": value["data_identity"],
            "checkpoints": state.checkpoints, "resolves": state.resolves, "applies": state.applies, "proofs": state.proofs,
            "allocation_frame": frame, "sampler": value["sampler"], "before_node_memory": before, "after_shutdown_memory": after,
            "normal_cpu_ticks": cpu_delta(state.checkpoints[0]["cpu"], state.checkpoints[-1]["cpu"]),
            "shutdown": value["shutdown"], "final_verification": value["final_verification"]}

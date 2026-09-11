"""Replay the fixed public mutations, receipts, pins and observed work owners."""
from tools.optimization_backend_revision.cache.accounting import runtime
from tools.optimization_backend_revision.engine.measurements import cpu, cpu_delta
from tools.optimization_backend_revision.engine.resources import memory
from tools.optimization_evidence.common import canonical, fields, require, uint
from tools.phase1_evidence.resources import Samples, idle, shutdown
from . import data, model, oracle, policy, sampler

CHECKPOINT = "kind label count old_pin node verification compiler accounting preparation cleanup memory cpu"
WORK = "observer_before observer_after verification_before verification_after cpu_before cpu_after"
HEADER = ("schema plan identity plan_sha256 identity_sha256 fixture_template configuration startup clock opening "
          "data_identity reopen_receipt population bounds configured_runtimes before_node_memory effective_engine samples "
          "status reason work operations shutdown runtime_threads_after_join catalog_owners_released "
          "data_identity_after_shutdown final_preparation final_compiler final_runtime_accounting final_verification "
          "final_catalog_work sampler after_shutdown_memory elapsed_nanos")


def frame(value, case, mode):
    if not model.profiled(mode):
        require(value is None, "catalog-mutation-normal-used-profile-frame")
        return None
    fields(value, "case poll_calls drop_calls catalog_moved_to_node")
    reopened = model.is_reopen(mode)
    require(value["case"] == case and 1 <= uint(value["poll_calls"]) <= 2**64 - 1
            and value["drop_calls"] == ("0" if reopened else "1")
            and value["catalog_moved_to_node"] is reopened,
            "catalog-mutation-profile-frame-ownership")
    return {**value, "symbol": model.SYMBOLS[case]}


class Replay:
    def __init__(self, value, selected, identity, fixture):
        self.value, self.selected, self.identity, self.fixture = value, selected, identity, fixture
        self.elapsed = uint(value["elapsed_nanos"])
        self.rows = value["samples"]
        require(isinstance(self.rows, list) and len(self.rows) <= model.MAX_SAMPLES
                and all(isinstance(row, dict) and len(canonical(row)) <= model.MAX_ROW_BYTES for row in self.rows),
                "catalog-mutation-raw-row-bound")
        self.position = self.clock = self.generation = 0
        self.operations, self.nodes = oracle.Operations(), Samples()
        self.checkpoints, self.mutations, self.proofs, self.anchors, self.frames = [], [], [], [], []
        self.seed = None
        self.published = self.metadata_reads = 0
        if model.is_reopen(selected["mode"]):
            self.generation = 5
            self.published = self.metadata_reads = selected["populated_size"]
        self.observer = value["opening"]["observer_after"]
        self.opening_verification = self.verification()
        self.clock = uint(value["opening"]["cpu_after"]["collector_finished_nanos"]) if value["opening"]["cpu_after"] is not None else uint(value["opening"]["finished_nanos"])
        self.expected = oracle.Oracle(fixture, selected["populated_size"], selected["shape"])

    def take(self, kind, names):
        require(self.position < len(self.rows), "catalog-mutation-missing-planned-row")
        row = self.rows[self.position]
        self.position += 1
        fields(row, "kind " + names)
        require(row["kind"] == kind, "catalog-mutation-row-order")
        return row

    def window(self, row):
        start, finish = uint(row["started_nanos"]), uint(row["finished_nanos"])
        require(self.clock <= start <= finish <= self.elapsed, "catalog-mutation-operation-clock")
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
                "catalog-mutation-checkpoint-identity")
        node = row["node"]
        self.nodes.check(node)
        idle(node, dormant=True)
        start, finish = uint(node["started_micros"]) * 1000, uint(node["finished_micros"]) * 1000
        require(self.clock <= start + 999 and finish <= self.elapsed, "catalog-mutation-checkpoint-clock")
        inventory, cells = node["inventory"], node["inventory"]["cellCapacity"]
        require(inventory["nodeId"] == "catalog-mutation-comparison" and node["label"] == label
                and inventory["routeGeneration"] == str(self.generation) and len(cells) == 1
                and cells[0]["class"] == "standard" and cells[0]["total"] == 2
                and cells[0]["queueCapacity"] == 3 and cells[0]["quarantined"] == 0
                and node["resources"]["descendants"] == [], "catalog-mutation-native-ownership")
        require(node["work"] == {"commands": str(self.operations.commands), "invoke_attempts": "0", "budget_exhausted": False}
                and node["ownership"]["journal"]["maximum_retained_bytes"] == "20971520"
                and node["ownership"]["journal"]["maximum_terminal"] == "64", "catalog-mutation-command-or-retention")
        require(row["verification"] == self.verification(), "catalog-mutation-verification-checkpoint")
        policy.accounting(row["accounting"], node)
        policy.cleanup(row["cleanup"])
        self.anchors.append(policy.preparation(row["preparation"], finish, self.elapsed))
        require(row["compiler"] == row["preparation"]["snapshot"]["compiler"], "catalog-mutation-compiler-projection")
        observed = memory(row["memory"], label, self.nodes.identity,
                          uint(row["preparation"]["collector_finished_nanos"]), self.elapsed,
                          operating_system=self.identity["environment"]["os"])
        cpu(row["cpu"], self.nodes.identity, uint(row["memory"]["collector_finished_nanos"]), self.elapsed)
        self.clock = uint((row["cpu"] or row["memory"])["collector_finished_nanos"])
        self.checkpoints.append({**row, "memory_values": observed})

    def publish(self):
        count = self.selected["populated_size"]
        for first in range(0, count, 256):
            amount = min(256, count - first)
            row = self.take("publication-chunk", "first_ordinal last_ordinal first planned_count completed started_nanos finished_nanos digest failure")
            self.window(row)
            require(row["first"] == str(first) and row["planned_count"] == row["completed"] == str(amount)
                    and row["first_ordinal"] == str(self.operations.commands + 1)
                    and row["last_ordinal"] == str(self.operations.commands + amount) and row["failure"] is None
                    and row["digest"] == self.fixture.publication_digest(first, amount, self.selected["shape"]),
                    "catalog-mutation-publication-digest")
            self.operations.add("publications", count=amount)
            self.published += amount

    def observed(self, row, operation, generation, normalization):
        require(row["observer_before"] == self.observer and row["verification_before"] == self.verification(),
                "catalog-mutation-work-before-association")
        lower = self.clock
        start, finish = self.window(row)
        cpu(row["cpu_before"], self.nodes.identity, lower, start)
        cpu(row["cpu_after"], self.nodes.identity, finish, self.elapsed)
        work = policy.work_operation(row["observer_before"], row["observer_after"], operation,
                                     generation, normalization=normalization)
        self.observer = row["observer_after"]
        self.generation = generation
        self.metadata_reads += self.selected["populated_size"] - int(operation == "delete-versioned")
        require(row["verification_after"] == self.verification(), "catalog-mutation-work-after-verification")
        self.clock = uint(row["cpu_after"]["collector_finished_nanos"]) if row["cpu_after"] is not None else finish
        return {**row, "work_counts": work, "cpu_ticks": cpu_delta(row["cpu_before"], row["cpu_after"]),
                "cpu_scope": "before-public-future-construction-through-result-return-before-projection-and-drop", "sampled_memory": None}

    def seed_call(self):
        row = self.take("seed", "ordinal count generation_before started_nanos finished_nanos outcome " + WORK)
        count = self.selected["populated_size"]
        require(row["count"] == str(count) and row["generation_before"] == "0"
                and row["outcome"] == {"result": {"generation": "1"}}, "catalog-mutation-seed-result")
        self.operations.add("seed_batches", ordinal=row["ordinal"])
        self.seed = self.observed(row, "apply-many", 1, count)

    def mutation(self, index, label):
        row = self.take("mutation", "label ordinal expected_generation generation_before started_nanos finished_nanos outcome allocation_frame " + WORK)
        require(row["label"] == label and row["generation_before"] == str(index + 1)
                and row["expected_generation"] == ("0" if label == "reapply" else str(index + 1))
                and row["outcome"] == self.expected.mutation(label), "catalog-mutation-public-receipt")
        self.operations.add("deletes" if label == "delete" else "applies", ordinal=row["ordinal"])
        value = self.observed(row, "delete-versioned" if label == "delete" else "apply-versioned", index + 2,
                              0 if label == "delete" else 1)
        selected_frame = frame(row["allocation_frame"], label, self.selected["mode"])
        if selected_frame is not None:
            self.frames.append(selected_frame)
        self.mutations.append(value)

    def proof(self, label, operation, outcome, route=None):
        row = self.take("proof-operation", "label operation ordinal started_nanos finished_nanos "
                        + next(iter(outcome)) + (" target routing_key" if operation == "resolve" else ""))
        self.window(row)
        require(row["label"] == label and row["operation"] == operation
                and all(row[key] == value for key, value in outcome.items()), "catalog-mutation-public-proof")
        if operation == "resolve":
            require(row["target"] == self.expected.target(route) and row["routing_key"] == oracle.KEY,
                    "catalog-mutation-proof-target")
        self.operations.add({"get": "gets", "resolve": "resolves", "policy": "policies", "pin": "pins"}[operation],
                            "error" not in outcome, ordinal=row["ordinal"])
        self.proofs.append(row)

    def initial(self):
        count = self.selected["populated_size"]
        self.checkpoint("empty", 0)
        self.publish()
        self.checkpoint("artifact-only", count)
        self.seed_call()
        self.checkpoint("post-seed-idle", count)
        self.checkpoint("oracle-released", count)
        self.proof("old-pin", "pin", {"result": {"generation": "1"}})
        for index, label in enumerate(model.MUTATIONS):
            self.mutation(index, label)
            self.proof(label + "/get", "get", self.expected.get(label))
            self.proof(label + "/old-named", "resolve", self.expected.resolved("seed", "named"), "named")
            self.proof(label + "/old-policy", "policy", self.expected.policy())
            self.proof(label + "/current-pin", "pin", {"result": {"generation": str(index + 2)}})
            for route in ("named", "default"):
                outcome = self.expected.resolved(label, route)
                self.proof(label + "/current-" + route, "resolve", outcome, route)
                if "error" not in outcome:
                    self.proof(label + "/current-" + route + "-policy", "policy", self.expected.policy())
            self.checkpoint(label, count - int(label == "delete"), True)
        self.checkpoint("overlap-before-pin-drop", count, True)
        self.checkpoint("pin-released", count)

    def reopen(self):
        count = self.selected["populated_size"]
        self.checkpoint("reopened-idle", count)
        self.checkpoint("oracle-released", count)
        self.proof("reopen-get", "get", self.expected.get("reapply"))
        self.proof("reopen-pin", "pin", {"result": {"generation": "5"}})
        for route in ("named", "default"):
            self.proof("reopen-" + route, "resolve", self.expected.resolved("reapply", route), route)
            self.proof("reopen-" + route + "-policy", "policy", self.expected.policy())
        self.checkpoint("reopened-output-released", count)


def opening(value, state):
    row = fields(value["opening"], "started_nanos finished_nanos cpu_before cpu_after observer_before observer_after returned_ok error allocation_frame verification_after")
    start, finish = uint(row["started_nanos"]), uint(row["finished_nanos"])
    require(uint(value["before_node_memory"]["collector_finished_nanos"]) <= start <= finish <= state.elapsed
            and row["returned_ok"] is True and row["error"] is None
            and value["startup"]["catalog_open_nanos"] == str(finish - start), "catalog-mutation-opening-boundary")
    policy.work_snapshot(row["observer_before"], sequence=0)
    work = policy.work_operation(row["observer_before"], row["observer_after"], "open",
                                 5 if model.is_reopen(state.selected["mode"]) else 0, normalization=0)
    require(row["verification_after"] == state.opening_verification, "catalog-mutation-opening-verification")
    cpu(row["cpu_before"], state.nodes.identity, uint(value["before_node_memory"]["collector_finished_nanos"]), start)
    cpu(row["cpu_after"], state.nodes.identity, finish, uint(state.checkpoints[0]["node"]["started_micros"]) * 1000 + 999)
    if state.selected["mode"] == "allocation-reopen":
        state.frames.append(frame(row["allocation_frame"], "reopen", state.selected["mode"]))
    else:
        require(row["allocation_frame"] is None, "catalog-mutation-unplanned-opening-frame")
    return {**row, "work_counts": work, "cpu_ticks": cpu_delta(row["cpu_before"], row["cpu_after"]),
            "cpu_scope": "actual-repository-opening-before-node-construction", "sampled_memory": None}


def parse(value, selected, identity, fixture, record, artifacts):
    fields(value, HEADER)
    require(value["schema"] == "latent.optimization.catalog-mutation-arm.v1" and value["plan"] == selected
            and value["identity"] == identity and value["status"] == "passed" and value["reason"] is None,
            "catalog-mutation-raw-not-qualified")
    require(value["plan_sha256"] == record["plan"]["sha256"] and value["identity_sha256"] == record["identity"]["sha256"]
            and value["fixture_template"] == fixture.template(), "catalog-mutation-input-or-fixture-binding")
    policy.configuration(value["configuration"], selected)
    policy.engine(value["effective_engine"], identity)
    expected = model.counts(selected["profile"], selected["mode"], selected["shape"], selected["populated_size"])
    require(value["population"] == {key: str(amount) for key, amount in expected.items()}
            and value["work"] == {"commands": str(expected["commands"]), "invoke_attempts": "0", "budget_exhausted": False},
            "catalog-mutation-raw-operation-population")
    require(value["bounds"] == {"arm_seconds": str(model.run_seconds(selected["profile"], selected["mode"])),
            "raw_bytes": "33554432", "raw_records": "2048", "raw_record_bytes": "262144", "publication_chunk": "256"},
            "catalog-mutation-source-bounds")
    policy.owners(value["configured_runtimes"], value["runtime_threads_after_join"], value["catalog_owners_released"])
    data.validate_identity(value["data_identity"], selected, identity["source"]["commit"])
    require(value["data_identity_after_shutdown"] == value["data_identity"]
            and value["data_identity"]["marker"] == artifacts.json(record["data_owner"]), "catalog-mutation-data-owner-crossed")
    require(value["reopen_receipt"] == (None if record["reopen_input"] is None else artifacts.json(record["reopen_input"])),
            "catalog-mutation-reopen-input-crossed")
    fields(value["clock"], "unix_origin_nanos clock_anchor_uncertainty_nanos")
    for item in value["clock"].values():
        uint(item)
    elapsed = uint(value["elapsed_nanos"])
    require(elapsed <= model.run_seconds(selected["profile"], selected["mode"]) * 10**9, "catalog-mutation-source-time-bound")
    startup = fields(value["startup"], "catalog_open_nanos node_start_nanos client_connect_nanos excluded comparable_to_historical_startup")
    require(startup["excluded"] == ["fixture-loading", "runtime-construction"]
            and startup["comparable_to_historical_startup"] is False, "catalog-mutation-startup-scope")
    for key in ("catalog_open_nanos", "node_start_nanos", "client_connect_nanos"):
        require(uint(startup[key]) <= elapsed, "catalog-mutation-startup-time-bound")
    state = Replay(value, selected, identity, fixture)
    state.reopen() if model.is_reopen(selected["mode"]) else state.initial()
    state.checkpoint("before-shutdown", selected["populated_size"])
    require(state.position == len(state.rows), "catalog-mutation-unplanned-row")
    state.operations.complete(value["operations"], expected)
    require(value["final_verification"] == state.verification() and value["final_catalog_work"] == state.observer,
            "catalog-mutation-final-observer-association")
    policy.work_snapshot(value["final_catalog_work"], sequence=1 if model.is_reopen(selected["mode"]) else 6)
    opened = opening(value, state)
    require(len(state.frames) == (1 if model.is_reopen(selected["mode"]) else 4) if model.profiled(selected["mode"])
            else not state.frames, "catalog-mutation-frame-population")
    owner = state.nodes.identity
    before = memory(value["before_node_memory"], "before-node", owner, 0,
                    uint(value["opening"]["started_nanos"]), operating_system=identity["environment"]["os"])
    state.anchors.append(policy.preparation(value["final_preparation"], state.clock, elapsed, final=True))
    require(max(low for low, _ in state.anchors) <= min(high for _, high in state.anchors), "catalog-mutation-preparation-origin")
    final_compiler = policy.compiler(value["final_compiler"], final=True)
    require(value["final_preparation"]["snapshot"]["compiler"] == value["final_compiler"], "catalog-mutation-final-compiler")
    shutdown(value["shutdown"], cells=2)
    require(value["shutdown"]["quarantinedCells"] == 0 and value["shutdown"]["compiler"] == final_compiler,
            "catalog-mutation-final-quarantine-or-compiler")
    policy.cleanup(value["shutdown"]["cleanup"], final=True)
    runtime(value["final_runtime_accounting"], "candidate", zero=True)
    after = memory(value["after_shutdown_memory"], "after-shutdown", owner,
                   uint(value["final_preparation"]["collector_finished_nanos"]), elapsed,
                   operating_system=identity["environment"]["os"])
    sampled = sampler.validate(value["sampler"], selected["mode"], artifacts, artifacts.path(record["raw"]).parent,
        owner, elapsed, uint(value["before_node_memory"]["collector_started_nanos"]),
        uint(value["final_preparation"]["collector_started_nanos"]))
    for row in [opened, *([state.seed] if state.seed is not None else []), *state.mutations]:
        row["sampled_memory"] = sampler.phase(sampled, uint(row["started_nanos"]), uint(row["finished_nanos"])) if sampled else None
    return {"validated_commands": str(expected["commands"]), "validated_resolves": str(expected["resolves"]),
            "validated_invocations": "0", "validated_mutations": str(expected["measured_mutations"]),
            "validated_reopens": str(expected["reopen_observations"]), "attempt_count_complete": True,
            "elapsed_nanos": str(elapsed), "process_identity": list(owner), "operations": value["operations"],
            "startup": startup, "opening": opened, "seed": state.seed, "mutations": state.mutations, "proofs": state.proofs,
            "allocation_frames": state.frames, "effective_engine": value["effective_engine"], "data_identity": value["data_identity"],
            "checkpoints": state.checkpoints, "sampler": value["sampler"], "before_node_memory": before,
            "after_shutdown_memory": after, "shutdown": value["shutdown"], "final_verification": value["final_verification"],
            "final_observer": value["final_catalog_work"]}

"""Replay immutable stage records and actual CPU ticks without timing inference."""
from tools.optimization_evidence.common import fields, integer, require, uint
from tools.phase1_compiler_shutdown import FIELDS, validate_compiler_shutdown

STAGES = ("repository_fetch_verified", "metadata_validation", "component_new", "surface_link",
          "cache_adoption", "whole_job", "queue_wait")


class Observer:
    def __init__(self, pid, digests, variant):
        self.pid, self.digests, self.variant = pid, digests, variant
        self.records, self.jobs, self.last = {}, {}, None
        self.anchors = []

    def check(self, value, final=False):
        fields(value, "collector_started_nanos collector_finished_nanos snapshot")
        began, finished = uint(value["collector_started_nanos"]), uint(value["collector_finished_nanos"])
        require(began <= finished, "cold-observer-clock-window")
        current = value["snapshot"]
        fields(current, "enabled revision observed_nanos maximum_running_entries maximum_stage_observations active_jobs "
               "dropped_running_entries dropped_stage_observations compiler stages running recent_stages")
        require(current["enabled"] is True and current["maximum_running_entries"] == "4"
                and current["maximum_stage_observations"] == "256"
                and current["dropped_running_entries"] == current["dropped_stage_observations"] == "0", "cold-observation-loss")
        require(uint(current["active_jobs"]) <= 4, "cold-active-job-bound")
        offset = uint(current["observed_nanos"])
        self.anchors.append((began - offset, finished - offset))
        require(max(low for low, _ in self.anchors) <= min(high for _, high in self.anchors), "cold-observer-origin-inconsistent")
        require(isinstance(current["stages"], list) and [row["stage"] for row in current["stages"]] == list(STAGES), "cold-stage-manifest")
        for row in current["stages"]:
            fields(row, "stage started completed failed elapsed_nanos thread_cpu_samples thread_cpu_unavailable thread_cpu_user_ticks thread_cpu_system_ticks")
            values = {key: uint(item) for key, item in row.items() if key != "stage"}
            require(values["completed"] + values["failed"] <= values["started"]
                    and values["thread_cpu_samples"] + values["thread_cpu_unavailable"] == values["completed"] + values["failed"], "cold-stage-counter-inconsistent")
        require(isinstance(current["running"], list) and len(current["running"]) <= 4, "cold-running-record-bound")
        for row in current["running"]:
            fields(row, "job_id component_digest stage started_nanos thread")
            self.job(row)
            require(row["stage"] in STAGES and uint(row["started_nanos"]) <= offset, "cold-running-stage-window")
            if row["thread"] is not None:
                self.thread(row["thread"])
        require(isinstance(current["recent_stages"], list) and len(current["recent_stages"]) <= 256, "cold-stage-record-bound")
        prior = -1
        for row in current["recent_stages"]:
            fields(row, "sequence job_id component_digest stage started_nanos finished_nanos succeeded thread_cpu")
            sequence = uint(row["sequence"])
            require(prior < sequence and row["stage"] in STAGES and type(row["succeeded"]) is bool, "cold-stage-order")
            prior = sequence
            self.job(row)
            require(uint(row["started_nanos"]) <= uint(row["finished_nanos"]) <= offset, "cold-stage-window")
            if row["thread_cpu"] is not None:
                require(row["stage"] != "queue_wait",
                        "cold-cross-thread-stage-claims-cpu")
                cpu = fields(row["thread_cpu"], "before after")
                for reading in cpu.values():
                    fields(reading, "identity user_ticks system_ticks")
                    self.thread(reading["identity"])
                require(cpu["before"]["identity"] == cpu["after"]["identity"], "cold-cpu-thread-crossed")
                for key in ("user_ticks", "system_ticks"):
                    require(uint(cpu["after"][key]) >= uint(cpu["before"][key]), "cold-cpu-regressed")
            require(sequence not in self.records or self.records[sequence] == row, "cold-stage-history-rewritten")
            self.records[sequence] = row
        if current["compiler"] is None:
            require(self.variant == "control", "cold-candidate-pool-unobserved")
            require(all(uint(item) == 0 for key, item in current["stages"][-1].items() if key != "stage"), "cold-control-fabricated-queue")
        else:
            require(self.variant == "candidate", "cold-control-has-treatment-pool")
            compiler = current["compiler"]
            require(isinstance(compiler,dict) and set(compiler) == FIELDS, "cold-compiler-fields")
            for name,item in compiler.items():
                if name in ("accepting","failed"):
                    require(type(item) is bool, "cold-compiler-state")
                else:
                    uint(item)
            require(compiler["maximum_jobs"] == "4" and compiler["maximum_workers"] == "2"
                    and compiler["maximum_queued_jobs"] == "2" and compiler["maximum_waiters"] == "68"
                    and compiler["maximum_waiters_per_job"] == "68"
                    and compiler["maximum_ready_preparations"] == "68", "cold-compiler-controls")
            for field, ceiling in (("assigned_jobs", 2), ("running_jobs", 2), ("queued_jobs", 2), ("waiting_callers", 68)):
                require(uint(compiler[field]) <= ceiling, "cold-compiler-gauge-bound")
            if final:
                validate_compiler_shutdown({key:item if type(item) is bool else uint(item)
                                           for key,item in compiler.items()}, require)
        if final:
            require(current["active_jobs"] == "0" and current["running"] == [], "cold-final-job-ownership")
            require(sorted(self.records) == list(range(len(self.records))), "cold-stage-sequence-gap")
            for total in current["stages"]:
                rows = [row for row in self.records.values() if row["stage"] == total["stage"]]
                require(uint(total["started"]) == len(rows)
                        and uint(total["completed"]) == sum(row["succeeded"] for row in rows)
                        and uint(total["failed"]) == sum(not row["succeeded"] for row in rows)
                        and uint(total["thread_cpu_samples"]) == sum(row["thread_cpu"] is not None for row in rows)
                        and uint(total["thread_cpu_unavailable"]) == sum(row["thread_cpu"] is None for row in rows)
                        and uint(total["elapsed_nanos"]) == sum(uint(row["finished_nanos"]) - uint(row["started_nanos"]) for row in rows),
                        "cold-final-stage-total-not-raw")
                for key in ("user_ticks", "system_ticks"):
                    actual = sum(uint(row["thread_cpu"]["after"][key]) - uint(row["thread_cpu"]["before"][key])
                                 for row in rows if row["thread_cpu"] is not None)
                    require(uint(total["thread_cpu_" + key]) == actual, "cold-cpu-total-not-raw")
            require(sorted(self.jobs) == list(range(len(self.jobs))), "cold-job-sequence-gap")
            for job in self.jobs:
                rows = [row for row in self.records.values() if uint(row["job_id"]) == job]
                require(sum(row["stage"] == "whole_job" for row in rows) == 1, "cold-job-without-whole-interval")
        self.last = current

    def thread(self, row):
        fields(row, "process_id thread_id start_time_ticks")
        require(uint(row["process_id"]) == self.pid and uint(row["thread_id"]) > 0
                and uint(row["start_time_ticks"]) > 0, "cold-thread-outside-process")

    def job(self, row):
        job = uint(row["job_id"])
        values = row["component_digest"]
        require(isinstance(values, list) and len(values) == 32, "cold-job-identity")
        digest = "sha256:" + bytes(integer(uint(item), 0, 255) for item in values).hex()
        require(digest in self.digests and (job not in self.jobs or self.jobs[job] == digest), "cold-crossed-job-release")
        self.jobs[job] = digest
        return digest

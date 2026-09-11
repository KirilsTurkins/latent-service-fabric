"""Export cursors preserve every stage while the production ring stays bounded."""
from tools.optimization_evidence.common import fields, require, uint
from ..cold.observer import Observer, STAGES


class CacheObserver(Observer):
    def __init__(self, pid, digests):
        super().__init__(pid, digests, "candidate", allow_ring_overwrites=True)
        self.next_export = 0

    def export(self, value):
        fields(value, "kind label collector_started_nanos collector_finished_nanos first_sequence next_sequence events "
               "observed_nanos stages ring_overwrites compiler")
        start, finish, offset = (uint(value[key]) for key in ("collector_started_nanos", "collector_finished_nanos", "observed_nanos"))
        require(start <= finish, "cache-event-clock-window")
        self.anchors.append((start - offset, finish - offset))
        require(max(low for low, _ in self.anchors) <= min(high for _, high in self.anchors), "cache-event-clock-origin-changed")
        rows = value["events"]
        require(isinstance(rows, list) and len(rows) <= 256 and uint(value["first_sequence"]) == self.next_export
                and uint(value["next_sequence"]) == self.next_export + len(rows)
                and [uint(row["sequence"]) for row in rows] == list(range(self.next_export, self.next_export + len(rows))),
                "cache-export-missing-duplicate-or-reordered-stage")
        self.record_rows(rows, offset)
        self.next_export += len(rows)
        require(uint(value["ring_overwrites"]) == max(0, self.next_export - 256), "cache-export-ring-overwrite-count")
        require(isinstance(value["stages"], list) and [row["stage"] for row in value["stages"]] == list(STAGES), "cache-stage-manifest")
        for total in value["stages"]:
            fields(total, "stage started completed failed elapsed_nanos thread_cpu_samples thread_cpu_unavailable thread_cpu_user_ticks thread_cpu_system_ticks")
            stage = [row for sequence, row in self.records.items() if sequence < self.next_export and row["stage"] == total["stage"]]
            require(uint(total["completed"]) == sum(row["succeeded"] for row in stage)
                    and uint(total["failed"]) == sum(not row["succeeded"] for row in stage)
                    and len(stage) <= uint(total["started"]) <= len(stage) + 4
                    and uint(total["elapsed_nanos"]) == sum(uint(row["finished_nanos"]) - uint(row["started_nanos"]) for row in stage)
                    and uint(total["thread_cpu_samples"]) == sum(row["thread_cpu"] is not None for row in stage)
                    and uint(total["thread_cpu_unavailable"]) == sum(row["thread_cpu"] is None for row in stage),
                    "cache-export-cumulative-stage-not-raw")
            for name in ("user_ticks", "system_ticks"):
                actual = sum(uint(row["thread_cpu"]["after"][name]) - uint(row["thread_cpu"]["before"][name])
                             for row in stage if row["thread_cpu"] is not None)
                require(uint(total["thread_cpu_" + name]) == actual, "cache-export-cumulative-cpu-not-raw")
        self.compiler_check(value["compiler"], value["stages"])

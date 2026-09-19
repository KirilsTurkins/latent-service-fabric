"""Open-loop arrivals without completion-paced catch-up or an unbounded client queue."""
from __future__ import annotations

import time

from tools.phase2_operator_process import require
from tools.phase3_resource_profile import validate_schedule


def run_open_loop(count, interval_ns, maximum_outstanding, launch, finish, tick, deadline,
                  clock=time.monotonic_ns, pause=time.sleep):
    require(type(count) is int and 1 <= count <= 256 and 1 <= maximum_outstanding <= 16,
            "resource-schedule-bound")
    require(type(interval_ns) is int and 1 <= interval_ns <= 1_000_000_000, "resource-arrival-interval")
    origin = clock()
    rows, active = [], []
    next_arrival = 0
    try:
        while next_arrival < count or active:
            require(clock() < deadline, "resource-schedule-deadline")
            tick()
            retained = []
            for process, row in active:
                process.drain()
                if process.owner.exited():
                    row["result"] = finish(process)
                    row["finishedNanos"] = str(clock() - origin)
                    row["ownerReaped"] = bool(process.closed and process.owner.finished)
                    row["disposition"] = "completed"
                else:
                    retained.append((process, row))
            active = retained
            now = clock()
            while next_arrival < count and now >= origin + next_arrival * interval_ns:
                row = {"ordinal": next_arrival, "scheduledNanos": str(next_arrival * interval_ns),
                       "startedNanos": None, "finishedNanos": None, "disposition": "client-shed",
                       "reason": "outstanding-bound"}
                rows.append(row)
                next_arrival += 1
                if len(active) < maximum_outstanding:
                    row["startedNanos"] = str(clock() - origin)
                    process = launch(row["ordinal"])
                    row.update(disposition="outstanding", reason=None)
                    active.append((process, row))
                now = clock()
            pause(0.002)
        validate_schedule(rows, count, interval_ns)
        return rows
    finally:
        for process, _row in active:
            process.close()

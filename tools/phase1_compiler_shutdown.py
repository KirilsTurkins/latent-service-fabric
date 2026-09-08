"""Strict optional compiler ownership proof for newer standalone shutdowns.

Historical shutdown records omit this object and keep their original schema.
A present object must prove actual quiescence AND joins; missing gauges cannot
be treated as zero or inferred from the outer clean flag.
"""
from __future__ import annotations

LIMITS = ("maximum_jobs maximum_workers maximum_queued_jobs maximum_waiters "
          "maximum_waiters_per_job maximum_ready_preparations maximum_document_bytes").split()
ZERO = ("assigned_jobs running_jobs queued_jobs waiting_callers ready_preparations "
        "ready_metadata_bytes ready_compiled_image_bytes reserved_document_bytes workers_live").split()
COUNTERS = ("jobs_started jobs_completed jobs_failed jobs_abandoned coalesced_waiters "
            "queue_rejected waiter_rejected ready_rejected cancelled_waiters discarded_results").split()
FIELDS = set(LIMITS + ZERO + COUNTERS + ["workers_quiescent", "workers_joined", "accepting", "failed"])


def validate_compiler_shutdown(value, require):
    require(isinstance(value, dict) and set(value) == FIELDS, "compiler-shutdown-fields")
    for field in LIMITS + ZERO + COUNTERS + ["workers_quiescent", "workers_joined"]:
        require(type(value[field]) is int and 0 <= value[field] <= 2**64 - 1,
                "compiler-shutdown-counter")
    require(1 <= value["maximum_jobs"] <= 1024, "compiler-job-bound")
    workers = value["maximum_workers"]
    require(1 <= workers <= min(8, value["maximum_jobs"]), "compiler-worker-bound")
    require(value["maximum_queued_jobs"] == value["maximum_jobs"] - workers, "compiler-queue-bound")
    require(1 <= value["maximum_waiters_per_job"] <= value["maximum_waiters"] <= 1024,
            "compiler-waiter-bound")
    require(1 <= value["maximum_ready_preparations"] <= 1024
            and value["maximum_document_bytes"] > 0, "compiler-ready-document-bound")
    require(value["accepting"] is False and value["failed"] is False, "compiler-shutdown-state")
    require(all(value[name] == 0 for name in ZERO), "compiler-live-owners")
    require(value["workers_quiescent"] == workers and value["workers_joined"] == workers,
            "compiler-unjoined-workers")

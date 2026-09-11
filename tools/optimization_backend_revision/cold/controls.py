"""Actual cancellation and idle evidence, independent of asserted flags."""
from tools.optimization_evidence.common import fields, require, uint


def cancellation(row, observer, release):
    fields(row,"kind phase trigger commands retained_valid")
    require(row["phase"] == "cancel" and isinstance(row["commands"],list)
            and len(row["commands"]) == 4 and row["retained_valid"] is True, "cold-cancel-count")
    trigger = fields(row["trigger"],"running_when_observed observation")
    require(type(trigger["running_when_observed"]) is bool, "cold-cancel-trigger-marker")
    capture = trigger["observation"]
    observer.check(capture)
    current = capture["snapshot"]
    def matches(item):
        return item["stage"] == "component_new" and observer.job(item) == release
    running = any(matches(item) for item in current["running"])
    finished = any(matches(item) for item in current["recent_stages"])
    require(trigger["running_when_observed"] == running and (running or finished), "cold-cancel-trigger-not-compilation")
    prior = uint(capture["collector_finished_nanos"])
    for index,command in enumerate(row["commands"]):
        fields(command,"activation_id started_nanos finished_nanos response")
        began,ended = uint(command["started_nanos"]),uint(command["finished_nanos"])
        response = fields(command["response"],"grpc_code disposition terminal_state")
        require(command["activation_id"] == f"cold-cancel-cold-{index:04}"
                and prior <= began <= ended and response["grpc_code"] == 0
                and type(response["disposition"]) is int and response["disposition"] in (1,2,3)
                and (response["terminal_state"] is None or isinstance(response["terminal_state"],str)),
                "cold-cancel-disposition-or-order")
        prior = ended


def drained(capture):
    current = capture["snapshot"]
    require(current["active_jobs"] == "0" and current["running"] == [], "cold-phase-compiler-not-idle")
    if current["compiler"] is not None:
        require(all(current["compiler"][name] == "0" for name in
                    ("assigned_jobs","running_jobs","queued_jobs","waiting_callers","ready_preparations")),
                "cold-phase-compiler-owner")


def compilation_associations(observer,rows):
    """Use conservative clock brackets, never infer preparation from RPC time."""
    lower=max(left for left,_ in observer.anchors)
    upper=min(right for _,right in observer.anchors)
    compiled=[row for row in observer.records.values() if row["stage"] == "component_new"]
    first={}
    for row in rows:
        if row["dispatch_nanos"] is not None:
            release=row["release_digest"]
            first[release]=min(first.get(release,2**64),uint(row["dispatch_nanos"]))
    for job in compiled:
        release=observer.jobs[uint(job["job_id"])]
        require(release in first and uint(job["started_nanos"])+lower >= first[release],
                "cold-compilation-before-first-dispatch")
    for row in rows:
        if row["outcome"] == "success":
            require(any(job["succeeded"] and observer.jobs[uint(job["job_id"])] == row["release_digest"]
                        and uint(job["finished_nanos"])+upper <= uint(row["completed_nanos"]) for job in compiled),
                    "cold-success-before-observed-compilation")

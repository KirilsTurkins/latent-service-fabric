"""Descriptive paired statistics, preserving overlap and outcome populations."""
from collections import Counter
from decimal import Decimal

from tools.optimization_evidence.attempts import metrics
from tools.optimization_evidence.common import distribution, uint
from tools.phase1_paired.aggregate import delta
from .observer import STAGES


def compilation_windows(events):
    """Use one observer clock, including compilation of the warm release K0."""
    checkpoints = {row["label"]:row["observer"]["snapshot"] for row in events if row["kind"] == "checkpoint"}
    starts = {row["phase"]:row["observer"]["snapshot"] for row in events if row["kind"] == "phase-start"}
    ends = {row["phase"]:row["observer"]["snapshot"] for row in events if row["kind"] == "phase-end"}
    windows = {"warmup":(checkpoints["empty"],checkpoints["after-warmup"]),
               "baseline":(checkpoints["after-warmup"],checkpoints["after-baseline"]),
               **{phase:(starts[phase],ends[phase]) for phase in starts},
               "healthy":(ends["cancel"],checkpoints["after-healthy"])}
    return windows


def phase_compilations(records, window):
    before,after=window
    known={row["sequence"] for row in before["recent_stages"]}
    observed={row["sequence"] for row in after["recent_stages"]}
    return [row for row in records if row["sequence"] in observed-known
            and uint(before["observed_nanos"]) <= uint(row["started_nanos"])
            and uint(row["finished_nanos"]) <= uint(after["observed_nanos"])]


def summarize(rows, observer, controls, snapshots, events):
    phases = []
    lower = max(left for left,_ in observer.anchors)
    upper = min(right for _,right in observer.anchors)
    compile_rows = [row for row in observer.records.values() if row["stage"] == "component_new"]
    windows = compilation_windows(events)
    attributed = set()
    warm_release = next(row["release_digest"] for row in rows if row["key"] == "0")
    for phase in ("warmup","baseline","same-key","distinct","cancel","healthy"):
        selected = [row for row in rows if row["phase"] == phase]
        warm = [row for row in selected if row["key"] == "0"]
        cold = [row for row in selected if row["key"] != "0"]
        began, finished = (uint(snapshot["observed_nanos"]) for snapshot in windows[phase])
        jobs = phase_compilations(compile_rows,windows[phase])
        attributed.update(row["sequence"] for row in jobs)
        warm_jobs = [row for row in jobs if observer.jobs[uint(row["job_id"])] == warm_release]
        overlap = [row for row in warm if row["dispatch_nanos"] is not None and any(
            max(uint(row["dispatch_nanos"]),uint(job["started_nanos"])+upper)
            < min(uint(row["completed_nanos"]),uint(job["finished_nanos"])+lower) for job in jobs)]
        phases.append({"phase":phase,"offers":str(len(selected)),"outcomes":dict(sorted(Counter(row["outcome"] for row in selected).items())),
                       "all":metrics(selected),"warm":metrics(warm) if warm else None,"cold":metrics(cold) if cold else None,
                       "warm_overlap_offers":str(len(overlap)),"warm_overlap_successes":str(sum(row["outcome"] == "success" for row in overlap)),
                       "warm_overlap":metrics(overlap) if overlap else None,"actual_compilations":str(len(jobs)),
                       "warm_key_compilations":str(len(warm_jobs)),"cold_key_compilations":str(len(jobs)-len(warm_jobs)),
                       "compilation_observer_window_nanos":[str(began),str(finished)]})
    stages = []
    for stage in STAGES:
        selected = [row for row in observer.records.values() if row["stage"] == stage]
        cpu = [row["thread_cpu"] for row in selected if row["thread_cpu"] is not None]
        stages.append({"stage":stage,"observations":str(len(selected)),
                       "cpu_population":"unavailable-across-pool-threads" if stage == "queue_wait"
                                        else "paired-readings-of-the-actual-executing-task",
                       "elapsed_nanos":distribution([uint(row["finished_nanos"])-uint(row["started_nanos"]) for row in selected]) if selected else None,
                       "thread_cpu_samples":str(len(cpu)),"thread_cpu_unavailable":str(len(selected)-len(cpu)),
                       "thread_cpu_user_ticks":str(sum(uint(row["after"]["user_ticks"])-uint(row["before"]["user_ticks"]) for row in cpu)),
                       "thread_cpu_system_ticks":str(sum(uint(row["after"]["system_ticks"])-uint(row["before"]["system_ticks"]) for row in cpu))})
    fresh = next(row for row in rows if row["phase"] == "warmup" and row["index"] == "0")
    return {"phase_metrics":phases,"preparation_stages":stages,"compiler":observer.last["compiler"],
            "fresh_rpc_nanos":str(uint(fresh["completed_nanos"])-uint(fresh["dispatch_nanos"])),
            "baseline_success_latency_nanos":distribution([uint(row["latency_nanos"]) for row in rows if row["phase"] == "baseline"]),
            "node_samples":snapshots,"control_observations":controls,
            "unattributed_compilation_records":[row for row in compile_rows if row["sequence"] not in attributed],
            "compiler_job_records":list(observer.records.values()),"observer_clock_offset_interval_nanos":[str(lower),str(upper)]}


def aggregate(suite, checksum, builds, records, complete, failed):
    indexed = {(row["repetition"],row["variant"]):row for row in records if row["status"] == "passed"}
    pairs = []
    for repetition in range(1,8):
        if any((repetition,variant) not in indexed for variant in ("control","candidate")):
            continue
        control,candidate = (indexed[repetition,variant] for variant in ("control","candidate"))
        phase_pairs=[]
        for left,right in zip(control["phase_metrics"],candidate["phase_metrics"],strict=True):
            if left["phase"] not in ("same-key","distinct","cancel"):
                continue
            before,after=left["warm"],right["warm"]
            success_before,success_after=(item["successful_response_latency_nanos"] for item in (before,after))
            phase_pairs.append({"phase":left["phase"],"control":before,"candidate":after,
                "successful_latency_contrasts_conditioned_on_success":None if success_before is None or success_after is None else {
                    key:delta(Decimal(success_after[key]),Decimal(success_before[key])) for key in ("median","p95","p99")},
                "all_offered_elapsed_contrasts":{key:delta(Decimal(after["all_offered_elapsed_nanos"][key]),
                                                          Decimal(before["all_offered_elapsed_nanos"][key])) for key in ("median","p95","p99")},
                "control_overlap_offers":left["warm_overlap_offers"],"candidate_overlap_offers":right["warm_overlap_offers"]})
        pairs.append({"repetition":repetition,"warm_during_cold":phase_pairs,"baseline_success_latency_nanos":{
            "control":control["baseline_success_latency_nanos"],"candidate":candidate["baseline_success_latency_nanos"],
            "contrasts":{key:delta(Decimal(candidate["baseline_success_latency_nanos"][key]),Decimal(control["baseline_success_latency_nanos"][key]))
                         for key in ("median","p95","p99")}},
            "fresh_rpc_nanos":delta(Decimal(candidate["fresh_rpc_nanos"]),Decimal(control["fresh_rpc_nanos"]))})
    across=[]
    if pairs:
        for phase in ("same-key","distinct","cancel"):
            selected=[next(row for row in pair["warm_during_cold"] if row["phase"] == phase) for pair in pairs]
            across.append({"phase":phase,"all_offered_p99_paired_differences":distribution([
                Decimal(row["all_offered_elapsed_contrasts"]["p99"]["absolute"]) for row in selected]),
                "pairs_with_success_in_both_arms":str(sum(row["successful_latency_contrasts_conditioned_on_success"] is not None for row in selected)),
                "pairs_with_actual_warm_rpc_compile_overlap_in_both_arms":str(sum(
                    uint(row["control_overlap_offers"]) > 0 and uint(row["candidate_overlap_offers"]) > 0 for row in selected))})
    return {"schema":"latent.optimization.cold-aggregate.v1","profile":suite["profile"],
            "status":"failed" if failed else ("complete" if complete and suite["profile"] == "full" else "incomplete"),
            "suite_sha256":checksum,"builds":builds,"population_complete":complete,"attempt_count_complete":complete,
            "validated_calls":str(sum(int(row["samples"]) for row in records if row["status"] == "passed")),
            "runs":records,"pairs":pairs,"across_pairs":across,
            "limitations":["Fixed common client runtime and opt-in observation overhead belong to both processes.",
                "Warm overlap means the RPC interval intersects a conservatively mapped actual Component::new interval; its sample count is explicit.",
                "Phase compilation counts include K0 and cold releases within paired observer captures on the same clock; boundary-crossing or interphase records remain explicitly unattributed.",
                "CPU fields are actual task ticks with retained clock resolution, not wall time; zero ticks are quantized observations.",
                "QueueWait spans submitted-ready to worker pickup, including assigned-slot wake delay; it is per job, not a queued-waiter latency distribution.",
                "WholeJob measures the preparation body after worker pickup (inline in control); valid same-task CPU readings are retained. QueueWait has unavailable CPU and is separate.",
                "Whole-job and nested stages overlap and cannot be summed. Component::new includes Wasmtime internal validation.",
                "Compiler job IDs bind releases and stage intervals; RPC IDs bind callers. No per-caller prepare-ready interval is inferred from those separate groups.",
                "Successful latency contrasts are conditional on success; all offered warm requests, failures, producer lag and overshoot remain separate populations.",
                "A complete population is evidence completeness, not proof that every ordinary burst reached simultaneous worker and queue capacity.",
                "Ordinary performance has no blocked compiler seam; deterministic functional tests separately prove saturation and cancellation races.",
                "Smoke never completes full evidence; seven pairs are descriptive rather than statistical significance or an SLO."]}

"""Complete cache populations and descriptive paired effects at fixed locality."""
from collections import Counter
from decimal import Decimal

from tools.optimization_evidence.attempts import metrics
from tools.optimization_evidence.common import distribution, require, uint
from tools.phase1_paired.aggregate import delta
from ..cold.observer import STAGES


def resource_summary(snapshots):
    """Summarize every validated checkpoint; exact observations stay in raw."""
    require(bool(snapshots), "cache-resource-samples-missing")
    counters = {
        "rss_bytes": [uint(row["resources"]["process"]["residentMemoryBytes"]) for row in snapshots],
        "process_threads": [uint(row["resources"]["process"]["threadCount"]) for row in snapshots],
        "tasks": [uint(row["resources"]["taskCount"]) for row in snapshots],
        "open_file_descriptors": [uint(row["resources"]["process"]["openFileDescriptors"]) for row in snapshots],
        "process_sockets": [uint(row["resources"]["process"]["socketCount"]) for row in snapshots],
        "unique_sockets": [uint(row["resources"]["uniqueSocketCount"]) for row in snapshots],
        "listening_tcp_sockets": [uint(row["resources"]["listeningTcpSocketCount"]) for row in snapshots],
        "descendants": [len(row["resources"]["descendants"]) for row in snapshots],
    }
    return {"sample_count": str(len(snapshots)),
            "scope": "normal-node-process-including-common-libtest-and-client-runtimes",
            "sampling": "fixed-checkpoints-not-continuous-or-kernel-high-water",
            "first_label": snapshots[0]["label"], "last_label": snapshots[-1]["label"],
            "first_started_micros": snapshots[0]["started_micros"], "last_finished_micros": snapshots[-1]["finished_micros"],
            "counters": {name: {"first": str(values[0]), "last": str(values[-1]),
                                "minimum_observed": str(min(values)), "maximum_observed": str(max(values))}
                         for name, values in counters.items()}}


def summarize(rows, observer, snapshots, events):
    checkpoints = {row["label"]: row for row in events if row["kind"] == "checkpoint"}
    boundaries = {"warmup": ("empty", "after-warmup"), "baseline": ("after-warmup", "after-baseline"),
                  "round-robin-warmup": ("after-baseline", "after-round-robin-warmup"),
                  "round-robin": ("after-round-robin-warmup", "after-round-robin"),
                  "locality-warmup": ("after-round-robin", "after-locality-warmup"),
                  "locality": ("after-locality-warmup", "after-locality"),
                  "ownership": ("after-locality", "ownership-complete"),
                  "concurrent": ("before-concurrent", "after-concurrent"), "healthy": ("after-concurrent", "after-healthy")}
    lower, upper = max(left for left, _ in observer.anchors), min(right for _, right in observer.anchors)
    compiled = [row for row in observer.records.values() if row["stage"] == "component_new"]
    warm_release = next(row["release_digest"] for row in rows if row["key"] == "0")
    phases, attributed = [], set()
    for phase, (left, right) in boundaries.items():
        before, after = checkpoints[left], checkpoints[right]
        selected = [row for row in rows if (row["phase"].startswith("ownership-") if phase == "ownership" else row["phase"] == phase)]
        begin, end = (uint(row["observer"]["snapshot"]["observed_nanos"]) for row in (before, after))
        jobs = [row for row in compiled if begin <= uint(row["started_nanos"]) <= uint(row["finished_nanos"]) <= end]
        attributed.update(row["sequence"] for row in jobs)
        cold_jobs = [row for row in jobs if observer.jobs[uint(row["job_id"])] != warm_release]
        warm = [row for row in selected if row["key"] == "0"]
        overlap = [row for row in warm if row["dispatch_nanos"] is not None and any(
            max(uint(row["dispatch_nanos"]), uint(job["started_nanos"]) + upper)
            < min(uint(row["completed_nanos"]), uint(job["finished_nanos"]) + lower) for job in cold_jobs)]
        change = {}
        for name in ("hits", "misses", "evictions", "invalidations"):
            first, last = (uint(row["accounting"]["resident"][name]) for row in (before, after))
            require(first <= last, "cache-counter-regressed")
            change[name] = str(last - first)
        phases.append({"phase": phase, "warmup": phase in ("warmup", "round-robin-warmup", "locality-warmup"),
                       "functional_ownership_sequence": phase == "ownership", "offers": str(len(selected)),
                       "outcomes": dict(sorted(Counter(row["outcome"] for row in selected).items())), "all": metrics(selected),
                       "warm": metrics(warm) if warm else None, "cache_delta": change,
                       "actual_compilations": str(len(jobs)), "warm_key_compilations": str(len(jobs) - len(cold_jobs)),
                       "cold_key_compilations": str(len(cold_jobs)), "cold_compile_overlap_offers": str(len(overlap)),
                       "cold_compile_overlap_successes": str(sum(row["outcome"] == "success" for row in overlap)),
                       "cold_compile_overlap": metrics(overlap) if overlap else None,
                       "compilation_observer_window_nanos": [str(begin), str(end)]})
    stages = []
    for stage in STAGES:
        selected = [row for row in observer.records.values() if row["stage"] == stage]
        cpu = [row["thread_cpu"] for row in selected if row["thread_cpu"] is not None]
        stages.append({"stage": stage, "observations": str(len(selected)),
                       "elapsed_nanos": distribution([uint(row["finished_nanos"]) - uint(row["started_nanos"]) for row in selected]) if selected else None,
                       "thread_cpu_samples": str(len(cpu)), "thread_cpu_unavailable": str(len(selected) - len(cpu)),
                       "thread_cpu_user_ticks": str(sum(uint(row["after"]["user_ticks"]) - uint(row["before"]["user_ticks"]) for row in cpu)),
                       "thread_cpu_system_ticks": str(sum(uint(row["after"]["system_ticks"]) - uint(row["before"]["system_ticks"]) for row in cpu))})
    return {"phase_metrics": phases, "preparation_stages": stages, "compiler": observer.last["compiler"],
            "preparation_stage_record_count": str(len(observer.records)), "preparation_job_count": str(len(observer.jobs)),
            "resources": resource_summary(snapshots),
            "observer_clock_offset_interval_nanos": [str(lower), str(upper)],
            "unattributed_compilation_count": str(sum(row["sequence"] not in attributed for row in compiled))}


def aggregate(suite, checksum, builds, records, complete, failed):
    indexed = {(row["repetition"], row["variant"]): row for row in records if row["status"] == "passed"}
    pairs = []
    for repetition in range(1, 8):
        if any((repetition, arm) not in indexed for arm in ("control", "candidate")):
            continue
        control, candidate = (indexed[repetition, arm] for arm in ("control", "candidate"))
        comparisons = []
        for left, right in zip(control["phase_metrics"], candidate["phase_metrics"], strict=True):
            require(left["phase"] == right["phase"], "cache-paired-phase-crossed")
            if left["warmup"] or left["functional_ownership_sequence"]:
                continue
            scope = "warm" if left["phase"] == "concurrent" else "all"
            before, after = left[scope], right[scope]
            success_before, success_after = (row["successful_response_latency_nanos"] for row in (before, after))
            comparisons.append({"phase": left["phase"], "population": scope, "control": before, "candidate": after,
                                "control_cache_delta": left["cache_delta"], "candidate_cache_delta": right["cache_delta"],
                                "successful_latency_contrasts_conditioned_on_success": None if success_before is None or success_after is None else {
                                    key: delta(Decimal(success_after[key]), Decimal(success_before[key])) for key in ("median", "p95", "p99")},
                                "all_offered_elapsed_contrasts": {key: delta(Decimal(after["all_offered_elapsed_nanos"][key]),
                                                                             Decimal(before["all_offered_elapsed_nanos"][key]))
                                                                 for key in ("median", "p95", "p99")},
                                "control_actual_overlap_offers": left["cold_compile_overlap_offers"],
                                "candidate_actual_overlap_offers": right["cold_compile_overlap_offers"]})
        pairs.append({"repetition": repetition, "phases": comparisons})
    across = []
    for phase in ("baseline", "round-robin", "locality", "concurrent", "healthy"):
        selected = [next(row for row in pair["phases"] if row["phase"] == phase) for pair in pairs]
        if selected:
            across.append({"phase": phase, "pairs": len(selected),
                           "all_offered_p99_paired_differences": distribution([Decimal(row["all_offered_elapsed_contrasts"]["p99"]["absolute"]) for row in selected]),
                           "pairs_with_success_in_both_arms": str(sum(row["successful_latency_contrasts_conditioned_on_success"] is not None for row in selected)),
                           "pairs_with_cold_compile_overlap_in_both_arms": str(sum(uint(row["control_actual_overlap_offers"]) > 0
                                                                                  and uint(row["candidate_actual_overlap_offers"]) > 0 for row in selected))})
    return {"schema": "latent.optimization.cache-behavior-aggregate.v1", "profile": suite["profile"],
            "status": "failed" if failed else ("complete" if complete and suite["profile"] == "full" else "incomplete"),
            "suite_sha256": checksum, "builds": builds, "population_complete": complete, "attempt_count_complete": complete,
            "validated_calls": str(sum(int(row["samples"]) for row in records if row["status"] == "passed")),
            "validated_direct_executions": str(sum(int(row["direct_work"]["executions"]) for row in records if row["status"] == "passed")),
            "runs": records, "pairs": pairs, "across_pairs": across,
            "limitations": [
                "Both arms use matched post-101 compiler workers and the same in-process node/client diagnostic overhead; this is not the external standalone RPC reference.",
                "Warmup calls are retained but excluded from measured contrasts; the held-owner and failed-refill sequence is reported separately as functional work.",
                "All offered requests, producer lag, failures and overshoot remain in their declared populations; successful latency is conditional on success.",
                "Phase throughput spans first offer to last completion and includes intervening retained-status and fixed observer-export coordination.",
                "Preparation records are exported at fixed groups of at most 16 sequential calls; ring overwrites do not justify missing archived records.",
                "All preparation records and node probes are validated in archived cache.json; the aggregate retains derived counts and fixed-checkpoint resource summaries, not duplicate raw arrays.",
                "Actual task CPU ticks are separate from elapsed; nested preparation stages overlap and cannot be summed.",
                "Warm/cold overlap is conservatively tied to actual other-component compile intervals; no per-caller prepare-ready latency is inferred.",
                "Control unique-runtime accounting is unavailable; candidate source-associated bytes, metadata charges and image spans are not RSS or uniquely mapped physical bytes.",
                "The direct contained execution has no fabricated manager route or terminal receipt and is counted separately from RPC Invokes.",
                "A complete population does not mean every concurrent request succeeded; rejected work cannot be presented as a matched-completion CPU saving.",
                "Smoke does not complete full evidence; seven independent pairs supply descriptive variability, not significance or an SLO."]}

"""Descriptive process statistics, preserving the actual sampled boundaries."""
from collections import Counter
from decimal import Decimal

from tools.optimization_evidence.common import distribution, fields, integer, require, uint
from ..cache.aggregate import resource_summary
from ..cold.observer import STAGES
from . import model, resources


def cpu(value, owner, lower, upper):
    if value is None:
        return None
    fields(value, "collector_started_nanos collector_finished_nanos pid start_time_ticks user_ticks system_ticks")
    for item in value.values():
        uint(item)
    require((uint(value["pid"]), uint(value["start_time_ticks"])) == owner
            and lower <= uint(value["collector_started_nanos"]) <= uint(value["collector_finished_nanos"]) <= upper,
            "engine-cpu-owner-or-capture-crossed")
    return value


def cpu_delta(before, after):
    if before is None or after is None:
        return None
    require(uint(before["collector_finished_nanos"]) <= uint(after["collector_started_nanos"]), "engine-cpu-brackets-overlap")
    result = 0
    for key in ("user_ticks", "system_ticks"):
        require(uint(after[key]) >= uint(before[key]), "engine-process-cpu-regressed")
        result += uint(after[key]) - uint(before[key])
    return str(result)


def summarize(calls, checkpoints, windows, observer, samples, memory_rows, identity):
    metrics, phases = {}, []
    frequency = integer(identity["environment"]["clock_ticks_per_second"], 1, 1_000_000)
    metrics["process.population_and_controls.cpu_ticks"] = cpu_delta(checkpoints["empty"]["cpu"], checkpoints["before-shutdown"]["cpu"])
    metrics["process.population_and_controls.cpu_seconds"] = (None if metrics["process.population_and_controls.cpu_ticks"] is None else
            str(Decimal(metrics["process.population_and_controls.cpu_ticks"]) / frequency))
    resource = resource_summary(samples)
    for name, values in resource["counters"].items():
        metrics["process.sampled_maximum." + name] = values["maximum_observed"]
    for phase in model.phases(identity["measurement_profile"]):
        name = phase["name"]
        phase_rows = [call for call in calls if call["row"]["phase"] == name]
        for population in ("warmup", "measured"):
            selected = [call for call in phase_rows if call["row"]["phase_kind"] == population]
            window = windows[(name, population)]
            begin, finish = uint(window["started_nanos"]), uint(window["finished_nanos"])
            successful = [call for call in selected if call["row"]["outcome"] == "success"]
            summary = {"phase": name, "population": population, "offers": str(len(selected)),
                       "outcomes": dict(sorted(Counter(call["row"]["outcome"] for call in selected).items())),
                       "successful_latency_nanos": distribution([call["latency_nanos"] for call in successful]) if successful else None,
                       "all_offered_elapsed_nanos": distribution([call["all_offered_nanos"] for call in selected]),
                       "backend_timing_micros": {key: distribution([call["timing"][key] for call in selected]) for key in selected[0]["timing"]},
                       "batch_window": window, "throughput_rps": str(Decimal(len(selected)) * 10**9 / (finish - begin))}
            if population == "measured":
                prefix = "phase." + name + "."
                for source, label in (("successful_latency_nanos", "successful"), ("all_offered_elapsed_nanos", "all_offered")):
                    for quantile in ("median", "p95", "p99"):
                        metrics[prefix + label + "." + quantile + "_nanos"] = summary[source][quantile] if summary[source] else None
                for timing, values in summary["backend_timing_micros"].items():
                    for quantile in ("median", "p95"):
                        metrics[prefix + timing + "." + quantile] = values[quantile]
                metrics[prefix + "throughput_rps"] = summary["throughput_rps"]
                left, right = checkpoints[name + "-after-warmup"], checkpoints[name + "-after-measured"]
                summary["process_cpu_ticks"] = cpu_delta(left["cpu"], right["cpu"])
                summary["process_cpu_scope"] = "same-process-after-warmup-to-after-measured-checkpoints-including-client-status-and-observation"
                metrics[prefix + "process_cpu_ticks"] = summary["process_cpu_ticks"]
                for field in resources.STATUS + resources.ROLLUP:
                    metrics[prefix + "after_measured." + field] = right["memory_values"][field]
            phases.append(summary)
    first = calls[0]
    metrics["fresh_engine_first_echo.latency_nanos"] = str(first["latency_nanos"])
    stage_rows = []
    for stage in STAGES:
        selected = [row for row in observer.records.values() if row["stage"] == stage]
        cpu_rows = [row["thread_cpu"] for row in selected if row["thread_cpu"] is not None]
        user = sum(uint(row["after"]["user_ticks"]) - uint(row["before"]["user_ticks"]) for row in cpu_rows)
        system = sum(uint(row["after"]["system_ticks"]) - uint(row["before"]["system_ticks"]) for row in cpu_rows)
        stage_rows.append({"stage": stage, "records": str(len(selected)), "thread_cpu_available": str(len(cpu_rows)),
                           "thread_cpu_unavailable": str(len(selected) - len(cpu_rows)), "thread_cpu_user_ticks": str(user),
                           "thread_cpu_system_ticks": str(system), "elapsed_nanos":
                           distribution([uint(row["finished_nanos"]) - uint(row["started_nanos"]) for row in selected]) if selected else None})
        if stage == "component_new":
            metrics["preparation.component_new.total_cpu_ticks"] = str(user + system) if len(cpu_rows) == len(selected) else None
    return phases, metrics, {"checkpoints": str(len(memory_rows)), "fields": resources.summarize(memory_rows),
                           "normal_node_resources": resource}, {
        "jobs": str(len(observer.jobs)), "stage_records": str(len(observer.records)), "stages": stage_rows,
        "compiler": observer.last["compiler"], "clock_ticks_per_second": frequency,
        "clock_offset_interval_nanos": [str(max(low for low, _ in observer.anchors)), str(min(high for _, high in observer.anchors))]}

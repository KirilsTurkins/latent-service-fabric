"""Stream collector records, checking order and the terminal receipt."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import (MAX_RAW_BYTES, MAX_ROW_BYTES, MAX_ROWS, EvidenceError, canonical,
                     decode, fields, require, text, uint, validate_identity, validate_plan)
from .resources import Samples, shutdown
from .statistics import Measurements

RAW_SCHEMA = "latent.phase1.measurement.raw.v1"


def public_configuration(value: Any) -> None:
    require(isinstance(value, dict), "invalid-public-configuration")
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, dict):
            for key, child in item.items():
                require(not any(word in key.lower() for word in
                                ("credential", "token", "password", "authorization", "secret")),
                        "sensitive-public-configuration")
                pending.append(child)
        elif isinstance(item, list):
            pending.extend(item)


def work(value: Any) -> tuple[int, int]:
    fields(value, "commands invoke_attempts budget_exhausted")
    commands, invokes = uint(value["commands"]), uint(value["invoke_attempts"])
    require(invokes <= commands and type(value["budget_exhausted"]) is bool, "invalid-work-counts")
    return commands, invokes


def read_raw(path: Path) -> dict[str, Any]:
    # Profile validators consume one bounded row at a time. Only capped numeric
    # samples and resource checkpoints survive beyond an iteration.
    from .profiles import Profile

    header = None
    footer = None
    measurements = Measurements()
    samples = Samples()
    profile = None
    sequence = 0
    byte_count = 0
    cleanup = False
    shared = {}
    input_references = []
    workload_started = False
    try:
        require(path.is_file(), "not-regular-raw-file")
        with path.open("rb") as source:
            while line := source.readline(MAX_ROW_BYTES + 1):
                byte_count += len(line)
                require(byte_count <= MAX_RAW_BYTES and len(line) <= MAX_ROW_BYTES, "raw-byte-limit")
                require(line.endswith(b"\n"), "truncated-raw-line")
                require(sequence < MAX_ROWS and footer is None, "records-after-summary")
                row = fields(decode(line, MAX_ROW_BYTES), "schema sequence kind payload")
                require(row["schema"] == RAW_SCHEMA and uint(row["sequence"]) == sequence, "invalid-raw-sequence")
                kind = text(row["kind"], 64)
                payload = row["payload"]
                if sequence == 0:
                    require(kind == "header", "missing-raw-header")
                    header = fields(payload, "profile workload repetition plan config identity")
                    validate_plan(header["plan"])
                    validate_identity(header["identity"])
                    public_configuration(header["config"])
                    require(header["profile"] == header["plan"]["profile"]
                            and header["workload"] == header["plan"]["kind"]
                            and uint(header["repetition"]) == header["plan"]["repetition"], "header-plan-mismatch")
                    require(header["profile"] != "full" or header["identity"]["build"]["profile"] == "release", "full-profile-requires-release-build")
                    profile = Profile(header["plan"], measurements, samples)
                elif kind == "summary":
                    footer = fields(payload, "status reason event_count elapsed_nanos shutdown work workload_result")
                    require(footer["status"] in ("passed", "failed"), "invalid-run-status")
                    require(uint(footer["event_count"]) == sequence - 1, "event-count-mismatch")
                    work(footer["work"])
                    if footer["status"] == "passed":
                        require(set(shared) == {"fixture-inputs", "startup"}, "missing-shared-provenance")
                        require(cleanup, "missing-data-cleanup")
                        require(footer["reason"] is None and footer["work"]["budget_exhausted"] is False,
                                "passed-run-has-failure")
                        shutdown(footer["shutdown"])
                        profile.finish(footer)
                    else:
                        text(footer["reason"], 128)
                    require(uint(footer["elapsed_nanos"]) >= samples.last_finished * 1000,
                            "elapsed-before-observation")
                    require(uint(footer["elapsed_nanos"]) <= uint(header["plan"]["maximum_run_seconds"]) * 10**9,
                            "run-watchdog-exceeded")
                elif kind == "data-cleanup":
                    fields(payload, "removed")
                    require(not cleanup and payload["removed"] is True, "invalid-data-cleanup")
                    cleanup = True
                else:
                    require(not cleanup, "measurement-after-data-cleanup")
                    require(kind != "header", "duplicate-raw-header")
                    if kind in ("fixture-inputs", "startup"):
                        from .provenance import fixture_inputs, startup
                        require(kind not in shared and not workload_started, "invalid-shared-provenance-order")
                        shared[kind] = payload
                        if kind == "fixture-inputs":
                            input_references = fixture_inputs(payload, path.parent, header["identity"])
                        else:
                            startup(payload, measurements)
                    else:
                        require(set(shared) == {"fixture-inputs", "startup"}, "workload-before-provenance")
                        workload_started = True
                        profile.event(kind, payload)
                sequence += 1
    except OSError as error:
        raise EvidenceError("unreadable-raw-evidence") from error
    require(header is not None and footer is not None, "missing-raw-summary")
    require(byte_count <= uint(header["plan"]["maximum_output_bytes"]), "configured-output-limit")
    for sample in samples.values:
        commands, invokes = work(sample["work"])
        final_commands, final_invokes = work(footer["work"])
        require(commands <= final_commands and invokes <= final_invokes, "sample-work-exceeds-final")
    result = {"header": header, "summary": footer, "metrics": measurements.summaries(),
              "samples": samples.values, "raw_bytes": str(byte_count), "input_references": input_references}
    if header["workload"] == "soak" and footer["status"] == "passed":
        from .policy import reclamation
        result["reclamation"] = reclamation(samples.values, header["profile"])
    if header["workload"] == "benchmark":
        from .inputs import benchmark_input
        if footer["status"] == "passed":
            benchmark_input(profile.validator.input, header["identity"])
            echo = next(row for row in shared["fixture-inputs"]["fixtures"] if row["name"] == "echo")
            require(profile.validator.input["manifest_sha256"] == echo["capsule"]["sha256"]
                    and profile.validator.input["contract_metadata_sha256"] == echo["contracts"]["sha256"],
                    "benchmark-transmitted-metadata-mismatch")
        result["benchmark_input"] = profile.validator.input
        result["throughput"] = profile.validator.throughput()
    return result


def same_plan(base: dict[str, Any], measured: dict[str, Any], repetition: int) -> bool:
    expected = dict(base, repetition=repetition)
    return canonical(expected) == canonical(measured)

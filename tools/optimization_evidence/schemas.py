"""Self-contained draft-2020-12 schemas, mirrored by stricter semantic replay."""

from copy import deepcopy

from .common import OUTCOMES


def obj(properties, optional=()):
    return {"type": "object", "properties": properties, "required": [key for key in properties if key not in optional],
            "additionalProperties": False}


def array(item, maximum=4096, minimum=0):
    return {"type": "array", "items": item, "maxItems": maximum, "minItems": minimum}


def nullable(value):
    return {"anyOf": [value, {"type": "null"}]}


def ref(name):
    return {"$ref": "#/$defs/" + name}


def documents():
    string = {"type": "string", "maxLength": 4096}
    number = {"type": "integer", "minimum": 0, "maximum": 2**32 - 1}
    uint = {"type": "string", "pattern": "^(0|[1-9][0-9]{0,19})$"}
    digest = {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}
    boolean = {"type": "boolean"}
    definitions = {
        "artifact": obj({"path": {"type": "string", "minLength": 1, "maxLength": 1024},
                         "sha256": digest, "bytes": uint}),
        "json": {"anyOf": [{"type": "null"}, boolean, {"type": "number"},
                           {"type": "string", "maxLength": 1048576},
                           array(ref("json"), 100000),
                           {"type": "object", "maxProperties": 4096, "additionalProperties": ref("json")}]},
    }
    schedule = {"oneOf": [obj({"mode": {"const": "closed-loop"}}),
                           obj({"mode": {"const": "scheduled"}, "interval_nanos": {"type": "integer", "minimum": 1}})]}
    template = {
        "schema": {"const": "latent.optimization.client-plan.v1"}, "tenant": string,
        "services": array(string, 64, 1), "contract": string, "route": nullable(string),
        "function": {"enum": ["echo", "compute", "transform"]}, "payload": array(ref("json"), 4096),
        "warmup_attempts": number, "measured_attempts": number, "batch_size": number,
        "concurrency": {"type": "integer", "minimum": 1, "maximum": 64},
        "runtime_workers": {"type": "integer", "minimum": 1, "maximum": 16}, "schedule": schedule,
        "budget_millis": {"type": "integer", "minimum": 1, "maximum": 5000},
        **{key: {"type": "integer", "minimum": 0, "maximum": 2**64 - 1} for key in
           ("cpu_fuel", "memory_bytes", "log_bytes", "connect_timeout_millis",
            "response_timeout_millis", "maximum_output_bytes")},
    }
    dynamic = {"run_id": {"type": "string", "pattern": "^[A-Za-z0-9-]{1,48}$"},
               "arm": {"enum": ["native", "lsf"]}, "server_process_id": number,
               "endpoint": string, "token_file": string}
    definitions["client_plan"] = obj({**template, **dynamic})
    public = {key: value for key, value in {**template, **dynamic}.items()
              if key not in ("payload", "endpoint", "token_file")}
    public.update(payload_sha256=digest, payload_bytes=uint)
    definitions["plan"] = obj({
        "schema": {"const": "latent.optimization.plan.v1"}, "profile": {"enum": ["smoke", "full"]},
        "repetitions": {"enum": [1, 7]}, "scenarios": {"const": ["cold-restart"]},
        "cases": array(obj({"id": string, "client_plan": obj(template)}), 16, 16),
        "maximum_run_seconds": uint, "maximum_artifact_bytes": uint,
    })
    definitions["readiness"] = obj({
        "schema": {"const": "latent.optimization.client-readiness.v1"}, "run_id": string,
        "arm": dynamic["arm"], "client_process_id": number, "server_process_id": number,
        "runtime_workers": number, "maximum_in_flight": number,
        **{key: uint for key in ("started_unix_millis", "connected_unix_millis", "connect_nanos",
                                 "startup_to_ready_nanos", "request_bytes", "expected_output_bytes")},
        **{key: digest for key in ("plan_sha256", "request_sha256", "expected_output_sha256")},
        "public_plan": obj(public), "observation_hold_millis": {"const": 100},
    })
    consumption = obj({key: uint for key in ("cpu_fuel peak_memory_bytes wall_time_micros child_calls outbound_requests "
                                           "state_read_bytes state_write_bytes blob_read_bytes blob_write_bytes "
                                           "log_bytes effect_count").split()})
    definitions["attempt"] = obj({
        "schema": {"const": "latent.optimization.attempt.v1"}, "phase": {"enum": ["warmup", "measured"]},
        **{key: uint for key in ("index", "batch", "scheduled_nanos", "completed_nanos",
                                 "request_deadline_unix_millis", "deadline_nanos", "overshoot_nanos",
                                 "absolute_deadline_quantization_nanos")},
        "activation_id": string, "service": string,
        **{key: nullable(uint) for key in ("dispatch_nanos", "dispatch_lag_nanos", "latency_nanos", "grpc_timeout_nanos")},
        "grpc_timeout_header": nullable({"type": "string", "pattern": "^[0-9]{1,8}[HMSmun]$"}),
        "outcome": {"enum": list(OUTCOMES)}, "code": nullable(string),
        "semantic_match": nullable(boolean), "rpc_received": boolean,
        "response": nullable(obj({
            "activation_id": string, "revision_id": string, "release_digest": string, "route_generation": uint,
            "consumption": nullable(consumption), "media_type": nullable(string),
            "payload_sha256": nullable(digest), "payload_bytes": nullable(uint),
        })),
    })
    definitions["counts"] = obj({
        **{key: uint for key in ("attempts", "dispatched", "undispatched", "received", "successful",
                                 "semantic_mismatches", "last_completed_nanos", "elapsed_nanos")},
        "first_scheduled_nanos": nullable(uint),
        "outcomes": {"type": "object", "properties": {key: uint for key in OUTCOMES}, "additionalProperties": False},
        "throughput": obj({key: uint for key in ("completed_attempts", "successful_responses", "elapsed_nanos")}),
    })
    definitions["phase"] = obj({
        "origin_unix_nanos": uint, "clock_anchor_uncertainty_nanos": uint, "phase_elapsed_nanos": uint,
        "counts": ref("counts"), "batches": array(obj({"index": uint, "counts": ref("counts")}), 10000),
    })
    definitions["summary"] = obj({
        "schema": {"const": "latent.optimization.client-summary.v1"}, "status": {"const": "complete"},
        "readiness": ref("readiness"), "warmup": ref("phase"), "measured": ref("phase"),
        "client_elapsed_nanos": uint, "active_tasks_at_completion": {"const": 0},
        "observation_hold_millis": {"const": 100},
    })
    definitions["process"] = obj({
        "process_id": number, "start_time_ticks": uint,
        "role": {"enum": ["native-server", "lsf-server", "lsf-seed", "load-client"]},
        "executable_sha256": digest, "reaped": boolean, "output_closed": boolean,
        "exit_code": nullable({"type": "integer", "minimum": -255, "maximum": 255}),
    })
    definitions["identity"] = obj({
        "source": obj({"commit": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                       "tree": {"type": "string", "pattern": "^[0-9a-f]{40}$"},
                       "dirty": boolean, "cargo_lock_sha256": digest}),
        "build": obj({"profile": {"enum": ["release", "debug"]}, "rustc": string, "cargo": string,
                      "wasmtime": string, "target": string, "overrides": {"type": "object", "maxProperties": 64}}),
        "environment": obj({
            "os": string, "arch": string, "kernel": string, "cpu_model": string,
            "logical_cpus": uint, "memory_total_bytes": uint,
            **{key: {"type": "object", "maxProperties": 64} for key in ("virtualization", "allocator", "cpu_policy")},
            "load_before": array({"type": "number", "minimum": 0}, 3, 3),
        }),
        "executables": obj({key: ref("artifact") for key in ("native", "lsf", "client", "control", "cli")}, ("control", "cli")),
        "components": array(ref("artifact"), 5, 5), "workload_sources": array(ref("artifact"), 32, 1),
        "build_inputs": array(ref("artifact"), 8, 8), "source_checks": array(ref("artifact"), 2, 2),
    })
    definitions["snapshot"] = obj({
        "process_id": number, "start_time_ticks": uint,
        **{key: uint for key in ("rss_bytes", "cpu_user_ticks", "cpu_system_ticks", "read_bytes", "write_bytes")},
        "threads": number, "fd_count": number,
    })
    definitions["samples"] = obj({
        **{key: ref("snapshot") for key in ("before", "after", "last_live")},
        "peak_rss_bytes": uint, "sample_interval_millis": {"const": 100},
        "peak_semantics": {"const": "maximum-observed-rss-not-instantaneous-peak"},
    })
    controllers = ("cpu.max", "cpu.stat", "memory.max", "memory.current", "memory.stat",
                   "memory.events", "cpu.pressure", "memory.pressure", "io.pressure")
    definitions["cgroup"] = obj({
        "scope": {"const": "runner-cgroup-shared"}, "process_membership": {"type": "string", "maxLength": 16384},
        **{key: nullable({"type": "string", "maxLength": 65536}) for key in controllers},
        "resolution": obj({
            "status": {"enum": ["resolved", "unsupported"]},
            **{key: nullable(string) for key in ("path", "mount_id", "mount_root", "mount_point", "device", "inode")},
        }),
        "errors": {"type": "object", "properties": {
            key: {"enum": ["missing", "permission-denied", "oversized", "invalid", "unavailable", "ambiguous", "membership-changed"]}
            for key in (*controllers, "process_membership", "mountinfo", "resolution")
        }, "additionalProperties": False},
    })
    definitions["resources"] = obj({
        "server": ref("samples"), "client": ref("samples"),
        "cgroup": obj({"before": ref("cgroup"), "after": ref("cgroup")}),
    })
    definitions["lifecycle"] = obj({
        **{key: uint for key in ("process_start_to_ready_micros", "process_start_to_first_response_observed_micros",
                                 "ready_to_first_response_observed_micros")},
        "first_response_observation": {"const": "parent-received-client-event-upper-bound-includes-client-startup-and-connect"},
        "initial_preparation": {"enum": ["included-in-first-call", "not-applicable"]},
    })
    definitions["batch"] = obj({"id": string, **{key: ref("artifact") for key in
        ("plan", "readiness", "attempts", "summary", "client_process", "resources")}})
    definitions["run"] = obj({
        "repetition": {"type": "integer", "minimum": 1, "maximum": 7}, "arm": dynamic["arm"],
        "scenario": {"const": "cold-restart"}, "status": {"enum": ["passed", "failed"]},
        "reason": {"enum": [None, "collector-failed"]}, "started_micros": uint, "finished_micros": uint,
        "batches": array(ref("batch"), 16),
        **{key: nullable(ref("artifact")) for key in ("server_process", "configuration", "cleanup")},
        "lifecycle": nullable(ref("lifecycle")),
    })
    definitions["suite"] = obj({
        "schema": {"const": "latent.optimization.suite.v1"}, "profile": {"enum": ["smoke", "full"]},
        "plan": ref("plan"), "identity": ref("identity"), "runs": array(ref("run"), 14),
        "artifacts": array(ref("artifact"), 4096, 1),
    })
    # Aggregate numeric and correlation semantics are checked by exact replay.
    # Its open metric values are bounded JSON; top-level claims remain closed.
    definitions["aggregate"] = obj({
        "schema": {"const": "latent.optimization.aggregate.v1"}, "profile": {"enum": ["smoke", "full"]},
        "status": {"enum": ["complete", "incomplete", "failed"]},
        "scope": {"const": "standalone-native-code-versus-lsf-productionization-bundle"},
        "suite_sha256": digest, "plan_sha256": digest, "identity": ref("identity"),
        "population_complete": boolean, "validated_attempts": uint, "validated_processes": uint, "attempt_count_complete": boolean,
        "runs": array(ref("json"), 14), "comparisons": array(ref("json"), 16, 16),
        "limitations": array(string, 32, 1),
    })
    names = {"plan": "plan", "client-plan": "client_plan", "client-readiness": "readiness",
             "attempt": "attempt", "client-summary": "summary", "process": "process",
             "suite": "suite", "aggregate": "aggregate", "resources": "resources"}
    return {name + ".schema.json": {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://latent.fabric/schemas/optimization/" + name + ".schema.json",
        "$comment": "Structural validation is necessary; tools/validate_optimization_evidence.py performs mandatory semantic and integrity replay.",
        "$defs": deepcopy(definitions), "$ref": "#/$defs/" + key,
    } for name, key in names.items()}

"""Enumerate every offered request without importing the producer's oracle."""
import json
from tools.optimization_evidence.common import require
from tools.phase1_paired.common import INPUT
from . import model

MEDIA = "application/vnd.latent.wit-values.v1+json"
DIRTY = "engine-memory-dirty-4194304-a5"
TARGETS = (("engine-a", "engine-echo", "engine-a:echo/api@0.1.0", "echo"),
           ("engine-a", "engine-compute", "engine-a:benchmark/workloads@0.1.0", "optimization"),
           ("engine-a", "engine-generic", "engine-a:generic/values@0.1.0", "generic"),
           ("engine-b", "engine-generic", "engine-b:generic/values@0.1.0", "generic"),
           ("engine-a", "engine-capabilities", "engine-a:capabilities/api@0.1.0", "capabilities"),
           ("engine-b", "engine-capabilities", "engine-b:capabilities/api@0.1.0", "capabilities"),
           ("engine-a", "engine-memory", "engine-a:engine-memory/memory@0.1.0", "engine-memory"),
           ("engine-b", "engine-memory", "engine-b:engine-memory/memory@0.1.0", "engine-memory"))


def grant(name="G"):
    cpu, memory, wall, logs = {
        "G": (10_000_000_000, 16_777_216, 1000, 16384), "F": (50_000, 16_777_216, 1000, 16384),
        "M": (10_000_000_000, 4_194_304, 1000, 16384), "D": (10_000_000_000, 16_777_216, 50, 16384),
        "H": (10_000_000_000, 16_777_216, 5000, 16384), "R": (100_000_000, 8_388_608, 1000, 4096),
        "C": (10_000_000_000, 8_388_608, 1000, 4096)}[name]
    return {"cpu_fuel": str(cpu), "memory_bytes": str(memory), "wall_time_limit_millis": str(wall),
            "log_bytes": str(logs), "reserved_dimensions_zero": True}


def functional(index):
    require(1 <= index <= 24, "engine-functional-index")
    if index in (1, 2, 3, 4, 5, 6):
        marker = "a" if index % 2 else "b"
        function = "snapshot" if index <= 2 else "clocks" if index <= 4 else "log-probe"
        return (4 if marker == "a" else 5, function,
                [] if index <= 4 else [f"engine-log-{marker}", [{"name": "probe", "value": marker}]], None, "G", None)
    if index in (7, 8, 12, 14, 16, 24):
        return (2 if index in (7, 14) else 3, "bump", [], [1], "G", None)
    return {
        9: (6, "run", ["trap"], None, "R", "guest-trap"),
        10: (6, "run", ["success"], [692060160], "R", None),
        11: (2, "spin", [], None, "F", "resource-exhausted"),
        13: (3, "grow", [], None, "M", "resource-exhausted"),
        15: (2, "spin", [], None, "D", "deadline-exceeded"),
        17: (7, "run", ["cancel"], None, "C", "cancelled"),
        18: (7, "run", ["success"], [692060160], "R", None),
        **{n: (2 if n % 2 else 3, "spin", [], None, "H", "cancelled") for n in range(19, 23)},
        23: (2, "identify", [], [11], "G", None)}[index]


def expected(profile):
    # Use the existing independently implemented public workload arithmetic.
    from tools.optimization_evidence.workload import expected as workload
    result = []
    for phase in model.phases(profile):
        name = phase["name"]
        if name in ("echo", "concurrent-echo"):
            target, function, payload, output = 0, "echo", [INPUT], [{"ok": INPUT}]
        elif name == "compute":
            target, function, payload = 1, "compute", [7, 65536]
            output = json.loads(workload(function, payload))
        else:
            target, function, payload, output = 6, "run", ["success"], [692060160]
        for index in range(phase["warmup"] + phase["measured"]):
            result.append({"phase": name, "phase_kind": "warmup" if index < phase["warmup"] else "measured",
                           "index": index, "activation_id": f"engine-{name}-{index:04}", "target_index": target,
                           "function": function, "payload": payload, "output": output, "budget": grant(), "code": None})
    for index in range(1, 25):
        target, function, payload, output, budget, code = functional(index)
        result.append({"phase": "functional", "phase_kind": "functional", "index": index - 1,
                       "activation_id": f"engine-fn-{index:02}", "target_index": target, "function": function,
                       "payload": payload, "output": output, "budget": grant(budget), "code": code})
    return result

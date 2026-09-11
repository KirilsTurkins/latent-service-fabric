"""Fixed populations, ownership names and effective container resource controls."""
from tools.optimization_evidence.common import require
from tools.optimization_runner.plans import CONTRACT, SERVICE, TENANT, TOKEN

PREFIX = "latent.optimization.docker-"
CLIENT_PREFIX = "latent.optimization.infrastructure-client-"
DENSITIES = (1, 8, 32)
SERVICES = (SERVICE, *(f"{SERVICE}-{index}" for index in range(1, 32)))
MAX_TOTAL_BYTES = 1024**3
MAX_FILE_BYTES = 256 * 1024**2
MAX_CLIENT_BYTES = 32 * 1024**2
MAX_HELPER_BYTES = 8 * 1024**2
MAX_FILES = 4096
BASE_IMAGE = "debian:bookworm-slim@sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818"


def repetitions(profile):
    require(profile in ("smoke", "full"), "docker-profile")
    return 7 if profile == "full" else 1


def groups(profile, pair):
    require(type(pair) is int and 0 <= pair < repetitions(profile), "docker-pair")
    offset = pair % len(DENSITIES)
    density_order = DENSITIES[offset:] + DENSITIES[:offset]
    result = []
    for position, density in enumerate(density_order):
        arms = ("lsf", "native") if (pair + position) % 2 == 0 else ("native", "lsf")
        for arm in arms:
            result.append({"ordinal": len(result), "arm": arm, "density": density,
                           "phases": phases(profile, density)})
    return result


def phases(profile, density):
    repetitions(profile)
    require(type(density) is int and density in DENSITIES, "docker-density")
    full = profile == "full"
    result = []

    def add(name, kind, offers, concurrency, function="echo"):
        result.append({"ordinal": len(result), "name": name, "kind": kind,
                       "offers": offers, "concurrency": concurrency, "function": function,
                       "payload": [17, 10_000] if function == "compute" else ["optimization-reference-v1"]})

    add("first", "first", density, 1)
    add("density-warmup", "warmup", density * (4 if full else 1), 4)
    add("density-measured", "measured", density * (4 if full else 1), 4)
    if density == 1:
        add("echo-c1-warmup", "warmup", 8 if full else 2, 1)
        add("echo-c1-measured", "measured", 128 if full else 8, 1)
        add("compute-c1-warmup", "warmup", 4 if full else 1, 1, "compute")
        add("compute-c1-measured", "measured", 64 if full else 4, 1, "compute")
        add("echo-c4-warmup", "warmup", 8 if full else 4, 4)
        add("echo-c4-measured", "measured", 128 if full else 8, 4)
    return result


def resources(arm, density=1):
    require(arm in ("lsf", "native", "client"), "docker-resource-arm")
    require(type(density) is int and density in DENSITIES, "docker-resource-density")
    divisor = density if arm == "native" else 1
    memory = (256 * 1024**2 if arm == "client" else 2 * 1024**3) // divisor
    return {"cpu_period": 100_000, "cpu_quota": (200_000 if arm == "client" else 400_000) // divisor,
            "memory": memory, "memory_swap": memory,
            "pids_limit": (128 if arm == "client" else 512) // divisor,
            "nofile_soft": 1024, "nofile_hard": 1024,
            "cap_drop": ["ALL"], "no_new_privileges": True}


def plan(profile):
    pairs = repetitions(profile)
    all_groups = [groups(profile, pair) for pair in range(pairs)]
    offers = sum(phase["offers"] for group_set in all_groups for group in group_set for phase in group["phases"])
    require(offers == (9926 if profile == "full" else 300), "docker-frozen-population")
    return {"schema": PREFIX + "plan.v1", "profile": profile, "repetitions": pairs,
            "groups": all_groups, "logical_offers": str(offers), "client_owners": pairs,
            "measured_lsf_starts": 3 * pairs, "measured_native_starts": 41 * pairs,
            "measured_lsf_inventory_rpcs": 9 * pairs, "client_commands": 61 * pairs,
            "seed_templates": 3, "seed_lsf_starts": 3, "seed_management_rpcs": 88,
            "seed_guest_invokes": 0, "idle_window_millis": 250,
            "snapshots_per_application": 6, "ready_timeout_seconds": 120,
            "group_timeout_seconds": 600, "collection_timeout_seconds": 7200,
            "maximum_artifact_bytes": str(MAX_TOTAL_BYTES), "maximum_files": MAX_FILES,
            "maximum_file_bytes": str(MAX_FILE_BYTES), "maximum_client_bytes": str(MAX_CLIENT_BYTES),
            "tenant": TENANT, "contract": CONTRACT, "node_id": "optimization-node",
            "request_budget_millis": 1000, "cpu_fuel": 10_000_000_000,
            "memory_bytes": 67_108_864, "log_bytes": 16_384,
            "connect_timeout_millis": 5000, "response_timeout_millis": 5000,
            "client_workers": 2, "wrapper_workers": 2, "wrapper_live_connections": 32,
            "wrapper_direction_buffer_bytes": 16_384,
            "order": "rotate-density-by-pair-lsf-first-when-pair-plus-rotated-position-is-even"}

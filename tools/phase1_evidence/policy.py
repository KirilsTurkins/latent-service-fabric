"""Initial explicit observational reclamation policy, never fitted to a run."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .common import canonical, read_json, require, sha256, uint
from .statistics import distribution

POLICY_PATH = Path(__file__).resolve().parents[2] / "benchmarks/phase1/measurement-policy.json"
RSS_ALLOWANCE = 64 * 1024 * 1024
FD_ALLOWANCE = 2


def policy() -> dict[str, Any]:
    document = read_json(POLICY_PATH)
    require(document["schema"] == "latent.phase1.measurement-policy.v1"
            and document["observational_only"] is True and document["production_slo"] is False
            and document["dormant_scales"] == [100, 1000, 10000, 100000]
            and document["independent_runs"] == {"scale": 1, "soak": 3, "benchmark": 7}
            and document["reclamation"] == {"baseline": "idle-after-complete-mixed-cycle-warmup",
                "rss_growth_allowance_bytes": str(RSS_ALLOWANCE), "file_descriptor_growth_allowance": str(FD_ALLOWANCE),
                "tail_batch_window": 10, "retain_every_batch": True, "drop_outliers": False, "smoke_qualifies": False},
            "unexpected-measurement-policy")
    return {"sha256": sha256(canonical(document)), "document": document}


def reclamation(samples: list[dict[str, Any]], profile: str) -> dict[str, Any]:
    baseline = [sample for sample in samples if sample["label"] == "after-warmup"]
    finals = [sample for sample in samples if sample["label"] == "final"]
    batches = [sample for sample in samples if sample["label"] == "measured"]
    require(len(baseline) == 1 and len(finals) == 1 and bool(batches), "missing-reclamation-samples")
    warm, final = baseline[0]["resources"]["process"], finals[0]["resources"]["process"]
    rss = [uint(sample["resources"]["process"]["residentMemoryBytes"]) for sample in batches]
    fd = [uint(sample["resources"]["process"]["openFileDescriptors"]) for sample in batches]
    warm_rss, warm_fd = uint(warm["residentMemoryBytes"]), uint(warm["openFileDescriptors"])
    final_rss, final_fd = uint(final["residentMemoryBytes"]), uint(final["openFileDescriptors"])
    within = max(rss + [final_rss]) <= warm_rss + RSS_ALLOWANCE and max(fd + [final_fd]) <= warm_fd + FD_ALLOWANCE
    if profile == "full":
        require(within, "reclamation-allowance-exceeded")
    return {"status": "passed" if profile == "full" and within else "observed-only",
            "warm_rss_bytes": str(warm_rss), "final_rss_bytes": str(final_rss),
            "peak_idle_rss_bytes": str(max(rss + [warm_rss, final_rss])),
            "warm_file_descriptors": str(warm_fd), "final_file_descriptors": str(final_fd),
            "peak_idle_file_descriptors": str(max(fd + [warm_fd, final_fd])),
            "batch_count": str(len(batches)), "first_batches": distribution(rss[:10]),
            "last_batches": distribution(rss[-10:]), "all_batches": distribution(rss),
            "rss_growth_allowance_bytes": str(RSS_ALLOWANCE), "file_descriptor_growth_allowance": str(FD_ALLOWANCE)}

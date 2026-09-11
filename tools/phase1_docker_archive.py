"""Offline Docker publication replay with one shared build and two fixed populations.

The root aggregate belongs to run/ (full); smoke/aggregate.json belongs to smoke/.
Retained source files are evidence bytes and are never imported or executed.
"""
from pathlib import Path

from tools import package_phase0_evidence as paths
from tools.optimization_docker import aggregate, evidence, model
from tools.optimization_evidence.common import canonical, read_json, require


def _replay(directory, build, aggregate_path, profile):
    paths.existing_regular_file_path(directory / "suite.json", "Docker suite")
    retained = read_json(paths.existing_regular_file_path(aggregate_path, "Docker aggregate"),
                         model.MAX_HELPER_BYTES)
    derived = evidence.validate(directory, build)
    require(derived.get("status") == "passed" and derived.get("profile") == profile,
            "docker-archive-campaign-profile")
    regenerated = aggregate.aggregate(derived)
    require(canonical(retained) == canonical(regenerated),
            "docker archive aggregate differs from replayed evidence")
    expected_plan = model.plan(profile)
    pairs = model.repetitions(profile)
    require(regenerated.get("schema") == aggregate.SCHEMA
            and regenerated.get("profile") == profile
            and regenerated.get("status") == "complete"
            and regenerated.get("completed_paired_run") is True
            and regenerated.get("full_population_completed") is (profile == "full")
            and regenerated.get("acceptance_qualified") is (profile == "full")
            and type(regenerated.get("validated_pairs")) is int
            and regenerated["validated_pairs"] == pairs
            and regenerated.get("logical_offers") == expected_plan["logical_offers"]
            and canonical(regenerated.get("plan")) == canonical(expected_plan),
            "docker archive requires complete full and smoke populations")
    counts = regenerated.get("counts")
    expected_counts = {
        "offers": expected_plan["logical_offers"], "successful": expected_plan["logical_offers"],
        "seed_management_rpcs": "88", "seed_invokes": "0",
        "measured_application_owners": str(44 * pairs), "client_owners": str(pairs),
        "all_containers_removed": str(45 * pairs + 3),
    }
    require(isinstance(counts, dict)
            and all(counts.get(key) == value for key, value in expected_counts.items()),
            "docker-archive-offer-and-owner-populations")
    return regenerated


def verify(directory: Path):
    """Replay both original campaigns against the same retained build closure."""
    directory = paths.existing_directory_path(Path(directory), "Docker archive evidence")
    build = paths.existing_directory_path(directory / "build", "Docker shared build")
    run = paths.existing_directory_path(directory / "run", "Docker full campaign")
    smoke = paths.existing_directory_path(directory / "smoke", "Docker smoke campaign")
    full = _replay(run, build, directory / "aggregate.json", "full")
    checked_smoke = _replay(smoke, build, smoke / "aggregate.json", "smoke")
    # Each replay already binds executable/fixture bytes to this build directory.
    # Compare the resulting identities too; collector Python commits can differ
    # while their separately retained controls and unchanged binary inputs bind.
    for key in ("build_source", "images"):
        require(key in full and key in checked_smoke
                and canonical(full[key]) == canonical(checked_smoke[key]),
                "docker-archive-crossed-build-or-images")
    return {"full": full, "smoke": checked_smoke}

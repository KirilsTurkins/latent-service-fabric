"""Replay #112 against the immutable, separately supplied #111 package.

Only the installed validator imports code. Retained sources remain inert bytes.
The dependency keeps its own original transport and semantic validation limits.
"""
from contextlib import contextmanager
import gzip
from pathlib import Path
import re
import tempfile

from tools import package_phase0_evidence as paths
from tools import phase0_evidence
from tools.optimization_docker import aggregate as docker_aggregate
from tools.optimization_evidence.common import canonical, fields, read_json, require, sha256, text, uint, verify_artifact
from tools.optimization_kubernetes import aggregate, model, replay

DOCKER_ARCHIVE_SHA256 = "sha256:b51441c7d23eb9569f77d00026533e9a5395c7732b1109b38cfbc3defeca43fd"
REFERENCE_SCHEMA = model.PREFIX + "docker-reference.v1"


def _reference(directory, package, manifest):
    from tools import validate_phase1_archive as archive
    value = fields(read_json(directory / "docker-reference.json", model.MAX_HELPER_BYTES),
                   "schema archive manifest aggregate")
    require(value["schema"] == REFERENCE_SCHEMA, "kubernetes-docker-reference-schema")
    for key, name, maximum in (("archive", archive.ARCHIVE, archive.MAX_SPLIT_COMPRESSED),
                               ("manifest", archive.MANIFEST, 4 * 1024**2),
                               ("aggregate", "aggregate.json", archive.MAX_AGGREGATE_BYTES)):
        row = fields(value[key], "path bytes sha256")
        require(row["path"] == name and uint(row["bytes"]) <= maximum,
                "kubernetes-docker-reference-path-or-bound")
        actual = manifest["archive"] if key == "archive" else archive.file_reference(package / name, package, maximum)
        require(canonical(row) == canonical(actual), "kubernetes-docker-reference-mismatch")
    require(value["archive"]["sha256"] == DOCKER_ARCHIVE_SHA256,
            "kubernetes-docker-dependency-is-not-original-campaign")
    return value


@contextmanager
def _dependency(directory, docker_package):
    from tools import validate_phase1_archive as archive
    require(docker_package is not None, "kubernetes archive requires --docker-package")
    package = paths.existing_directory_path(Path(docker_package), "original Docker package")
    require(archive.evidence_kind(package) == "docker", "kubernetes-dependency-must-be-docker")
    manifest = archive.load_manifest(package)
    reference = _reference(directory, package, manifest)
    # Mandatory original Docker replay includes its smoke and failed attempts.
    require(canonical(archive.verify_package(package)) == canonical(manifest),
            "kubernetes-docker-manifest-changed-during-replay")
    with archive.archive_input(package, manifest) as compressed:
        require(archive.file_reference(compressed, compressed.parent, archive.MAX_SPLIT_COMPRESSED)
                == manifest["archive"], "kubernetes-docker-stream-changed")
        with tempfile.TemporaryDirectory(prefix="latent-kubernetes-docker-") as temporary:
            extracted = Path(temporary) / "docker"
            with gzip.open(compressed, "rb") as stream:
                names = phase0_evidence.extract_tar_stream(stream, extracted, "original Docker dependency",
                                                         maximum_files=archive.MAX_DOCKER_FILES)
            expected = {row["path"]: row for row in manifest["files"]}
            require(names == set(expected), "kubernetes-docker-extraction-file-set")
            for name, row in expected.items():
                require(archive.file_reference(extracted / name, extracted, 256 * 1024**2) == row,
                        "kubernetes-docker-extraction-checksum")
            require(archive.file_reference(compressed, compressed.parent, archive.MAX_SPLIT_COMPRESSED)
                    == manifest["archive"], "kubernetes-docker-stream-changed")
            require(canonical(_reference(directory, package, manifest)) == canonical(reference),
                    "kubernetes-docker-reference-changed")
            yield extracted, reference
            require(archive.file_reference(compressed, compressed.parent, archive.MAX_SPLIT_COMPRESSED)
                    == manifest["archive"], "kubernetes-docker-stream-changed")
            require(canonical(_reference(directory, package, manifest)) == canonical(reference),
                    "kubernetes-docker-reference-changed")


def _population(result, derived, profile):
    pairs = model.repetitions(profile)
    protocol = model.suite_startup_protocol(derived)
    plan = model.plan(profile, owner=derived["owner"], startup_protocol=protocol)
    offers = plan["workload"]["logical_offers"]
    require(result.get("schema") == aggregate.SCHEMA and result.get("status") == "complete"
            and result.get("profile") == profile and result.get("completed_paired_run") is True
            and result.get("full_population_completed") is (profile == "full")
            and result.get("acceptance_qualified") is (profile == "full")
            and result.get("acceptance_scope") == "complete-descriptive-deployment-comparison"
            and type(result.get("exact_effective_cpu_match")) is bool
            and type(result.get("validated_pairs")) is int and result["validated_pairs"] == pairs
            and result.get("logical_offers") == offers and canonical(result.get("plan")) == canonical(plan),
            "kubernetes archive requires complete full and smoke populations")
    counts = result.get("counts")
    expected = {"offers": offers, "successful": offers, "seed_management_rpcs": "0", "seed_invokes": "0",
                "measured_application_owners": 44 * pairs, "client_owners": pairs}
    require(isinstance(counts, dict) and all(canonical(counts.get(key)) == canonical(value)
            for key, value in expected.items()), "kubernetes-archive-offer-and-owner-populations")


def _exact(path, data, reason):
    path = paths.existing_regular_file_path(path, "Kubernetes report output")
    require(len(data) <= model.MAX_HELPER_BYTES and path.stat().st_size == len(data)
            and path.read_bytes() == data, reason)


def _tables(directory, full, original):
    outputs = {"aggregate.json": canonical(full) + b"\n", "docker-aggregate.json": canonical(original) + b"\n"}
    outputs.update({name.replace("_", "-") + ".csv": docker_aggregate._csv_bytes(full[name])
                    for name in aggregate.TABLES})
    references = []
    for name, data in outputs.items():
        _exact(directory / name, data, "kubernetes-archive-table-bytes-differ")
        references.append({"path": name, "bytes": str(len(data)), "sha256": sha256(data)})
    manifest = {"schema": model.PREFIX + "aggregate-files.v1", "profile": full["profile"],
                "suite_sha256": full["suite_sha256"], "docker_suite_sha256": original["suite_sha256"],
                "csv_null": "literal-null", "files": references}
    _exact(directory / "manifest.json", canonical(manifest) + b"\n", "kubernetes-archive-table-manifest-differs")
    return set(outputs) | {"manifest.json"}


def _campaign(directory, dependency, bootstrap, profile):
    paths.existing_regular_file_path(directory / "suite.json", "Kubernetes suite")
    derived, original = replay.validate(directory, dependency / "build", dependency / "run", bootstrap)
    require(derived.get("status") == "passed" and derived.get("profile") == profile,
            "kubernetes-archive-campaign-profile")
    result = aggregate.aggregate(derived, original)
    _population(result, derived, profile)
    return result, derived, original


def _cluster_cleanup(directory, bootstrap):
    # The helper is required even when no failed campaign preceded publication.
    from tools.optimization_kubernetes import cluster_cleanup_evidence
    return cluster_cleanup_evidence.validate(directory, bootstrap)


def _failure(directory, bootstrap, **dependencies):
    from tools.optimization_kubernetes import failure_evidence
    return failure_evidence.validate(directory, bootstrap, **dependencies)


def _failed_attempts(directory, bootstrap, cleanup_started, *, dependency=None):
    root = directory / "attempts"
    if not root.exists() and not root.is_symlink():
        return None
    root = paths.existing_directory_path(root, "failed Kubernetes attempts")
    index = fields(read_json(root / "index.json", model.MAX_HELPER_BYTES), "schema attempts")
    require(index["schema"] == model.PREFIX + "failed-attempts.v1"
            and isinstance(index["attempts"], list) and 1 <= len(index["attempts"]) <= 8,
            "kubernetes-failed-index")
    names, recoveries = [], []
    for row in index["attempts"]:
        fields(row, "directory qualified suite recovery")
        name = text(row["directory"], 64)
        require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", name) is not None
                and row["qualified"] is False, "kubernetes-failed-index-entry")
        names.append(name)
        attempt = paths.existing_directory_path(root / name, "failed Kubernetes campaign")
        for key in ("suite", "recovery"):
            if key == "recovery" and row[key] is None:
                continue
            reference = fields(row[key], "path bytes sha256")
            require(reference["path"] == name + "/" + key + ".json", "kubernetes-failed-index-path")
            verify_artifact(root, reference, model.MAX_FILE_BYTES)
        if row["recovery"] is None:
            require(dependency is not None and not (attempt / "recovery.json").exists()
                    and not (attempt / "recovery.json").is_symlink(), "kubernetes-failed-inline-recovery")
            recovered = _failure(attempt, bootstrap, build_root=dependency / "build", docker_root=dependency / "run")
            result_path = attempt / "suite.json"
        else:
            recovered = _failure(attempt, bootstrap)
            result_path = attempt / "recovery.json"
        require(canonical(read_json(result_path, model.MAX_FILE_BYTES)) == canonical(recovered),
                "kubernetes-failed-recovery-return-binding")
        require(uint(recovered["started_nanos"]) <= uint(recovered["finished_nanos"]) <= uint(cleanup_started),
                "kubernetes-failed-recovery-after-cluster-cleanup")
        recoveries.append(recovered)
    require(names == sorted(set(names)) and {entry.name for entry in root.iterdir()} == {"index.json", *names},
            "kubernetes-failed-index-coverage")
    return {"index": index, "recoveries": recoveries}


def _prior_smokes(directory, dependency, bootstrap, full, original, cleanup_started):
    """Replay earlier completed smokes separately from the current populations."""
    root = directory / "prior-smokes"
    if not root.exists() and not root.is_symlink():
        return None
    root = paths.existing_directory_path(root, "prior Kubernetes smokes")
    index = fields(read_json(root / "index.json", model.MAX_HELPER_BYTES), "schema campaigns")
    require(index["schema"] == model.PREFIX + "prior-smokes.v1"
            and isinstance(index["campaigns"], list) and 1 <= len(index["campaigns"]) <= 4,
            "kubernetes-prior-smoke-index")
    names, results = [], []
    for row in index["campaigns"]:
        fields(row, "directory suite aggregate")
        name = text(row["directory"], 64)
        require(re.fullmatch(r"smoke-[0-9]{2}", name) is not None, "kubernetes-prior-smoke-name")
        names.append(name)
        campaign = paths.existing_directory_path(root / name, "prior completed Kubernetes smoke")
        for key in ("suite", "aggregate"):
            reference = fields(row[key], "path bytes sha256")
            require(reference["path"] == name + "/" + key + ".json", "kubernetes-prior-smoke-path")
            verify_artifact(root, reference, model.MAX_FILE_BYTES)
        result, derived, prior_original = _campaign(campaign, dependency, bootstrap, "smoke")
        require(derived["run_id"] == name and derived["owner"] == full["owner"]
                and canonical(derived["bootstrap"]) == canonical(full["bootstrap"])
                and canonical(derived["build_source"]) == canonical(full["build_source"])
                and canonical(derived["images"]) == canonical(full["images"])
                and canonical(prior_original) == canonical(original), "kubernetes-prior-smoke-crossed-dependency")
        _exact(campaign / "aggregate.json", canonical(result) + b"\n", "kubernetes-prior-smoke-aggregate")
        finished = derived.get("cleanup_completion", derived)["finished_nanos"]
        require(uint(derived["finished_nanos"]) <= uint(finished) <= uint(cleanup_started),
                "kubernetes-prior-smoke-after-cluster-cleanup")
        results.append({"directory": name, "aggregate": result})
    require(names == sorted(set(names)) and {entry.name for entry in root.iterdir()} == {"index.json", *names},
            "kubernetes-prior-smoke-coverage")
    return {"index": index, "campaigns": results}


def verify(directory: Path, *, docker_package):
    """Validate dependency, both populations, all report bytes and final teardown."""
    directory = paths.existing_directory_path(Path(directory), "Kubernetes archive evidence")
    bootstrap = paths.existing_directory_path(directory / "bootstrap", "public Kubernetes bootstrap")
    require(all(entry.name.casefold() != "private" for entry in bootstrap.iterdir()),
            "kubernetes-archive-private-credentials")
    run = paths.existing_directory_path(directory / "run", "Kubernetes full campaign")
    smoke = paths.existing_directory_path(directory / "smoke", "Kubernetes smoke campaign")
    cleanup_root = paths.existing_directory_path(directory / "cluster-cleanup", "Kubernetes cluster cleanup")
    with _dependency(directory, docker_package) as (dependency, reference):
        full, derived, original = _campaign(run, dependency, bootstrap, "full")
        checked_smoke, smoke_derived, smoke_original = _campaign(smoke, dependency, bootstrap, "smoke")
        _exact(smoke / "aggregate.json", canonical(checked_smoke) + b"\n", "kubernetes-archive-smoke-aggregate-differs")
        for key in ("build_source", "images"):
            require(canonical(full[key]) == canonical(checked_smoke[key]), "kubernetes-archive-crossed-build-or-images")
        require(derived["owner"] == smoke_derived["owner"]
                and canonical(derived["bootstrap"]) == canonical(smoke_derived["bootstrap"])
                and canonical(original) == canonical(smoke_original), "kubernetes-archive-crossed-bootstrap-or-docker")
        original_aggregate = docker_aggregate.aggregate(original)
        require(canonical(read_json(dependency / "aggregate.json", model.MAX_HELPER_BYTES)) == canonical(original_aggregate),
                "kubernetes-archive-original-docker-aggregate-differs")
        names = _tables(directory, full, original_aggregate)
        cleanup = _cluster_cleanup(cleanup_root, bootstrap)
        require(uint(cleanup["started_nanos"]) >= max(uint(derived["finished_nanos"]), uint(smoke_derived["finished_nanos"]))
                and uint(cleanup["finished_nanos"]) >= uint(cleanup["started_nanos"]),
                "kubernetes-archive-cluster-cleanup-precedes-campaign")
        for campaign in (derived, smoke_derived):
            if "cleanup_completion" in campaign:
                require(uint(campaign["cleanup_completion"]["finished_nanos"]) <= uint(cleanup["started_nanos"]),
                        "kubernetes-archive-cluster-cleanup-precedes-completion")
        failed = _failed_attempts(directory, bootstrap, cleanup["started_nanos"], dependency=dependency)
        prior_smokes = _prior_smokes(directory, dependency, bootstrap, derived, original, cleanup["started_nanos"])
        require({entry.name for entry in directory.iterdir()} == names | {
                "docker-reference.json", "run", "smoke", "bootstrap", "cluster-cleanup"}
                | ({"attempts"} if failed is not None else set())
                | ({"prior-smokes"} if prior_smokes is not None else set()), "kubernetes-archive-unrecognized-root-entry")
    result = {"full": full, "smoke": checked_smoke, "dependency": reference, "cluster_cleanup": cleanup}
    if failed is not None:
        result["failed_attempts"] = failed
    if prior_smokes is not None:
        result["prior_smokes"] = prior_smokes
    if "cleanup_completion" in smoke_derived:
        result["smoke_cleanup_completion"] = smoke_derived["cleanup_completion"]
    return result

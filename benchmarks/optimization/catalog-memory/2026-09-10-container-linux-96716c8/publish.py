#!/usr/bin/env python3
"""Reproduce #107 publication with stronger gzip; measurement bytes stay unchanged."""
import argparse
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import time

HARNESS = "96716c8468e90246c59c6282d401c0f5402d0dda"


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024**2):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def write(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--work", required=True, type=Path)
    parser.add_argument("--pigz", default="/usr/bin/pigz", type=Path)
    args = parser.parse_args()
    repo = args.repository.resolve(strict=True)
    actual = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    assert actual == HARNESS
    assert not subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"], text=True).strip()
    sys.path.insert(0, str(repo))
    package = importlib.import_module("tools.package_phase1_evidence")
    source = package.paths.existing_directory_path(args.source, "measurement source")
    output = package.paths.absent_output_path(args.output)
    work = package.paths.absent_output_path(args.work)
    for left, right in ((source, output), (source, work), (work, output)):
        package.require(not left.is_relative_to(right) and not right.is_relative_to(left), "paths overlap")
    package.require(package.evidence_kind(source) == "catalog", "catalog evidence required")
    maximum_expanded, maximum_file = package.archive_bounds("catalog")
    files = {package.relative_path(path.relative_to(source).as_posix()): path
             for path in package.paths.regular_files(source, "measurement source")}
    package.require(len(files) <= package.MAX_FILES, "too many evidence files")
    package.require(sum(path.stat().st_size for path in files.values()) <= maximum_expanded, "expanded bound")
    work.mkdir(parents=True, exist_ok=False)
    stage = work / "package"
    stage.mkdir()
    receipt = {"schema": "latent.catalog.publication-compression.v1", "harness": actual,
               "recipe_sha256": sha(Path(__file__)), "status": "incomplete",
               "compressed_limit_bytes": package.MAX_SPLIT_COMPRESSED,
               "expanded_limit_bytes": maximum_expanded, "source_unchanged": False,
               "round_trip_tar_bytes_identical": False, "semantic_replay": "pending"}
    try:
        # Identical USTAR metadata, member order and member bytes to create_archive.
        raw = work / "raw-evidence.tar"
        references = []
        with raw.open("xb") as destination:
            with tarfile.open(fileobj=destination, mode="w|", format=tarfile.USTAR_FORMAT) as archive:
                for name, path in sorted(files.items()):
                    original = package.file_reference(path, path.parent, maximum_file)
                    references.append({**original, "path": name})
                    info = tarfile.TarInfo(name)
                    info.size, info.mode, info.mtime = int(original["bytes"]), 0o644, 0
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
        package.require(raw.stat().st_size <= maximum_expanded + package.MAX_FILES * 1024 + 10240,
                        "tar framing bound")
        raw_hash = sha(raw)
        pigz = args.pigz.resolve(strict=True)
        argv = [str(pigz), "-11", "-I", "15", "-b", "1024", "-p", "4", "-n", "-c", str(raw)]
        env = dict(os.environ)
        env.pop("GZIP", None)
        env.pop("PIGZ", None)
        receipt.update(command=argv, helper_sha256=sha(pigz),
                       helper_version=subprocess.check_output([str(pigz), "-V"], stderr=subprocess.STDOUT, text=True).strip(),
                       inherited_compression_options={"GZIP": "unset", "PIGZ": "unset"},
                       tar={"bytes": str(raw.stat().st_size), "sha256": raw_hash},
                       files=references)
        encoded = work / package.ARCHIVE
        began = time.monotonic_ns()
        with encoded.open("xb") as destination, (work / "pigz.log").open("xb") as log:
            result = subprocess.run(argv, env=env, stdout=destination, stderr=log, timeout=3600, check=False)
        receipt.update(helper_exit_code=result.returncode, helper_elapsed_nanos=str(time.monotonic_ns() - began),
                       gzip={"bytes": str(encoded.stat().st_size), "sha256": sha(encoded)})
        package.require(result.returncode == 0, "gzip helper failed")
        package.require(encoded.stat().st_size <= package.MAX_SPLIT_COMPRESSED, "compressed evidence exceeds unchanged bound")
        digest = hashlib.sha256()
        expanded = 0
        with gzip.open(encoded, "rb") as stream:
            while chunk := stream.read(1024**2):
                expanded += len(chunk)
                package.require(expanded <= raw.stat().st_size, "gzip expansion exceeds exact tar length")
                digest.update(chunk)
        package.require(expanded == raw.stat().st_size and "sha256:" + digest.hexdigest() == raw_hash,
                        "gzip tar round trip differs")
        receipt["round_trip_tar_bytes_identical"] = True
        package.require(sha(raw) == raw_hash, "source tar changed")
        for ref in references:
            path = files[ref["path"]]
            current = package.file_reference(path, path.parent, maximum_file)
            package.require(current["bytes"] == ref["bytes"] and current["sha256"] == ref["sha256"],
                            "measurement source changed")
        receipt["source_unchanged"] = True
        shutil.copyfile(encoded, stage / package.ARCHIVE)
        archive_reference = package.file_reference(stage / package.ARCHIVE, stage, package.MAX_SPLIT_COMPRESSED)
        manifest = {"schema": "latent.phase1.archive-manifest.v1", "archive": archive_reference,
                    "files": references, "total_bytes": str(sum(int(ref["bytes"]) for ref in references))}
        write(stage / package.MANIFEST, manifest)
        (stage / (package.ARCHIVE + ".sha256")).write_text(
            archive_reference["sha256"][7:] + "  " + package.ARCHIVE + "\n", encoding="ascii", newline="\n")
        package.write_split_archive(stage, archive_reference)
        shutil.copyfile(source / "aggregate.json", stage / "aggregate.json")
        package.verify_package(stage)
        receipt["semantic_replay"] = "passed"
        output.parent.mkdir(parents=True, exist_ok=True)
        stage.rename(output)
        receipt.update(status="complete", published_directory=str(output))
    except BaseException as error:
        receipt.update(status="failed", failure={"type": type(error).__name__, "message": str(error)[:2048]})
        raise
    finally:
        write(work / "publication-receipt.json", receipt)
    print(json.dumps({key: receipt[key] for key in ("status", "gzip", "source_unchanged",
                                                   "round_trip_tar_bytes_identical", "semantic_replay")}))


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Stage one immutable failed-run Java component for native fault observation.

Data only: no compiler, guest execution, dependency fallback or qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RUN, JOB, ARTIFACT = 44518163237, 135539652265, 14527262956
HEAD = "7efaa23b879aafd9d7e7e7770541e18e25d278fc"
MERGE = "3c7b65ffc79d9128cda45047575168c23edbc68d"
ARCHIVE = (75006714, "448a2bb4466933d16c67f0b5458801b22f2f57ea179d133bbae91cd64564ffc9")
FILES = {
    "FIBERS-COMPILE.json": (591632, "19ff504b0999e316364465c8d78b2136cc57eba03e280cb4747c4cfae35d8c32"),
    "build/component.wasm": (14327712, "42a9b236dce7ab4e2602a5426849452c20e52bad66273be5bb50e56e932905b1"),
    "src/Capsule.java": (12668, "6a2f7a5a13b3295761b0f18989e47cc7ff106a7c9546c559492247fcd36430c8"),
    "wit/service.wit": (340, "14c7bb47a7634153b4dcf39473a31f7f87f971f8c90a602b378be498dc938236"),
}
PREFIX = "java-activation-fibers/"


def require(value, reason):
    if not value:
        raise ValueError("java-fiber-fault-" + reason)


def bounded(path: Path, maximum: int) -> bytes:
    require(path.is_file() and not path.is_symlink(), "regular-input")
    with path.open("rb") as source:
        raw = source.read(maximum + 1)
    require(len(raw) <= maximum, "input-bound")
    return raw


def identity(raw: bytes):
    return len(raw), hashlib.sha256(raw).hexdigest()


def validate_origin(run, job, artifact):
    require(run.get("id") == RUN and run.get("head_sha") == HEAD
            and run.get("head_branch") == "fix/sdk-java-model-counts-20261118"
            and run.get("event") == "pull_request"
            and run.get("path") == ".github/workflows/java-guest-feasibility.yml"
            and run.get("status") == "completed" and run.get("conclusion") == "failure", "run")
    require(job.get("id") == JOB and job.get("run_id") == RUN
            and job.get("name") == "Actual Java sources, SDK ownership and enforced node"
            and job.get("status") == "completed" and job.get("conclusion") == "failure", "job")
    for name, conclusion in (
            ("Prepare the opt-in Java fibers and reference JDK controls", "success"),
            ("Execute signed activation threads with actual physical cleanup", "failure")):
        require(sum(step.get("name") == name and step.get("status") == "completed"
                    and step.get("conclusion") == conclusion for step in job.get("steps", [])) == 1,
                "original-stage")
    require(artifact.get("id") == ARTIFACT and artifact.get("expired") is False
            and artifact.get("name") == "java-guest-feasibility-" + MERGE
            and artifact.get("size_in_bytes") == ARCHIVE[0]
            and artifact.get("digest") == "sha256:" + ARCHIVE[1]
            and artifact.get("workflow_run", {}).get("id") == RUN
            and artifact.get("workflow_run", {}).get("head_sha") == HEAD, "artifact")


def stage(archive: Path, output: Path, expected_source: bytes):
    require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size == ARCHIVE[0],
            "archive-size")
    with archive.open("rb") as source:
        require(hashlib.file_digest(source, "sha256").hexdigest() == ARCHIVE[1], "archive-digest")
    require(not output.exists() and not output.is_symlink(), "fresh-output")
    selected = {}
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        for name, (size, digest) in FILES.items():
            member = PREFIX + name
            require(names.count(member) == 1, "unique-member")
            info = source.getinfo(member)
            require(not info.is_dir() and not info.flag_bits & 1
                    and stat.S_IFMT(info.external_attr >> 16) in (0, stat.S_IFREG)
                    and info.file_size == size, "member-kind-or-size")
            with source.open(info) as stream:
                raw = stream.read(size + 1)
            require(identity(raw) == (size, digest), "member-digest")
            selected[name] = raw
    require(selected["src/Capsule.java"] == expected_source, "current-source")
    record = json.loads(selected["FIBERS-COMPILE.json"])
    require(record.get("fixture") == "threads"
            and record.get("profile") == "teavm-activation-fibers-v1"
            and record.get("status") == "component-built-unqualified"
            and record.get("qualification") == "pending" and record.get("nodeExecution") == "not-run"
            and record.get("componentDigest") == "sha256:" + FILES["build/component.wasm"][1]
            and record.get("sourceDigest") == "sha256:" + FILES["src/Capsule.java"][1], "compile-record")
    model = record.get("completableModel", {})
    require(model.get("status") == "actual-locked-classlib-model-passed"
            and model.get("modelMethodBodies") == 205 and model.get("actualGeneratedCallbacks") == 28
            and model.get("fieldReferences") == "actual-declared-and-inherited-types-passed", "model-record")
    output.mkdir(parents=True)
    for name, raw in selected.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as destination:
            destination.write(raw)
    report = {"schemaVersion": "latent.java.fiber-fault.inputs.v1", "run": RUN, "job": JOB,
              "artifact": ARTIFACT, "head": HEAD, "merge": MERGE,
              "archive": {"bytes": ARCHIVE[0], "sha256": ARCHIVE[1]},
              "files": {name: {"bytes": size, "sha256": digest} for name, (size, digest) in FILES.items()},
              "guestCompiled": False, "runtimeQualified": False}
    (output / "fault-inputs.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    validate_origin(*(json.loads(bounded(args.metadata / (name + ".json"), 1024 * 1024))
                      for name in ("run", "job", "artifact")))
    stage(args.archive, args.output,
          bounded(ROOT / "sdk/java-guest/fibers/conformance/Capsule.java", FILES["src/Capsule.java"][0]))


if __name__ == "__main__":
    main()

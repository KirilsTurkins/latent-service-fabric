#!/usr/bin/env python3
"""Actual pinned-object and isolated generated-header rejection qualification."""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.application_dependencies import MANIFEST, LOCK, capture, document, trust_inputs
from tools.application_dependency_store import Store, materialize
from tools.application_dependency_tools import execute, specification
from tools.build_observation import build_environment
from tools.build_process import run_bounded_result
from tools.build_snapshot import canonical, digest
from tools.c_application_dependencies import archive_members, wasm_object
from tools.c_capsule_build import build as build_component
from tools.c_capsule_project import create
from tools.c_guest.compiler import Compiler
from tools.c_static_archive_build import build as build_archive
from tools.qualify_rust_capsules import inputs
from tools.rust_capsule_build import Commands
from tools.rust_capsule_project import ROOT, checked_path, fresh, read_json, write_json


class Controls:
    def __init__(self, project, output, contracts, packager, installed):
        self.project, self.output = project, output
        self.contracts, self.packager, self.installed = contracts, packager, installed
        self.before = inputs("c")
        self.result = {"schemaVersion": "latent.c-dependency-controls.v1", "status": "in-progress",
            "sourceInputs": self.before, "controls": [], "network": "denied-for-compiler-and-generators",
            "guestExecution": False, "releasePublication": "not-performed"}
        self.started, self.stage = time.monotonic(), "pinned-compiler"
        self.work = output / "compiler-work"
        self.work.mkdir(mode=0o700)
        sdk = self.work / "sdk"
        shutil.copytree(ROOT / "sdk/c-guest", sdk)
        self.commands = Commands(self.work, output, build_environment(self.work))
        self.compiler = Compiler(self.work / "compiler", 900, sdk=sdk, platform=None,
                                 commands=self.commands, installed=installed)
        self.result["compilerIsolation"] = self.compiler.enable_captured_isolation(self.work)
        self.installed = self.compiler.paths

    def denied(self, name, operation, expected):
        if time.monotonic() - self.started > 900:
            raise ValueError("C dependency control overall deadline exceeded")
        self.stage = name
        try:
            operation()
        except (ValueError, RuntimeError) as error:
            if expected not in str(error):
                raise AssertionError(name + ": unexpected rejection category") from error
            self.result["controls"].append({"id": name, "status": "passed", "expectedDenial": expected})
        else:
            raise AssertionError(name + ": incompatible input was accepted")

    def passed(self, name, **record):
        self.result["controls"].append({"id": name, "status": "passed", **record})

    def object(self, name, source, target="wasm32-wasi"):
        path, obj = self.work / (name + ".c"), self.work / (name + ".o")
        path.write_text(source, encoding="ascii")
        self.compiler.run("zig", "cc", "-std=c11", "-target", target, "-O2", "-Wall", "-Wextra", "-Werror",
                          "-c", str(path), "-o", str(obj))
        return obj

    def archive(self, name, members):
        path = self.work / (name + ".a")
        for offset in range(0, len(members), 100):
            self.compiler.run("zig", "ar", "rcs", str(path), *map(str, members[offset:offset + 100]))
        return path

    def captured_case(self, name, edit):
        project = self.output / ("project-" + name)
        shutil.copytree(self.project, project)
        manifest, lock = document(project / MANIFEST), document(project / LOCK)
        store = Store(project / "dependency-inputs/objects")
        origins = self.output / ("origins-" + name)
        origins.mkdir(mode=0o700)
        resolved = {row["id"]: row for row in lock["artifacts"]}
        for index, declaration in enumerate(manifest["artifacts"]):
            row = resolved[declaration["id"]]
            if declaration["format"] == "file":
                declaration["source"] = {"path": str(store.path(row["files"][0]["digest"]))}
            else:
                origin = origins / str(index)
                origin.mkdir(mode=0o700)
                materialize(row["files"], origin, store)
                declaration["source"] = {"path": str(origin)}
        edit(project, manifest)
        (project / MANIFEST).write_bytes(canonical(manifest) + b"\n")
        (project / LOCK).write_bytes(canonical(capture(project)) + b"\n")
        return project

    def rejected_build(self, name, project, expected, *, archive=False):
        destination = self.output / ("build-" + name)
        if archive:
            operation = lambda: build_archive(project, destination,
                "https://github.com/KirilsTurkins/latent-service-fabric", installed=self.installed)
            prefix = "STATIC-ARCHIVE"
        else:
            operation = lambda: build_component(project, destination, self.contracts, self.packager,
                "https://github.com/KirilsTurkins/latent-service-fabric", installed=self.installed)
            prefix = "BUILD"
        self.denied(name, operation, expected)
        marker = destination / (prefix + "-FAILED.json")
        receipt = read_json(marker)
        if (destination / (prefix + "-COMPLETE.json")).exists() or (destination / "component.wasm").exists():
            raise AssertionError("rejected input produced a component or success marker")
        self.result["controls"][-1].update(failureStage=receipt["stage"],
            commandCount=len(receipt["commands"]), failureReceiptDigest=digest(marker.read_bytes()))

    def objects_and_closure(self):
        first = self.object("strong-first", "int duplicate_symbol(void) { return 1; }\n")
        second = self.object("unused-strong-second", "int duplicate_symbol(void) { return 2; }\n")
        duplicate = self.archive("unused-duplicate", [first, second])
        self.denied("actual-unused-duplicate-strong-member", lambda: archive_members(duplicate.read_bytes()),
                    "c-static-archive-duplicate-strong-symbol")
        native = self.object("host-native", "int native_symbol(void) { return 3; }\n", "x86_64-linux-gnu")
        native_archive = self.archive("host-native", [native])
        self.denied("actual-host-native-member", lambda: archive_members(native_archive.read_bytes()),
                    "c-static-archive-host-native-member")
        wasm64 = self.object("wasm64", "int data; int load(int *p) { return *p + data; }\n", "wasm64-freestanding")
        wasm64_archive = self.archive("wasm64", [wasm64])
        self.denied("actual-wasm64-target-member", lambda: archive_members(wasm64_archive.read_bytes()),
                    "c-wasm-object-requires-unqualified-runtime-profile")
        empty = self.object("empty-unused", "/* actual empty relocatable translation unit */\n")
        members = []
        for index in range(1025):
            member = self.work / ("bounded-unused-" + str(index) + ".o")
            member.write_bytes(empty.read_bytes())
            members.append(member)
        overflow = self.archive("member-overflow", members)
        self.denied("actual-1025-member-archive-overflow", lambda: archive_members(overflow.read_bytes()),
                    "c-static-archive-member-collision-or-limit")
        # A real compiled object with adversarial duplicate core code sections.
        # Metadata framing alone deliberately accepts it; the pinned core validator must reject it.
        payload = empty.read_bytes() + b"\x0a\x01\x00\x0a\x01\x00"
        wasm_object(payload)
        invalid = self.work / "external-invalid-unused.a"
        header = (b"unused.o/".ljust(16) + b"0".ljust(12) + b"0".ljust(6) + b"0".ljust(6)
                  + b"100644".ljust(8) + str(len(payload)).encode().ljust(10) + b"`\n")
        invalid.write_bytes(b"!<arch>\n" + header + payload + (b"\n" if len(payload) & 1 else b""))
        validation = self.work / "invalid-validation"
        validation.mkdir(mode=0o700)
        self.denied("actual-unused-invalid-core-validation",
            lambda: self.compiler.validate_static_libraries((invalid,), validation), "wasm-tools failed")

        def duplicate_declarations(_project, manifest):
            row = next(row for row in manifest["artifacts"] if row["mount"].endswith(".a"))
            another = copy.deepcopy(row)
            another.update(id="unknown-independent-unused/archive/2", mount="dependencies/unused-second.a")
            manifest["artifacts"].append(another)

        project = self.captured_case("cross-archive-duplicates", duplicate_declarations)
        self.rejected_build("actual-duplicate-across-captured-archives", project,
                            "c-static-archive-duplicate-strong-symbol")

        def stale_profile(_project, manifest):
            row = next(row for row in manifest["artifacts"] if row["mount"].endswith(".a"))
            row["metadata"]["archiveProfile"]["checkpointProfile"] = "unobserved-thread-profile"

        project = self.captured_case("stale-profile", stale_profile)
        self.rejected_build("actual-stale-runtime-checkpoint-profile", project,
                            "c-static-archive-needs-current-observed-abi-profile-or-source-rebuild")
        for name in ("missing-transitive", "tampered-transitive"):
            project = self.captured_case(name, lambda *_: None)
            parser = next(row for row in document(project / LOCK)["artifacts"] if row["id"] == "zserge/jsmn/1.1.0")
            path = Store(project / "dependency-inputs/objects").path(parser["files"][0]["digest"])
            if name == "missing-transitive":
                path.unlink()  # Only this newly owned control's copied CAS object.
                expected = "dependency-artifact-missing-resolve-explicitly"
            else:
                original = path.read_bytes()
                path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
                expected = "dependency-artifact-integrity"
            self.rejected_build("actual-" + name, project, expected)

    def source_project(self, name, source, *, generated=None, provenance=None):
        project = create(self.output / ("project-" + name), "greeting")
        origin = self.output / ("original-library-" + name)
        origin.mkdir(mode=0o700)
        (origin / "library.c").write_bytes(source)
        if generated is not None:
            (origin / "generated.h").write_bytes(generated)
        declaration = {"id": "outside-c-catalogue/generated-or-source/" + name, "role": "application",
            "format": "directory", "mount": "dependencies/unknown-library", "source": {"path": str(origin)},
            "dependencies": [], "metadata": {"cSources": ["library.c"], "includeDirectories": ["."], "license": "Apache-2.0"}}
        if provenance is not None:
            declaration["metadata"]["generatedStage"] = provenance
        manifest = {"formatVersion": 1, "language": "c", "selection": {"target": "wasm32-wasi"},
                    "nativeLocks": [], "artifacts": [declaration], "transformations": []}
        (project / MANIFEST).write_bytes(canonical(manifest) + b"\n")
        (project / LOCK).write_bytes(canonical(capture(project)) + b"\n")
        for owned in origin.iterdir():
            owned.unlink()
        return project

    def generated_headers(self):
        self.stage = "isolated-generated-header"
        private = self.output / "outside-private-inputs"
        private.mkdir(mode=0o700)
        canary = "synthetic-private-credential-canary-c-controls"
        secret = private / "ambient-signing-key"
        secret.write_text(canary, encoding="ascii")
        ambient_header = private / "ambient-header.h"
        ambient_header.write_text("#define AMBIENT_VALUE 23\n", encoding="ascii")
        selected_inputs = self.output / "generator-inputs"
        selected_inputs.mkdir(mode=0o700)
        header = b"#define CAPTURED_VALUE 17\n"
        (selected_inputs / "selected.h").write_bytes(header)
        generator = self.output / "finite-reviewed-generator.sh"
        # Pass an absolute pathname as a separately approved argument, never shell-interpolate it.
        generator.write_text('#!/bin/sh\nset -eu\n'
            'test "${PRIVATE_CAPTURE_SECRET-unset}" = unset\n'
            'test ! -r "$1"\ntest ! -d "$HOME/.ssh"\n'
            'cp /inputs/selected.h /outputs/generated.h\n', encoding="ascii")
        generator.chmod(0o700)
        arguments = [str(secret)]
        selected = specification(generator, arguments, selected_inputs, tool_version="finite-c-header-v1")
        approved = digest(canonical(selected))
        self.denied("generator-incorrect-approval-before-execution", lambda: execute(generator, arguments, selected_inputs,
            self.output / "unapproved-output", self.output / "unapproved-receipt.json", tool_version="finite-c-header-v1",
            approved_identity=digest(b"not-this-tool-or-input")), "dependency-generator-approval-mismatch")
        if (self.output / "unapproved-output").exists():
            raise AssertionError("unapproved generator created outputs")
        previous = os.environ.get("PRIVATE_CAPTURE_SECRET")
        os.environ["PRIVATE_CAPTURE_SECRET"] = canary
        try:
            generated, receipt = self.output / "generated-output", self.output / "generated-stage.json"
            record = execute(generator, arguments, selected_inputs, generated, receipt,
                             tool_version="finite-c-header-v1", approved_identity=approved)
            if record["status"] != "succeeded" or record["cleanup"] != "reaped" or (generated / "generated.h").read_bytes() != header:
                raise AssertionError("finite generated-header stage did not complete exactly")
            self.passed("actual-approved-isolated-header-and-private-credential-absence", identity=approved,
                        receiptDigest=digest(receipt.read_bytes()), headerDigest=digest(header), cleanup=record["cleanup"])
            (selected_inputs / "selected.h").write_bytes(b"#define CAPTURED_VALUE 19\n")
            self.denied("generator-changed-input-invalidates-original-approval", lambda: execute(generator, arguments, selected_inputs,
                self.output / "stale-approval-output", self.output / "stale-approval-receipt.json", tool_version="finite-c-header-v1",
                approved_identity=approved), "dependency-generator-approval-mismatch")
            self.denied("generator-private-environment-declaration-denied", lambda: specification(generator, arguments, selected_inputs,
                tool_version="finite-c-header-v1", environment={"PRIVATE_CAPTURE_SECRET": canary}),
                "dependency-generator-environment-denied")
            project = self.source_project("generated-header",
                b'#include "generated.h"\nint unknown_generated_value(void) { return CAPTURED_VALUE; }\n',
                generated=header, provenance={"identity": approved, "receiptDigest": digest(receipt.read_bytes())})
            trust_before = trust_inputs(project)
            archive = build_archive(project, self.output / "archive-generated-header",
                "https://github.com/KirilsTurkins/latent-service-fabric", installed=self.installed)
            marker = read_json(archive / "STATIC-ARCHIVE-COMPLETE.json")
            public = (project / LOCK).read_bytes() + (archive / "application-dependencies.json").read_bytes()
            if any(value in public for value in (canary.encode(), str(private).encode(), b"original-library-generated-header")):
                raise AssertionError("private origin or synthetic credential reached public captured closure")
            self.passed("actual-generated-header-offline-c-archive-and-public-closure-redaction", archiveDigest=marker["archiveDigest"],
                profileDigest=marker["profileDigest"], receiptDigest=digest((archive / "STATIC-ARCHIVE-COMPLETE.json").read_bytes()),
                originalSourcesAvailable=False)
            tampered = self.output / "project-tampered-generated-header"
            shutil.copytree(project, tampered)
            row = next(row for row in document(tampered / LOCK)["artifacts"][0]["files"] if row["path"] == "generated.h")
            Store(tampered / "dependency-inputs/objects").path(row["digest"]).write_bytes(b"#define CAPTURED_VALUE 91\n")
            self.rejected_build("actual-captured-generated-header-tamper", tampered, "dependency-artifact-integrity", archive=True)
            changed = self.output / "project-changed-generator-selection"
            shutil.copytree(project, changed)
            manifest = document(changed / MANIFEST)
            manifest["artifacts"][0]["metadata"]["generatedStage"]["identity"] = digest(b"different-reviewed-generator")
            (changed / MANIFEST).write_bytes(canonical(manifest) + b"\n")
            self.rejected_build("actual-changed-generator-selection-lock-denial", changed, "dependency-lock-drift", archive=True)
            if trust_inputs(project) != trust_before:
                raise AssertionError("unchanged successful generated-header trust moved")
            escaped = self.source_project("absolute-include-escape",
                ('#include "' + str(ambient_header) + '"\nint escape_value(void) { return AMBIENT_VALUE; }\n').encode("ascii"))
            self.rejected_build("actual-absolute-include-outside-captured-namespace", escaped, "zig failed", archive=True)
            credentials = self.output / "project-credential-manifest"
            shutil.copytree(project, credentials)
            manifest = document(credentials / MANIFEST)
            manifest["artifacts"][0]["metadata"]["authorization"] = canary
            (credentials / MANIFEST).write_bytes(canonical(manifest) + b"\n")
            candidate = self.output / "credential-candidate.json"
            execution = run_bounded_result([sys.executable, str(ROOT / "tools/c_capsule.py"), "resolve", str(credentials),
                "--candidate", str(candidate)], self.output, build_environment(self.output), 30, 16384)
            failure = candidate.with_name(candidate.name + ".failed.json")
            failed = failure.read_bytes()
            if (execution.returncode != 1 or candidate.exists() or canary.encode() in failed + execution.stdout + execution.stderr
                    or read_json(failure)["reason"] != "dependency-credentials-denied"):
                raise AssertionError("CLI credential rejection or public redaction failed")
            self.passed("actual-c-cli-private-credential-rejection-and-redaction", exitCode=execution.returncode,
                        receiptDigest=digest(failed), diagnosticsDigest=digest(execution.stdout + execution.stderr))
            graph = self.output / "project-unclosed-graph"
            shutil.copytree(project, graph)
            manifest = document(graph / MANIFEST)
            manifest["artifacts"][0]["dependencies"] = ["missing-transitive/c/1"]
            (graph / MANIFEST).write_bytes(canonical(manifest) + b"\n")
            self.denied("actual-capture-unclosed-transitive-graph", lambda: capture(graph), "dependency-graph-not-closed")
            loop = self.output / "finite-generator-deadline.sh"
            loop.write_text('#!/bin/sh\nwhile :; do printf x >> /outputs/progress; done &\nwait\n', encoding="ascii")
            loop.chmod(0o700)
            selected = specification(loop, [], selected_inputs, tool_version="finite-deadline-control-v1")
            deadline_output, deadline_receipt = self.output / "deadline-output", self.output / "deadline-stage.json"
            self.denied("actual-generator-deadline-terminates-descendants", lambda: execute(loop, [], selected_inputs,
                deadline_output, deadline_receipt, tool_version="finite-deadline-control-v1",
                approved_identity=digest(canonical(selected)), timeout_seconds=0.25), "command-deadline")
            progress = deadline_output / "progress"
            size = progress.stat().st_size
            time.sleep(0.1)
            if progress.stat().st_size != size:
                raise AssertionError("timed-out generator descendant is still writing")
            if read_json(deadline_receipt)["cleanup"] != "reaped":
                raise AssertionError("generator deadline lacks confirmed process cleanup")
            self.result["controls"][-1].update(progressStable=True, receiptDigest=digest(deadline_receipt.read_bytes()),
                retainedCleanupClaim=read_json(deadline_receipt)["cleanup"])
            # A different output and newly approved identity, never a retry of the expired owner.
            fresh_output, fresh_receipt = self.output / "after-deadline-output", self.output / "after-deadline-stage.json"
            current = specification(generator, arguments, selected_inputs, tool_version="finite-c-header-v1")
            record = execute(generator, arguments, selected_inputs, fresh_output, fresh_receipt,
                             tool_version="finite-c-header-v1", approved_identity=digest(canonical(current)))
            if record["cleanup"] != "reaped" or (fresh_output / "generated.h").read_bytes() != b"#define CAPTURED_VALUE 19\n":
                raise AssertionError("fresh approved producer after deadline failed")
            self.passed("actual-fresh-generated-header-stage-after-deadline", cleanup=record["cleanup"],
                        receiptDigest=digest(fresh_receipt.read_bytes()))
        finally:
            if previous is None:
                os.environ.pop("PRIVATE_CAPTURE_SECRET", None)
            else:
                os.environ["PRIVATE_CAPTURE_SECRET"] = previous


def qualify(project, output, contracts, packager, *, installed=None):
    project, output, contracts, packager = map(checked_path, (project, output, contracts, packager))
    if project == output or project in output.parents or output in project.parents:
        raise ValueError("C dependency control output must have a separate owner")
    if not any(row["mount"].endswith(".a") for row in document(project / MANIFEST)["artifacts"]):
        raise ValueError("C dependency controls require the captured static qualification project")
    output = fresh(output)
    suite = None
    try:
        suite = Controls(project, output, contracts, packager, installed)
        suite.objects_and_closure()
        suite.generated_headers()
        suite.stage = "final-integrity"
        suite.compiler.check_unchanged()
        if inputs("c") != suite.before or time.monotonic() - suite.started > 900:
            raise ValueError("C dependency control source or overall deadline changed")
        suite.result.update(status="passed", seconds=round(time.monotonic() - suite.started, 6), commands=suite.commands.records)
        write_json(output / "CONTROLS-COMPLETE.json", suite.result)
        return suite.result
    except BaseException as error:
        result = suite.result if suite else {"schemaVersion": "latent.c-dependency-controls.v1"}
        result.update(status="failed", stage=suite.stage if suite else "pinned-compiler",
                      reason=type(error).__name__, commands=suite.commands.records if suite else [])
        write_json(output / "CONTROLS-FAILED.json", result)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--contracts-tool", type=Path, default=ROOT / "target/debug/examples/capsule_contracts")
    parser.add_argument("--packager", type=Path, default=ROOT / "target/debug/examples/package")
    args = parser.parse_args()
    result = qualify(args.project, args.output, args.contracts_tool, args.packager)
    print(json.dumps({"status": result["status"], "controls": len(result["controls"]), "seconds": result["seconds"]}))


if __name__ == "__main__":
    main()

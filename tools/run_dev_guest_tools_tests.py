#!/usr/bin/env python3
"""Compile maintained applications outside checkout using only staged tools."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import sys
import tempfile
import time

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.dev_workflow import build, build_cache, paths, project, snapshot, state
from tools.dev_workflow.common import DevError, decode, digest, encode, require


def exercise(payload: Path, packager: Path, output: Path, language: str, *, source_node: Path | None = None) -> dict:
    require(language in project.LANGUAGES, "unsupported-application-build-test-language")
    require(sys.platform == "linux" and os.geteuid() != 0 and not output.exists(), "unprivileged-linux-and-new-test-output-required")
    output.mkdir(mode=0o700, parents=True)
    temporary = Path(tempfile.mkdtemp(prefix="lsf-" + language + "-dev-tests-"))
    require(not temporary.is_relative_to(Path(__file__).resolve().parents[1]), "application-test-must-be-outside-checkout")
    require(not temporary.is_relative_to(payload), "application-test-must-be-outside-tool-prefix")
    receipt = {"schemaVersion": "latent.dev." + language + "-tools-test.v1", "language": language, "passed": False, "cleanup": "unconfirmed",
               "publisherAuthenticated": False, "wslQualified": False, "templates": {},
               "host": {"os": sys.platform, "architecture": platform.machine(), "kernel": platform.release(),
                        "effectiveUser": os.geteuid(), "libc": list(platform.libc_ver())}}
    start = time.monotonic()
    try:
        cli = temporary / "latent"
        shutil.copyfile(packager, cli)
        cli.chmod(0o700)
        receipt["packager"] = paths.digest_file(temporary, "latent", 256 * 1024 * 1024)[0]
        if source_node is not None:
            require(paths.digest_file(source_node, "bin/latent", 256 * 1024 * 1024)[0] == receipt["packager"],
                    "source-node-requires-the-same-observed-packager")
        index = decode(paths.read(payload, "templates.json"))
        require(set(index["templates"]) == {"greeting", "word-count", "shipping"}, "maintained-language-tutorials-required")
        for name, entry in index["templates"].items():
            case = temporary / (name + " spaces-\u00fc")
            case.mkdir(mode=0o700)
            # The frontend captures an arbitrary author path into a separately
            # named Linux workspace. Match that boundary: Unicode/spaces belong
            # to the author path, while compiler staging uses the owned ID path.
            author, root = case / "author", temporary / ("test-" + name)
            root.mkdir(mode=0o700)
            (root / "snapshots").mkdir(mode=0o700)
            template = payload / entry["path"]
            manifest = decode(paths.read(template, "template.json"))
            project.scaffold(template, author, manifest, entry["identity"])
            descriptor = manifest["project"]
            require(descriptor["language"] == language, "maintained-language-template-required")
            trusted = project.trust_identity(descriptor)
            def compile_current():
                record, content = snapshot.observe(author, descriptor["inputRoots"], tuple(descriptor["exclude"]))
                source = root / "snapshots" / record["identity"][7:]
                if not source.exists():
                    snapshot.materialize(source, record, content)
                state.atomic(root, "project.json", {"descriptor": descriptor, "trust": trusted,
                    "source": str(source), "snapshot": record["identity"]})
                return build.execute(root, source, descriptor, payload, trusted=trusted, cli=cli)
            compiled = compile_current()
            require(compile_current() == compiled, "unchanged-build-must-reuse-verified-attempt")
            source = root / "builds" / compiled["attempt"] / "source"
            complete = decode(paths.read(source, "output/BUILD-COMPLETE.json"))
            compiler = decode(paths.read(source, "output/compiler-BUILD-COMPLETE.json"))
            require(compiler["packageAssembled"] is False
                    and not any(item["stage"] == "package" for item in compiler["commands"]),
                    "language-recipe-must-leave-package-assembly-to-controller")
            packaging = decode(paths.read(source, "output/controller-packaging.json"))
            require(complete["packageAssembled"] is True and packaging["authority"] == "observed-local-build"
                    and packaging["compilerObservation"] == compiler["observationDigest"]
                    == digest(paths.read(source, "output/compiler-build-observation.json"))
                    and packaging["observation"] == complete["observationDigest"]
                    == digest(paths.read(source, "output/build-observation.json"))
                    and packaging["packager"] == receipt["packager"]
                    and packaging["packageDigest"] == compiled["package"]["packageDigest"],
                    "controller-packaging-must-retain-actual-compiler-and-packager-observations")
            require(complete["componentDigest"] == compiler["componentDigest"] == compiled["artifacts"]["component"],
                    "observed-compiler-component-identity")
            # Retain exact common scenarios and compiled bytes for Windows/Linux
            # differential execution. This build probe itself does not invoke them.
            retained = output / name
            retained.mkdir(mode=0o700)
            (retained / "latent.project.json").write_bytes(encode(descriptor))
            shutil.copytree(author / "tests", retained / "tests")
            shutil.copytree(source / "output", retained / "output")
            receipt["templates"][name] = {"build": compiled, "cacheHit": True, "outsideCheckout": True,
                                          "authorPathIncludesSpacesAndUnicode": True}
            if source_node is not None:
                from tools.dev_node_application_probe import run as run_node
                receipt["templates"][name]["node"] = run_node(root, source_node, payload, descriptor, output / name / "node")
            if name == "greeting":
                source_name = "app/src/" + {"rust": "lib.rs", "c": "main.c", "java": "dev/latent/app/Capsule.java",
                    "dotnet": "Main.cs", "go": "main.go", "typescript": "main.ts"}[language]
                original = (author / source_name).read_bytes()
                (author / source_name).write_bytes(original + b"\nthis is not valid source;\n")
                try:
                    compile_current()
                except DevError as error:
                    require(not error.uncertain and error.code == "guest-build-failed-last-deployment-retained",
                            "compiler-failure-must-be-known-and-reaped")
                    require(any(item["path"] == source_name for item in error.diagnostics), "source-diagnostic-required")
                else:
                    raise DevError("invalid-source-was-accepted")
                require(state.load(root, "last-build.json")["receipt"] == compiled, "failed-compile-replaced-last-accepted-build")
                require(b"Hello, " in original, "maintained-greeting-change-needs-review")
                # The C template uses fixed buffer offsets; preserve that length.
                (author / source_name).write_bytes(original.replace(b"Hello, ", b"Howdy, "))
                changed = compile_current()
                require(changed["artifacts"]["component"] != compiled["artifacts"]["component"]
                        and changed["attempt"] != compiled["attempt"], "changed-source-must-build-a-new-component")
                receipt["templates"][name].update(compileFailureRetainedPrevious=True,
                    failureDiagnosticsMapped=True, changedComponent=changed["artifacts"]["component"])
        receipt.update(passed=True, cleanup="reaped")
    finally:
        attempts = list(temporary.glob("test-*/builds/*"))
        known = False
        try:
            known = all(build_cache.owner(path)["state"] in {"created", "failed", "complete"} for path in attempts)
            for path in temporary.glob("test-*/source-node-probe.json"):
                known &= decode(paths.read(path.parent, path.name))["cleanup"] == "owned-node-and-client-processes-reaped"
            if not receipt["passed"]:
                for attempt in attempts:
                    retained = output / "failed-attempts" / attempt.name
                    retained.mkdir(mode=0o700, parents=True)
                    for name in ("output/BUILD-FAILED.json", "build-cache/compiler-stdout.log", "build-cache/compiler-stderr.log"):
                        if (attempt / "source" / name).is_file():
                            (retained / Path(name).name).write_bytes(paths.read(attempt / "source", name, 4 * 1024 * 1024))
                    used = 0
                    for directory in ("logs", "compiler-logs"):
                        for log in sorted((attempt / "source/output" / directory).glob("*")):
                            if log.is_file() and log.suffix in {".log", ".txt", ".json"}:
                                raw = paths.read(log.parent, log.name, 4 * 1024 * 1024)
                                used += len(raw)
                                require(used <= 20 * 1024 * 1024, "failed-compiler-evidence-limit")
                                (retained / (directory + "-" + log.name)).write_bytes(raw)
        except (DevError, OSError):
            known = False
        if known:
            try:
                shutil.rmtree(temporary)
                receipt["cleanup"] = "reaped"
            except OSError:
                receipt.update(passed=False, cleanup="filesystem-cleanup-incomplete", retainedAttemptRoot=str(temporary))
        else:
            receipt.update(passed=False, cleanup="unconfirmed", retainedAttemptRoot=str(temporary))
        receipt["seconds"] = round(time.monotonic() - start, 3)
        (output / "receipt.json").write_bytes(encode(receipt))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--packager", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--language", choices=sorted(project.LANGUAGES), required=True)
    parser.add_argument("--source-node", type=Path, help="Explicit contributor node binaries/helper; never installed-artifact qualification")
    args = parser.parse_args()
    receipt = exercise(args.payload.resolve(strict=True), args.packager.resolve(strict=True), args.output.absolute(), args.language,
                       source_node=args.source_node.resolve(strict=True) if args.source_node else None)
    print(json.dumps({"passed": receipt["passed"], "cleanup": receipt["cleanup"], "templates": list(receipt["templates"]),
                      "publisherAuthenticated": False, "wslQualified": False}))
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

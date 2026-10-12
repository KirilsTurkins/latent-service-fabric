#!/usr/bin/env python3
"""Observe the existing GitHub dependency-cache backend without promoting it.

Only the isolated development-push experiment may write its new namespaces.
Read-only collection requires completed jobs, exact source and equivalent cases.
Cache-action elapsed times include lookup/pruning/compression and transfer; they
are never presented as separately measured network or decompression times.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import sys
import time
import urllib.parse
import urllib.request

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import ci_cargo_cache as cache, ci_cargo_evaluate as evaluation

KINDS = ("baseline", "recipe")
STATES = evaluation.STATES
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_PAGES = 20
PREFIX = "lsf-cargo-service-v1"


def identity(kind: str, experiment: str, root: Path, env: dict[str, str]) -> dict:
    if kind not in KINDS or re.fullmatch(r"[1-9][0-9]*-[1-9][0-9]*", experiment) is None:
        raise ValueError("invalid-cache-service-experiment")
    if env.get("GITHUB_EVENT_NAME") != "push" or env.get("GITHUB_REF") != "refs/heads/development":
        raise ValueError("cache-service-experiment-requires-development-push")
    if env.get("GITHUB_RUN_ID", "") + "-" + env.get("GITHUB_RUN_ATTEMPT", "") != experiment:
        raise ValueError("cache-service-experiment-run-mismatch")
    configuration = "current" if kind == "baseline" else "ci-correctness"
    observed = cache.observe(root, configuration, "rust", env)
    suffix = "lsf-ci-dependencies-v2" if kind == "baseline" else cache.NAMESPACE + "-" + observed["digest"]
    return {"kind": kind, "configuration": configuration, "experiment": experiment,
            "prefix": PREFIX + "-" + experiment + "-" + kind + "-" + suffix,
            "source": env["GITHUB_SHA"], "ref": env["GITHUB_REF"], "event": env["GITHUB_EVENT_NAME"],
            "observedBuildIdentity": observed, "productionCacheNamespaceSelected": False}


def duration(step: dict) -> float:
    if step.get("status") != "completed" or step.get("conclusion") != "success":
        raise ValueError("cache-service-step-not-completed-successfully")
    start, end = (dt.datetime.fromisoformat(step[key].replace("Z", "+00:00"))
                  for key in ("started_at", "completed_at"))
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError("invalid-cache-service-step-times")
    return (end - start).total_seconds()


def reconcile(reports: list[dict], jobs: list[dict], entries: list[dict], *,
              source: str, run_id: int, attempt: int) -> dict:
    expected = {(kind, state) for kind in KINDS for state in STATES}
    samples, digests, identities = {}, set(), {}
    experiment = f"{run_id}-{attempt}"
    for report in reports:
        ident, measured = report["identity"], report["evaluation"]
        rows = measured["samples"]
        if len(rows) != 1:
            raise ValueError("cache-service-report-must-have-one-sample")
        sample = rows[0]
        pair = (ident["kind"], sample["state"])
        if pair not in expected or pair in samples:
            raise ValueError("missing-or-duplicate-cache-service-sample")
        previous = identities.setdefault(pair[0], ident["observedBuildIdentity"])
        if previous != ident["observedBuildIdentity"]:
            raise ValueError("cold-warm-cache-service-build-identity-changed")
        if (ident["source"] != source or ident["experiment"] != experiment
                or ident["ref"] != "refs/heads/development" or ident["event"] != "push"
                or not ident["prefix"].startswith(PREFIX + "-" + experiment + "-" + pair[0] + "-")
                or ident["configuration"] != ("current" if pair[0] == "baseline" else "ci-correctness")
                or measured["configuration"] != ident["configuration"]
                or measured["cacheIdentity"] != ident["observedBuildIdentity"]
                or not measured["passed"] or not sample["passed"]
                or sample["cacheServiceExactHit"] != (pair[1] != "cold")
                or measured["cacheBackend"] != "GitHub-cache-service-pinned-rust-cache"):
            raise ValueError("unqualified-cache-service-sample")
        invocations = [invocation.name for recipe in evaluation.ci_cargo.RUST_RECIPES
                       for invocation in evaluation.ci_cargo.RECIPES[recipe]]
        if sample["observations"] != [f"{pair[1]}/{name}/observation.json" for name in invocations]:
            raise ValueError("cache-service-reviewed-invocations-incomplete")
        peak = sample["maximumChildRssKiB"]
        if type(peak) is not int or peak <= 0:
            raise ValueError("cache-service-memory-observation-missing")
        digest = sample["caseIdentityDigest"]
        if (re.fullmatch(r"[a-f0-9]{64}", digest) is None
                or type(sample["activeCases"]) is not int or sample["activeCases"] <= 0):
            raise ValueError("cache-service-case-observation-missing")
        digests.add((digest, sample["activeCases"]))
        label = f"Cache sample ({pair[0]} / {pair[1]})"
        selected_jobs = [job for job in jobs if job["name"] == label or job["name"].endswith(" / " + label)]
        if len(selected_jobs) != 1:
            raise ValueError("cache-service-job-missing-or-ambiguous")
        job = selected_jobs[0]
        if job["run_id"] != run_id or job["run_attempt"] != attempt or job["head_sha"] != source:
            raise ValueError("cache-service-job-source-or-run-mismatch")
        if job["status"] != "completed" or job["conclusion"] != "success":
            raise ValueError("cache-service-job-not-completed-successfully")
        steps = job["steps"]
        def one(name: str) -> dict:
            matches = [step for step in steps if step["name"] == name]
            if len(matches) != 1:
                raise ValueError("cache-service-step-missing-or-ambiguous")
            return matches[0]
        duration(one("Execute every reviewed Cargo invocation"))
        restore_seconds = duration(one("Restore dependency cache"))
        post_seconds = duration(one("Post Restore dependency cache"))
        caches = [entry for entry in entries if entry["key"].startswith(ident["prefix"] + "-")
                  and entry["ref"] == "refs/heads/development"]
        if len(caches) != 1 or caches[0]["size_in_bytes"] <= 0:
            raise ValueError("cache-service-saved-entry-missing-or-ambiguous")
        samples[pair] = {"kind": pair[0], "state": pair[1], "jobId": job["id"],
            "source": source, "caseIdentityDigest": digest, "activeCases": sample["activeCases"],
            "completedSuiteSeconds": sample["completedSuiteSeconds"],
            "builtArtifactRecords": sample["builtArtifactRecords"], "freshArtifactRecords": sample["freshArtifactRecords"],
            "observations": sample["observations"], "restoreActionSeconds": restore_seconds,
            "maximumChildRssKiB": peak,
            "saveActionSeconds": post_seconds if pair[1] == "cold" else None,
            "readOnlyPostActionSeconds": post_seconds if pair[1] != "cold" else None,
            "cacheBytes": caches[0]["size_in_bytes"], "cacheId": caches[0]["id"]}
    if set(samples) != expected or len(digests) != 1:
        raise ValueError("incomplete-or-differently-selected-cache-service-comparison")
    case_digest, case_count = digests.pop()
    return {"schemaVersion": "latent.ci.cargo-cache-service.v1", "passed": True,
            "source": source, "runId": run_id, "runAttempt": attempt,
            "samples": [samples[(kind, state)] for kind in KINDS for state in STATES],
            "samplesPerCandidate": {kind: {"cold": 1, "warm": 2} for kind in KINDS},
            "caseIdentityDigest": case_digest, "activeCases": case_count, "eligibleForAutomaticDefaultPromotion": False,
            "networkTransferSeconds": None, "separateExtractionSeconds": None,
            "costInterpretation": "cache-action elapsed time includes lookup, pruning/compression or extraction and service transfer",
            "uncertainty": "one cold and two serial warm samples per candidate on separate hosted runners; no randomized order or confidence interval",
            "defaultDecision": "retain baseline pending review of complete observations and end-to-end CI"}


def get_json(path: str, token: str, deadline: float) -> dict:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError("cache-service-api-overall-deadline")
    request = urllib.request.Request("https://api.github.com/" + path,
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"})
    with urllib.request.urlopen(request, timeout=min(30, remaining)) as response:
        raw = response.read(MAX_JSON_BYTES + 1)
    if len(raw) > MAX_JSON_BYTES:
        raise ValueError("cache-service-api-response-limit")
    return json.loads(raw)


def pages(path: str, field: str, token: str, deadline: float) -> list[dict]:
    rows = []
    for page in range(1, MAX_PAGES + 1):
        data = get_json(path + ("&" if "?" in path else "?") + f"per_page=100&page={page}", token, deadline)
        batch = data[field]
        rows.extend(batch)
        if len(batch) < 100:
            return rows
    raise ValueError("cache-service-api-page-limit")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    command = parser.add_subparsers(dest="command", required=True)
    identify = command.add_parser("identity")
    identify.add_argument("--kind", choices=KINDS, required=True)
    identify.add_argument("--experiment", required=True)
    identify.add_argument("--output", type=Path, required=True)
    identify.add_argument("--github-output", type=Path, required=True)
    finalize = command.add_parser("sample-report")
    finalize.add_argument("--identity", type=Path, required=True)
    finalize.add_argument("--evaluation", type=Path, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    collect = command.add_parser("collect")
    collect.add_argument("--reports", type=Path, required=True)
    collect.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "identity":
            value = identity(args.kind, args.experiment, evaluation.ci_cargo.ROOT, dict(os.environ))
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as out:
                json.dump(value, out, indent=2)
            with args.github_output.open("a", encoding="utf-8") as out:
                out.write(f"prefix={value['prefix']}\nconfiguration={value['configuration']}\n")
        elif args.command == "sample-report":
            value = {"identity": json.loads(args.identity.read_bytes()),
                     "evaluation": json.loads(args.evaluation.read_bytes())}
            if not value["evaluation"]["passed"]:
                raise ValueError("failed-cache-service-evaluation")
            rows = value["evaluation"]["samples"]
            if len(rows) != 1:
                raise ValueError("cache-service-single-sample-required")
            metrics = []
            for name in rows[0]["observations"]:
                path = args.evaluation.parent / name
                if (Path(name).is_absolute() or ".." in Path(name).parts or path.is_symlink()
                        or path.stat().st_size > MAX_JSON_BYTES):
                    raise ValueError("unsafe-cache-service-invocation-observation")
                observed = json.loads(path.read_bytes())
                if not observed["passed"] or observed["metrics"] is None:
                    raise ValueError("cache-service-completed-native-metrics-required")
                metrics.append(observed["metrics"]["maximumChildRssKiB"])
            if not metrics:
                raise ValueError("cache-service-native-metrics-missing")
            peak = max(metrics)
            if type(peak) not in (int, float) or not math.isfinite(peak) or peak <= 0 or int(peak) != peak:
                raise ValueError("invalid-cache-service-native-memory-observation")
            rows[0]["maximumChildRssKiB"] = int(peak)
            rows[0]["rssDefinition"] = "GNU time maximum child RSS, not simultaneous process-tree RSS"
            with args.output.open("x", encoding="utf-8") as out:
                json.dump(value, out, indent=2)
        else:
            repository = os.environ["GITHUB_REPOSITORY"]
            if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository) is None:
                raise ValueError("invalid-cache-service-repository")
            run_id, attempt = int(os.environ["GITHUB_RUN_ID"]), int(os.environ["GITHUB_RUN_ATTEMPT"])
            files = sorted(args.reports.glob("*/service-sample.json"))
            if len(files) != 6 or any(p.is_symlink() or p.stat().st_size > MAX_JSON_BYTES for p in files):
                raise ValueError("cache-service-six-bounded-sample-reports-required")
            reports = [json.loads(path.read_bytes()) for path in files]
            token = os.environ["GH_TOKEN"]
            deadline = time.monotonic() + 120
            jobs = pages(f"repos/{repository}/actions/runs/{run_id}/attempts/{attempt}/jobs", "jobs", token, deadline)
            scope = urllib.parse.urlencode({"key": PREFIX + f"-{run_id}-{attempt}-", "ref": "refs/heads/development"})
            entries = pages(f"repos/{repository}/actions/caches?{scope}", "actions_caches", token, deadline)
            value = reconcile(reports, jobs, entries, source=os.environ["GITHUB_SHA"], run_id=run_id, attempt=attempt)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x", encoding="utf-8") as out:
                json.dump(value, out, indent=2)
        return 0
    except (OSError, KeyError, TypeError, ValueError) as error:
        # API failures must not serialize request headers or credential-bearing URLs.
        print("Cargo cache-service observation failed: " + type(error).__name__, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

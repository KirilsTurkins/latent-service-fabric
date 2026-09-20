#!/usr/bin/env python3
"""Select a successful development CI artifact for protected Pages publication."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.docs_pages_policy import (
    MAX_ARCHIVE, REPOSITORY, SITE_URL, archive_files, commit, integer, require,
    rollback_receipt, select_artifact, stage_site, validate_run, verify_staged_site,
)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def fetch(url, maximum, *, authenticated=False, redirects=0):
    require(url.startswith("https://") and redirects <= 3, "https-download")
    headers = {"User-Agent": "LSF-reviewed-pages-publisher", "Accept": "application/vnd.github+json"}
    if authenticated:
        require(urllib.parse.urlsplit(url).netloc == "api.github.com", "api-authority")
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
        headers["X-GitHub-Api-Version"] = "2022-11-28"
    request = urllib.request.Request(url, headers=headers)
    try:
        response = urllib.request.build_opener(NoRedirect).open(request, timeout=30)
    except urllib.error.HTTPError as error:
        if error.code in (301, 302, 303, 307, 308):
            location = urllib.parse.urljoin(url, error.headers["Location"])
            error.close()
            # Artifact storage receives no GitHub token, including on later redirects.
            return fetch(location, maximum, redirects=redirects + 1)
        raise
    with response:
        length = response.headers.get("Content-Length")
        require(length is None or (length.isdecimal() and int(length) <= maximum), "download-size")
        data = response.read(maximum + 1)
        require(len(data) <= maximum, "download-size")
        return data


def api(path):
    require(path.startswith("/") and ".." not in path, "api-path")
    return json.loads(fetch("https://api.github.com/repos/" + REPOSITORY + path,
                           4 * 1024 * 1024, authenticated=True))


def artifacts(run):
    value = api(f"/actions/runs/{run}/artifacts?per_page=100")
    require(value["total_count"] <= 100, "artifact-list-bound")
    return value["artifacts"]


def download(item):
    data = fetch(f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{item['id']}/zip",
                 MAX_ARCHIVE, authenticated=True)
    return archive_files(data, item["digest"])


def live_publication():
    return json.loads(fetch(SITE_URL + "publication.json", 256 * 1024))


def check_authority():
    require(os.environ.get("GITHUB_REPOSITORY") == REPOSITORY, "publisher-repository")
    require(os.environ.get("GITHUB_REF") == "refs/heads/release"
            and os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch", "publisher-ref-event")


def guard(receipt):
    check_authority()
    require(receipt.get("repository") == REPOSITORY and receipt.get("schema") == 1, "publication-receipt")
    require(receipt.get("publisherRun") == integer(os.environ["GITHUB_RUN_ID"])
            and receipt.get("publisherAttempt") == integer(os.environ["GITHUB_RUN_ATTEMPT"])
            and receipt.get("publisherSource") == commit(os.environ["GITHUB_SHA"]), "publisher-identity")
    if receipt["mode"] == "publish":
        require(api("/branches/development")["commit"]["sha"] == receipt["source"], "stale-development")
    else:
        require(receipt["mode"] == "rollback", "publication-mode")
        require(live_publication().get("source") == commit(receipt["expectedLiveSource"]), "live-source-changed")


def select(args):
    check_authority()
    source, run_id, attempt = commit(args.source), integer(args.run), integer(args.attempt)
    repo = json.loads(fetch("https://api.github.com/repos/" + REPOSITORY, 262144, authenticated=True))
    require(repo.get("full_name") == REPOSITORY and repo.get("default_branch") == "release", "repository-authority")
    run = api(f"/actions/runs/{run_id}")
    validate_run(run, repo["id"], source, attempt, api("/actions/workflows/ci.yml")["id"])
    item = select_artifact(artifacts(run_id), run, repo["id"], f"docs-site-{source}-{run_id}-{attempt}")
    security = api(f"/actions/workflows/security-baseline.yml/runs?head_sha={source}&event=push&per_page=10")
    matching_security = [candidate for candidate in security.get("workflow_runs", [])
                         if candidate.get("head_sha") == source and candidate.get("head_branch") == "development"
                         and candidate.get("head_repository", {}).get("id") == repo["id"]]
    require(matching_security and matching_security[0].get("status") == "completed"
            and matching_security[0].get("conclusion") == "success", "security-baseline-result")
    receipt = {"schema": 1, "repository": REPOSITORY, "source": source,
               "ciRun": run_id, "ciAttempt": attempt, "artifactId": item["id"],
               "artifactDigest": item["digest"], "mode": args.mode,
               "publisherRun": integer(os.environ["GITHUB_RUN_ID"]),
               "publisherAttempt": integer(os.environ["GITHUB_RUN_ATTEMPT"]),
               "publisherSource": commit(os.environ["GITHUB_SHA"]), "url": SITE_URL}
    if args.mode == "rollback":
        prior_id = integer(args.previous_publication_run)
        prior = api(f"/actions/runs/{prior_id}")
        validate_run(prior, repo["id"], prior["head_sha"], prior["run_attempt"],
                     api("/actions/workflows/docs-pages.yml")["id"], publisher=True)
        previous = select_artifact(artifacts(prior_id), prior, repo["id"],
                                   f"docs-pages-receipt-{prior_id}-{prior['run_attempt']}")
        rollback_receipt(download(previous), source, run_id, attempt, item)
        receipt.update(expectedLiveSource=commit(args.expected_live_source), previousPublicationRun=prior_id)
    else:
        require(not args.previous_publication_run and not args.expected_live_source, "unexpected-rollback-input")
    guard(receipt)
    require(not args.output.exists(), "output-exists")
    identity = stage_site(download(item), source, args.output / "site")
    receipt.update(identity)
    encoded = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    (args.output / "publication.json").write_bytes(encoded)
    (args.output / "site/publication.json").write_bytes(encoded)
    print(json.dumps({"source": source, "ciRun": run_id, "ciAttempt": attempt,
                      "artifactId": item["id"], "treeDigest": identity["treeDigest"]}))


def verify(args):
    expected = json.loads(args.receipt.read_bytes())
    observed = live_publication()
    require(observed == expected, "live-publication-identity")
    manifest = json.loads(fetch(SITE_URL + "site-manifest.json", 4 * 1024 * 1024))
    require(manifest["revision"] == expected["source"] and manifest["dirty"] is False, "live-manifest")
    # Browser interaction is a separate unprivileged job. These fetches also
    # detect incomplete publication before this trusted deployment receipt is kept.
    for route in ("", "guides/", "search/", "docs/architecture/overview/", "404.html"):
        body = fetch(SITE_URL + route, 4 * 1024 * 1024)
        require(b"<html" in body.lower(), "live-html")
    print(json.dumps({"source": expected["source"], "liveIdentity": True, "staticRoutes": 5}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    selection = sub.add_parser("select")
    for name in ("source", "run", "attempt"):
        selection.add_argument("--" + name, required=True)
    selection.add_argument("--mode", choices=("publish", "rollback"), required=True)
    selection.add_argument("--expected-live-source", default="")
    selection.add_argument("--previous-publication-run", default="")
    selection.add_argument("--output", type=Path, required=True)
    for name in ("guard", "verify"):
        child = sub.add_parser(name)
        child.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "select":
            select(args)
        elif args.command == "guard":
            receipt = json.loads(args.receipt.read_bytes())
            verify_staged_site(args.receipt.parent / "site", receipt)
            guard(receipt)
        else:
            verify(args)
        return 0
    except (ValueError, KeyError, OSError, urllib.error.URLError, zipfile.BadZipFile) as error:
        # No URLs with signed storage parameters, response bodies or tokens.
        code = str(error) if isinstance(error, ValueError) and str(error).replace("-", "").isalpha() else type(error).__name__
        print("Pages publication rejected: " + code, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

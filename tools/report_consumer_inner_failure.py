"""Report a small, authenticated summary of the retained #1664 failure."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "KirilsTurkins/latent-service-fabric"
BRANCH = "diag/sdk-745-consumer-failure-20261105"
ORIGINAL_HEAD = "296a1bd794c8566af600e869f520c549490cb03d"
RUN = 41970273145
JOB = 127056632180
ARTIFACT = 13390646225
ARTIFACT_SIZE = 846426
ARTIFACT_SHA256 = "c1abaedd611dbfb7cee9f355f5acf4e77ceb4c4be9400aeffa0359ba843225b2"
REPORTER_PATHS = (
    ".github/workflows/consumer-inner-future-failure-report.yml",
    "tools/ci/contracts/workflows/consumer-inner-future-failure-report.yml/jobs/inspect.json",
    "tools/ci/contracts/workflows/consumer-inner-future-failure-report.yml/workflow.json",
    "tools/report_consumer_inner_failure.py",
)
API = "https://api.github.com/repos/" + REPOSITORY + "/"
MAX_ARCHIVE_CONTENTS = 32 * 1024 * 1024
MAX_MEMBER = 16 * 1024 * 1024


def require(value):
    if not value:
        raise ValueError("bounded failure report refused")


def source_location(raw, line, column):
    if not isinstance(raw, str) or type(line) is not int or type(column) is not int:
        return None
    raw = raw.replace("\\", "/")
    found = re.search(r"(?:^|/)((?:crates|sdk|tools)/[A-Za-z0-9_./-]+\.rs)$", raw)
    if found is None:
        return None
    path = found.group(1)
    if ".." in path.split("/") or not 1 <= line <= 10000000 or not 1 <= column <= 100000:
        return None
    return path, line, column


def inspect_archive(archive):
    infos = archive.infolist()
    require(len(infos) <= 128 and len({i.filename for i in infos}) == len(infos))
    require(all(not (i.flag_bits & 1) and i.file_size <= MAX_MEMBER for i in infos))
    require(sum(i.file_size for i in infos) <= MAX_ARCHIVE_CONTENTS)
    require(archive.testzip() is None)

    def member(name, maximum):
        selected = [i for i in infos if i.filename == name or i.filename.endswith("/" + name)]
        require(len(selected) == 1 and selected[0].file_size <= maximum)
        return archive.read(selected[0])

    receipt = json.loads(member("FAILED.json", 8 * 1024 * 1024))
    require(isinstance(receipt, dict) and receipt.get("status") == "failed"
            and receipt.get("sourceRevision") == ORIGINAL_HEAD)
    stage = receipt.get("stage")
    require(stage is None or isinstance(stage, str)
            and re.fullmatch(r"[A-Za-z0-9_:.-]{1,300}", stage) is not None)
    rows = json.loads(member("commands.json", 1024 * 1024))
    require(isinstance(rows, list) and len(rows) <= 64)
    failed = []
    diagnostics = []
    for ordinal, row in enumerate(rows):
        require(isinstance(row, dict))
        name, exit_code = row.get("stage"), row.get("exitCode")
        require(isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,80}", name)
                and type(exit_code) is int and -255 <= exit_code <= 255)
        if exit_code == 0:
            continue
        failed.append((name, exit_code))
        for stream in ("stdout", "stderr"):
            suffix = f"commands/logs/{ordinal:02d}-{name}.{stream}.txt"
            selected = [i for i in infos if i.filename == suffix or i.filename.endswith("/" + suffix)]
            require(len(selected) <= 1)
            if not selected:
                continue
            require(selected[0].file_size <= 4 * 1024 * 1024)
            data = archive.read(selected[0]).decode("utf-8", "replace")
            for line in data.splitlines():
                if len(line) > 1024 * 1024:
                    continue
                try:
                    event = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if not isinstance(event, dict) or event.get("reason") != "compiler-message":
                    continue
                message = event.get("message")
                if not isinstance(message, dict) or message.get("level") != "error":
                    continue
                code_data = message.get("code")
                code = code_data.get("code") if isinstance(code_data, dict) else None
                if not isinstance(code, str) or re.fullmatch(r"E[0-9]{4}", code) is None:
                    code = "uncoded"
                spans = message.get("spans")
                if not isinstance(spans, list):
                    continue
                for span in spans[:64]:
                    if not isinstance(span, dict):
                        continue
                    location = source_location(span.get("file_name"),
                                               span.get("line_start"), span.get("column_start"))
                    if location is not None:
                        item = (code, *location)
                        if item not in diagnostics:
                            diagnostics.append(item)
                        if len(diagnostics) >= 16:
                            break
                if len(diagnostics) >= 16:
                    break
    return stage or "not-recorded", failed, diagnostics[:16]


def api_request(path):
    token = os.environ["GH_TOKEN"]
    require(bool(token))
    return urllib.request.Request(API + path, headers={
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "lsf-consumer-failure-report",
    })


def api_json(path):
    with urllib.request.urlopen(api_request(path), timeout=20) as response:
        require(response.status == 200)
        raw = response.read(2 * 1024 * 1024 + 1)
    require(len(raw) <= 2 * 1024 * 1024)
    value = json.loads(raw)
    require(isinstance(value, dict))
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    stage = "host-context"
    try:
        require(os.environ.get("GITHUB_ACTIONS") == "true"
                and os.environ.get("GITHUB_REPOSITORY") == REPOSITORY
                and os.environ.get("GITHUB_EVENT_NAME") == "push"
                and os.environ.get("GITHUB_REF_NAME") == BRANCH)
        head = os.environ.get("GITHUB_SHA", "")
        require(re.fullmatch(r"[0-9a-f]{40}", head) is not None)
        stage = "source-check"
        run = subprocess.run(["git", "rev-list", "--parents", "-n", "1", "HEAD"],
                             check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=10, text=True)
        require(run.stdout.strip().split() == [head, ORIGINAL_HEAD])
        run = subprocess.run(["git", "diff", "--no-ext-diff", "--name-only", ORIGINAL_HEAD, head, "--"],
                             check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             timeout=10, text=True)
        require(tuple(sorted(run.stdout.splitlines())) == REPORTER_PATHS)
        stage = "run-metadata"
        run = api_json(f"actions/runs/{RUN}")
        require(run.get("id") == RUN and run.get("head_sha") == ORIGINAL_HEAD
                and run.get("head_branch") == "feat/sdk-745-consumer-inner-future-20261105"
                and run.get("event") == "push" and run.get("status") == "completed"
                and run.get("conclusion") == "failure"
                and run.get("path") == ".github/workflows/consumer-inner-future.yml")
        stage = "job-metadata"
        job = api_json(f"actions/jobs/{JOB}")
        require(job.get("id") == JOB and job.get("run_id") == RUN
                and job.get("head_sha") == ORIGINAL_HEAD
                and job.get("status") == "completed" and job.get("conclusion") == "failure")
        stage = "artifact-metadata"
        artifact = api_json(f"actions/artifacts/{ARTIFACT}")
        origin = artifact.get("workflow_run")
        require(artifact.get("id") == ARTIFACT and artifact.get("expired") is False
                and artifact.get("size_in_bytes") == ARTIFACT_SIZE
                and artifact.get("digest") == "sha256:" + ARTIFACT_SHA256
                and artifact.get("name") == "consumer-inner-future-" + ORIGINAL_HEAD
                and isinstance(origin, dict) and origin.get("id") == RUN
                and origin.get("head_sha") == ORIGINAL_HEAD)
        stage = "download-redirect"
        try:
            urllib.request.build_opener(NoRedirect).open(api_request(f"actions/artifacts/{ARTIFACT}/zip"), timeout=20)
            raise ValueError("expected signed redirect")
        except urllib.error.HTTPError as response:
            require(response.code in (302, 303, 307, 308))
            location = response.headers.get("Location", "")
        parsed = urllib.parse.urlsplit(location)
        require(parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password)
        stage = "download-stream"
        target = Path(os.environ["RUNNER_TEMP"]) / "consumer-inner-original-13390646225.zip"
        digest = hashlib.sha256()
        total = 0
        with urllib.request.urlopen(location, timeout=45) as response, target.open("xb") as output:
            require(response.status == 200)
            while True:
                chunk = response.read(65536)
                if not chunk:
                    break
                total += len(chunk)
                require(total <= ARTIFACT_SIZE)
                digest.update(chunk)
                output.write(chunk)
        stage = "archive-identity"
        require(total == ARTIFACT_SIZE and digest.hexdigest() == ARTIFACT_SHA256)
        stage = "archive-and-receipt"
        with zipfile.ZipFile(target) as archive:
            original_stage, failed, diagnostics = inspect_archive(archive)
        stage = "emit-summary"
        print("::notice title=Original owner::run=41970273145 head=296a1bd794c8566af600e869f520c549490cb03d artifact=13390646225")
        print(f"::warning title=Original owner failure::stage={original_stage}")
        if not failed:
            print("::notice title=Original failed command::none-recorded")
        for name, exit_code in failed[:16]:
            print(f"::notice title=Original failed command::{name} exit={exit_code}")
        for code, path, line, column in diagnostics:
            print(f"::notice title=Bounded Rust error::{code} {path}:{line}:{column}")
        print(f"::notice title=Failure report::rust-diagnostics={len(diagnostics)}")
    except Exception as error:
        print(f"::error title=Original failure reporter::stage={stage} kind={type(error).__name__}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

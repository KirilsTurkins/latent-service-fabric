"""Retain one reviewable disposable candidate without creating authority.

Review supplies the exact candidate digest. Only the existing authenticated
native policy mutation can grant access. Pausing consumes the original lifetime.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import stat
import time

from tools.rust_capsule_project import read_file

from . import configuration as cfg
from .evidence import encoded
from .inputs import decode, digest, require

NAME = "authority-candidate.json"
CLAIM = "authority-candidate-used.json"
EXCLUDED = {NAME, "campaign-receipt.json"}
FIELDS = {"schemaVersion", "root", "rootIdentity", "clock", "sources", "nativeTools", "collectors",
          "originalInputs", "prepared", "recipient", "node", "cliCalls", "evidence", "files"}


def integer(value, maximum, minimum=0):
    require(type(value) is int and minimum <= value <= maximum, "original-candidate-integer-bound")
    return value


def boot_id():
    with Path("/proc/sys/kernel/random/boot_id").open("rb") as source:
        raw = source.read(65)
    require(0 < len(raw) <= 64, "original-linux-boot-observation")
    value = raw.decode().strip()
    require(re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", value),
            "original-linux-boot-observation")
    return value


def clock(timeout):
    integer(timeout, 1200, 1)
    started = time.monotonic_ns()
    return {"bootId": boot_id(), "startedMonotonicNanos": started, "startedUnixNanos": time.time_ns(),
            "deadlineMonotonicNanos": started + timeout * 1_000_000_000, "timeoutSeconds": timeout}


def deadline(original, timeout):
    require(isinstance(original, dict) and set(original) == {"bootId", "startedMonotonicNanos",
        "startedUnixNanos", "deadlineMonotonicNanos", "timeoutSeconds"}, "closed-original-candidate-clock")
    require(original["bootId"] == boot_id() and original["timeoutSeconds"] == timeout,
            "original-candidate-clock-owner")
    start = integer(original["startedMonotonicNanos"], 2**64 - 1, 1)
    wall = integer(original["startedUnixNanos"], 2**64 - 1, 1)
    end = integer(original["deadlineMonotonicNanos"], 2**64 - 1, 1)
    integer(original["timeoutSeconds"], 1200, 1)
    now = time.monotonic_ns()
    require(end - start == timeout * 1_000_000_000 and start <= now < end
            and abs((time.time_ns() - wall) - (now - start)) <= 1_000_000_000,
            "original-candidate-deadline-or-clock-drift")
    # This observer can refuse continuation; it certifies no native continuity.
    return end / 1_000_000_000


def root_identity(root):
    require(root.is_absolute() and root.is_dir() and not root.is_symlink(), "original-private-candidate-root")
    value = root.stat()
    require(os.name != "posix" or value.st_mode & 0o077 == 0, "private-candidate-root-mode")
    return {"device": value.st_dev, "inode": value.st_ino, "mode": stat.S_IMODE(value.st_mode)}


def files(root):
    """A bounded streaming identity census of the stopped original owners.

    These are observation limits, not native storage/profile configuration.
    No component or native image is copied into an observer buffer.
    """
    result, total, directories = {}, 0, 0
    pending = [root]
    while pending:
        current = pending.pop()
        directories += 1
        require(directories <= 4096, "candidate-directory-observation-bound")
        for path in sorted(current.iterdir()):
            require(len(result) < 4096, "candidate-entry-observation-bound")
            relative = path.relative_to(root).as_posix()
            require(len(relative.encode()) <= 512 and not any(ord(c) < 32 or ord(c) == 127 for c in relative),
                    "candidate-observed-path-bound")
            before = path.lstat()
            require(not stat.S_ISLNK(before.st_mode), "candidate-links-refused")
            if stat.S_ISDIR(before.st_mode):
                require(len(path.relative_to(root).parts) <= 16, "candidate-directory-depth-bound")
                result[relative] = {"kind": "directory", "mode": stat.S_IMODE(before.st_mode)}
                pending.append(path)
                continue
            require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1,
                    "candidate-single-link-regular-file-required")
            if relative in EXCLUDED:
                continue
            require(before.st_size <= 268435456
                    and total + before.st_size <= 1073741824, "candidate-file-observation-bound")
            value = hashlib.sha256()
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd, "rb") as source:
                consumed = 0
                while raw := source.read(1048576):
                    consumed += len(raw)
                    require(consumed <= before.st_size, "candidate-file-changed-during-observation")
                    value.update(raw)
                after = os.fstat(source.fileno())
            require(consumed == before.st_size and
                (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_nlink)
                == (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_nlink),
                "candidate-file-changed-during-observation")
            result[relative] = {"kind": "file", "bytes": consumed, "digest": "sha256:" + value.hexdigest(),
                                "mode": stat.S_IMODE(after.st_mode)}
            total += consumed
    return dict(sorted(result.items()))


def path(root, relative):
    require(isinstance(relative, str) and 0 < len(relative.encode()) <= 512 and "\\" not in relative
            and not any(ord(c) < 32 or ord(c) == 127 for c in relative)
            and not Path(relative).is_absolute() and all(part not in {"", ".", ".."} for part in relative.split("/")),
            "original-relative-candidate-path")
    return root / relative


def write_once(file, value):
    raw = encoded(value)
    require(len(raw) <= 1048576, "candidate-document-byte-bound")
    with file.open("xb") as target:
        target.write(raw)
        target.flush()
        os.fsync(target.fileno())
    file.chmod(0o600)
    return {"path": str(file), "digest": digest(raw), "bytes": len(raw)}


def catalog(client, publications):
    from .inputs import VARIANTS
    from .diagnostic_inputs import NAME
    expected = set(VARIANTS) - {"forbidden-http"}
    if NAME in publications:
        expected.add(NAME)
    require(isinstance(publications, dict) and set(publications) == expected
            and all(isinstance(value, str) and re.fullmatch(r"publication:sha256:[0-9a-f]{64}", value)
                    for value in publications.values()) and len(set(publications.values())) == len(expected),
            "original-four-publication-catalog-scope")
    result = {"publications": {}, "policies": {}}
    for name, publication in publications.items():
        original = client.call("release", "operation", "java-publish-" + name)["data"]["receipt"]
        require(original["publication"]["id"] == publication, "original-publication-operation-receipt")
        result["publications"][name] = original
    for kind in ("provider-binding", "policy"):
        observed = client.call("policy", "--kind", kind, "list", "--page-size", str(cfg.POLICY_PAGE_RECORDS))["data"]
        require(set(observed) == {"policies", "catalogGeneration", "nextPageToken"}
                and observed["policies"] == [] and observed["nextPageToken"] is None
                and isinstance(observed["catalogGeneration"], str)
                and re.fullmatch(r"[1-9][0-9]{0,19}", observed["catalogGeneration"])
                and int(observed["catalogGeneration"]) <= 2**64 - 1,
                "original-empty-policy-catalog-required")
        result["policies"][kind] = observed
    return result


def sources(args):
    from .diagnostic_inputs import selection
    result = {"native": args.native_source_commit, "conductor": args.conductor_source_commit,
              "portable": str(args.portable)}
    selected = selection(args)
    if selected is not None:
        result["diagnostic"] = selected
    return result


def capture(root, original_clock, args, record, prepared, client, node, peer):
    require(client.node is None and node.process is None and type(node.ordinal) is int
            and node.ordinal == 1 and len(node.shutdown) == 1
            and peer.shutdown is not None, "original-candidate-positive-teardown-required")
    from .lifecycle import require_retirement
    require(node.shutdown[0]["reaped"] is True and peer.shutdown["reaped"] is True,
            "original-candidate-process-retirement-required")
    require_retirement(node.shutdown[0]["record"]["report"])
    from .provider import stopped_observation
    observed = stopped_observation(peer.shutdown["record"], peer.incarnation)
    require(all(observed[name] == 0 for name in ("requests", "puts", "gets", "acceptedRecords", "appliedRecords",
                "retainedRecords", "duplicatePuts", "disconnectedAfterAcceptance")),
            "authority-staging-cannot-have-application-provider-requests")
    value = {"schemaVersion": "latent.java-transaction.authority-candidate.v1", "root": str(root),
        "rootIdentity": root_identity(root), "clock": original_clock,
        "sources": sources(args),
        "nativeTools": record["nativeTools"], "collectors": record["collectorDigests"],
        "originalInputs": record["originalInputs"], "prepared": prepared,
        "recipient": {"directory": peer.directory.relative_to(root).as_posix(),
            "tls": "tls", "credential": "recipient-token", "incarnation": peer.incarnation,
            "port": peer.port, "session": 1, "shutdown": peer.shutdown},
        "node": {"directory": node.directory.relative_to(root).as_posix(),
                 "ordinal": node.ordinal, "shutdown": node.shutdown},
        "cliCalls": client.calls, "evidence": client.evidence.summary(), "files": files(root)}
    if "diagnostic" in value["sources"]:
        require(isinstance(record.get("diagnosticInput"), dict), "original-diagnostic-candidate-input-required")
        value["diagnosticInput"] = record["diagnosticInput"]
    return write_once(root / NAME, value)


def retain(args, tools, collectors):
    file = args.resume_candidate
    require(file.is_absolute() and file.name == NAME and file.parent == args.output
            and not (args.output / CLAIM).exists(), "unused-original-candidate-required")
    raw = read_file(file, 1048576)
    require(re.fullmatch(r"sha256:[0-9a-f]{64}", args.candidate_digest or "")
            and digest(raw) == args.candidate_digest, "exact-reviewed-candidate-digest-required")
    value = decode(raw, 1048576)
    selected_sources = sources(args)
    expected_fields = FIELDS | ({"diagnosticInput"} if "diagnostic" in selected_sources else set())
    require(isinstance(value, dict) and set(value) == expected_fields
            and value["schemaVersion"] == "latent.java-transaction.authority-candidate.v1"
            and value["root"] == str(args.output)
            and value["rootIdentity"] == root_identity(args.output), "original-candidate-root-identity")
    require(value["sources"] == selected_sources and value["nativeTools"] == tools and value["collectors"] == collectors,
            "original-candidate-source-or-tool-drift")
    until = deadline(value["clock"], args.timeout)
    integer(value["cliCalls"], 255)
    require(value["files"] == files(args.output), "original-candidate-retained-file-drift")
    node, peer = value["node"], value["recipient"]
    require(isinstance(node, dict) and set(node) == {"directory", "ordinal", "shutdown"}
            and type(node["ordinal"]) is int and node["ordinal"] == 1
            and isinstance(node["shutdown"], list) and len(node["shutdown"]) == 1,
            "original-counted-node-session-required")
    require(isinstance(peer, dict) and set(peer) == {"directory", "tls", "credential", "incarnation", "port", "session", "shutdown"}
            and type(peer["session"]) is int and peer["session"] == 1
            and isinstance(peer["incarnation"], str) and re.fullmatch(r"[0-9a-f]{64}", peer["incarnation"]),
            "original-counted-recipient-session-required")
    integer(peer["port"], 65535, 1)
    from .lifecycle import require_retirement
    require(node["shutdown"][0]["reaped"] is True and peer["shutdown"]["reaped"] is True,
            "original-candidate-process-retirement-required")
    require_retirement(node["shutdown"][0]["record"]["report"])
    from .provider import COUNTERS, stopped_observation
    observed = stopped_observation(peer["shutdown"]["record"], peer["incarnation"])
    require(all(observed[name] == 0 for name in COUNTERS), "authority-staging-cannot-have-application-provider-requests")
    for field in ("directory", "tls", "credential"):
        path(args.output, peer[field])
    path(args.output, node["directory"])
    prepared = value["prepared"]
    require(isinstance(prepared, dict) and set(prepared) == {"bootstrap", "full", "signed", "authority", "origin", "publications", "mutations",
                             "proposals", "catalog", "hosts"}, "closed-original-prepared-candidate")
    for field in ("bootstrap", "full", "signed"):
        path(args.output, prepared[field])
    return value, until


def configuration(root, prepared):
    from tools.phase2_operator_process import read_json
    return cfg.Configuration(path(root, prepared["bootstrap"]),
        read_json(path(root, prepared["bootstrap"])), prepared["authority"], prepared["origin"])


def claim(root, candidate_digest):
    # Consuming the candidate is separate from the native command ledger. It
    # prevents this disposable conductor from retrying an uncertain mutation.
    require(isinstance(candidate_digest, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", candidate_digest),
            "exact-reviewed-candidate-digest-required")
    return write_once(root / CLAIM, {"schemaVersion": "latent.java-transaction.candidate-use.v1",
        "candidateDigest": candidate_digest, "startedMonotonicNanos": time.monotonic_ns()})


def mode(args):
    require(type(args.prepare_authority_only) is bool
            and (args.resume_candidate is None) == (args.candidate_digest is None)
            and not (args.prepare_authority_only and args.resume_candidate is not None),
            "exclusive-paired-candidate-mode")
    return "resume" if args.resume_candidate is not None else "prepare" if args.prepare_authority_only else "run"

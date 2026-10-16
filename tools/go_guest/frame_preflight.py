#!/usr/bin/env python3
"""Authenticated, unprivileged entry for the failure-only Go frame observer."""
import hashlib
import json
import os
import pathlib
import stat
import sys
import tempfile


def main():
    phase = "arguments"
    code = "exception"

    def require(value, reason):
        nonlocal code
        if not value:
            code = reason
            raise SystemExit("Go-private-frame-host-preflight-refused")

    try:
        expected = json.loads(sys.argv[1])
        cargo = sys.argv[2:]
        phase = "credentials"
        require(os.getuid() == os.geteuid() == expected["uid"] != 0, "uid")
        require(os.getgid() == os.getegid() == expected["gid"], "gid")
        require(set(os.getgroups()) <= set(expected["groups"]), "groups")
        phase = "capsets"
        status = pathlib.Path("/proc/self/status").read_text()
        for key in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
            fields = [line.split(":", 1)[1].strip() for line in status.splitlines() if line.startswith(key + ":")]
            require(len(fields) == 1 and int(fields[0], 16) == 0, key)
        require("NoNewPrivs:\t1" in status, "no-new-privs")
        phase = "uid-map"
        require(hashlib.sha256(pathlib.Path("/proc/self/uid_map").read_bytes()).hexdigest() == expected["uidMapDigest"], "uid-map")
        phase = "root-stat"
        root = pathlib.Path("/").stat()
        require([root.st_uid, root.st_gid, stat.S_IMODE(root.st_mode)] == expected["root"], "root-stat")
        phase = "temp-ancestors"
        temporary = pathlib.Path(tempfile.gettempdir()).resolve(strict=True)
        for path in (*reversed(temporary.parents), temporary):
            value = path.stat()
            require(stat.S_ISDIR(value.st_mode), "temporary-directory")
            require(value.st_uid in (0, expected["uid"]), "temporary-owner")
            require(not value.st_mode & 0o022 or value.st_uid == 0 and bool(value.st_mode & stat.S_ISVTX), "temporary-mode")
        require(all(key not in os.environ for key in ("TEMP", "TMP", "TMPDIR")), "temporary-environment")
        print("LSF_GO_DIAG_HOST " + json.dumps({"uid": os.getuid(), "gid": os.getgid(), "sameUserNamespace": True,
            "capabilitiesDropped": True, "rootOwnershipPreserved": True, "temporaryAncestorsAccepted": True}), flush=True)
        phase = "native-start"
        os.execve(cargo[0], cargo, dict(os.environ))
    except BaseException as error:
        kind = type(error).__name__
        if kind not in ("SystemExit", "ValueError", "JSONDecodeError", "KeyError", "IndexError", "TypeError", "PermissionError",
                        "FileNotFoundError", "NotADirectoryError", "OSError", "RuntimeError"):
            kind = "Other"
        print("LSF_GO_DIAG_HOST_FAILURE " + json.dumps({"phase": phase, "code": code, "exception": kind}), file=sys.stderr, flush=True)
        raise SystemExit("Go-private-frame-host-preflight-refused") from None


if __name__ == "__main__":
    main()

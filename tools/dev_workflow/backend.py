"""Explicit transport adapters; requests never become a remote shell program."""
from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import sys

from . import paths, process, protocol
from .common import DevError, MAX_SNAPSHOT, decode, digest, encode, members, require, sha

HELPER = "/opt/latent-dev/helper.pyz"
GUEST_PYTHON = "/usr/local/bin/python3.13"
EXEC_HELPER = """import hashlib,os,pathlib,stat,sys
p,expected=sys.argv[1:3]
try:
    parts=pathlib.PurePosixPath(p).parts
    assert parts[0]=='/' and '..' not in parts
    d=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
    for part in parts[1:-1]:
        n=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=d)
        os.close(d); d=n; s=os.fstat(d)
        assert s.st_uid in (0,os.geteuid()) and (s.st_mode&18==0 or s.st_uid==0 and s.st_mode&stat.S_ISVTX)
    f=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW,dir_fd=d); os.close(d); s=os.fstat(f)
    assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=16777216
    assert s.st_uid in (0,os.geteuid()) and s.st_mode&18==0
    with os.fdopen(os.dup(f),'rb') as stream:
        assert 'sha256:'+hashlib.file_digest(stream,'sha256').hexdigest()==expected
    z='/proc/self/fd/'+str(f)
except (AssertionError,OSError,ValueError):
    sys.exit(126)
sys.path.insert(0,z); sys.argv=[p,*sys.argv[3:]]
from tools.dev_workflow.helper import main
raise SystemExit(main())
"""


def guest_command(python: str, helper: str, expected: str, mode: str) -> list[str]:
    require(mode in {"rpc", "create-user", "user-status", "remove-user"}, "helper-mode")
    return [python, "-I", "-c", EXEC_HELPER, helper, sha(expected), mode]


def validate(value: dict) -> dict:
    members(value, {"kind", "helperSha256"}, {"distribution", "user", "python", "helper", "host", "port",
                                           "identityFile", "knownHosts", "ssh"})
    sha(value["helperSha256"])
    kind = value["kind"]
    require(kind in {"linux", "wsl2", "ssh"}, "unsupported-backend-macos-deferred")
    if kind == "wsl2":
        require(set(value) == {"kind", "helperSha256", "distribution", "user"}, "wsl-backend-fields")
        require(re.fullmatch(r"LSF-Dev-[a-f0-9]{16}", value["distribution"])
                and re.fullmatch(r"lsfd-[a-f0-9]{12}", value["user"]), "unowned-wsl-target")
    elif kind == "linux":
        require(set(value) == {"kind", "helperSha256", "python", "helper"}, "linux-backend-fields")
        for key in ("python", "helper"):
            paths.absolute(Path(value[key]))
    else:
        require(set(value) == {"kind", "helperSha256", "host", "port", "user", "identityFile", "knownHosts", "ssh"},
                "ssh-backend-fields")
        require(isinstance(value["host"], str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,200}", value["host"]),
                "ssh-host-must-be-explicit")
        require(isinstance(value["user"], str) and re.fullmatch(r"[a-z_][a-z0-9_-]{0,30}", value["user"]), "ssh-user")
        require(type(value["port"]) is int and 1 <= value["port"] <= 65535, "ssh-port")
        for key in ("ssh", "identityFile", "knownHosts"):
            paths.absolute(Path(value[key]))
    return value


def wsl_executable() -> str:
    require(os.name == "nt", "wsl-requires-windows")
    path = Path(os.environ["SystemRoot"]) / "System32/wsl.exe"
    require(path.is_file(), "wsl-not-installed-follow-windows-prerequisites")
    return str(path)


def command(config: dict) -> list[str]:
    validate(config)
    # SSH transmits only this constant remote command. Untrusted data stays on stdin.
    guest = guest_command(GUEST_PYTHON, HELPER, config["helperSha256"], "rpc")
    if config["kind"] == "wsl2":
        return [wsl_executable(), "--distribution", config["distribution"], "--user", config["user"], "--exec", *guest]
    if config["kind"] == "linux":
        require(sys.platform == "linux", "direct-backend-requires-linux")
        return guest_command(config["python"], config["helper"], config["helperSha256"], "rpc")
    return [config["ssh"], "-F", "NUL" if os.name == "nt" else "/dev/null", "-T", "-a",
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "-o", "IdentitiesOnly=yes",
            "-o", "ForwardAgent=no", "-o", "ClearAllForwardings=yes", "-o", "PermitLocalCommand=no",
            "-o", "ProxyCommand=none", "-o", "ConnectTimeout=10", "-o", "ConnectionAttempts=1",
            "-o", "ServerAliveInterval=5", "-o", "ServerAliveCountMax=2", "-o", "ControlMaster=no",
            "-o", "ControlPath=none", "-o", "UserKnownHostsFile=" + config["knownHosts"],
            "-o", "GlobalKnownHostsFile=" + ("NUL" if os.name == "nt" else "/dev/null"),
            "-i", config["identityFile"], "-p", str(config["port"]),
            config["user"] + "@" + config["host"], " ".join(shlex.quote(part) for part in guest)]


class Backend:
    def __init__(self, config: dict, workspace: str, cwd: Path):
        self.config, self.workspace, self.cwd = validate(config), workspace, cwd
        self.negotiated = False

    def call(self, operation: str, arguments: dict, *, timeout: int = 60) -> dict:
        if self.config["kind"] == "wsl2":
            from .wsl import verify_workspace
            verify_workspace(self.cwd.parent, self.workspace, self.config)
        if operation != "hello" and not self.negotiated:
            protocol.negotiate(self.call("hello", {}))
            self.negotiated = True
        request = protocol.request(operation, self.workspace, arguments)
        try:
            completed = process.run(command(self.config), self.cwd, timeout=timeout,
                                    stdin=encode(request), maximum=4 * 1024 * 1024)
            require(completed.returncode != 126, "helper-identity-mismatch-before-execution")
            require(completed.returncode == 0, "backend-helper-exit")
            return protocol.result(decode(completed.stdout, 4 * 1024 * 1024), request)
        except (DevError, OSError) as error:
            if isinstance(error, DevError) and error.code not in {"backend-helper-exit", "owned-process-failed",
                    "owned-process-command-deadline", "owned-process-command-output-limit"}:
                raise
            raise DevError("backend-transport-lost-status-required", uncertain=operation not in
                           {"hello", "doctor", "status", "logs", "recover"}) from None

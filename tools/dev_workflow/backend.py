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
VERIFY_HELPER = ("import hashlib,os,stat,sys; p=sys.argv[1]; "
                 "f=os.open(p,os.O_RDONLY|os.O_NOFOLLOW); s=os.fstat(f); "
                 "assert stat.S_ISREG(s.st_mode) and s.st_nlink==1 and s.st_size<=16777216; "
                 "assert s.st_uid in (0,os.geteuid()) and s.st_mode & 18 == 0; "
                 "b=os.read(f,16777217); os.close(f); "
                 "assert len(b)==s.st_size; print('sha256:'+hashlib.sha256(b).hexdigest())")


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


def command(config: dict, *, verify: bool = False) -> list[str]:
    validate(config)
    # SSH transmits only this constant remote command. Untrusted data stays on stdin.
    guest = (["/usr/bin/python3", "-I", "-c", VERIFY_HELPER, HELPER] if verify
             else ["/usr/bin/python3", "-I", HELPER, "rpc"])
    if config["kind"] == "wsl2":
        return [wsl_executable(), "--distribution", config["distribution"], "--user", config["user"], "--exec", *guest]
    if config["kind"] == "linux":
        require(sys.platform == "linux", "direct-backend-requires-linux")
        return ([config["python"], "-I", "-c", VERIFY_HELPER, config["helper"]] if verify
                else [config["python"], "-I", config["helper"], "rpc"])
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
        if operation != "hello" and not self.negotiated:
            protocol.negotiate(self.call("hello", {}))
            self.negotiated = True
        checked = process.run(command(self.config, verify=True), self.cwd, timeout=20, maximum=4096)
        require(checked.returncode == 0 and checked.stdout.strip().decode("ascii") == self.config["helperSha256"],
                "helper-identity-mismatch-before-execution")
        request = protocol.request(operation, self.workspace, arguments)
        try:
            completed = process.run(command(self.config), self.cwd, timeout=timeout,
                                    stdin=encode(request), maximum=4 * 1024 * 1024)
            require(completed.returncode == 0, "backend-helper-exit")
            return protocol.result(decode(completed.stdout, 4 * 1024 * 1024), request)
        except (DevError, OSError) as error:
            if isinstance(error, DevError) and error.code not in {"backend-helper-exit", "owned-process-failed"}:
                raise
            raise DevError("backend-transport-lost-status-required", uncertain=operation not in
                           {"hello", "doctor", "status", "logs", "recover"}) from None

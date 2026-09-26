"""One server instance or one private foreground evaluation directory."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from .common import execute, require
from . import files


@dataclass(frozen=True)
class Layout:
    prefix: Path
    config: Path
    data: Path
    cache: Path
    system: bool

    @classmethod
    def server(cls):
        return cls(Path("/opt/lsf"), Path("/etc/lsf"), Path("/var/lib/lsf"), Path("/var/cache/lsf"), True)

    @classmethod
    def local(cls, root: Path):
        files.absolute(root)
        require(len(root.parts) >= 4 and root.name not in {"bin", "etc", "lib", "cache", "data"},
                "dedicated-local-directory-required")
        return cls(root, root / "config", root / "data", root / "cache", False)

    @property
    def state(self) -> Path:
        return self.prefix / "installed.json"

    @property
    def transaction(self) -> Path:
        return self.prefix / "transaction.json"

    @property
    def node(self) -> Path:
        return self.config / "node.json"

    @property
    def client(self) -> Path:
        return self.config / "client" / "client.json"

    @property
    def current(self) -> Path:
        return self.prefix / "current"

    def roots(self) -> dict[str, Path]:
        return {"config": self.config, "data": self.data, "cache": self.cache}


def account(create: bool) -> tuple[int, int]:
    import grp
    import pwd
    try:
        user = pwd.getpwnam("lsf")
    except KeyError:
        require(create, "service-account-missing")
        try:
            grp.getgrnam("lsf")
        except KeyError:
            pass
        else:
            require(False, "preexisting-service-group")
        status, _output = execute(["/usr/sbin/useradd", "--system", "--user-group", "--no-create-home",
                                   "--home-dir", "/var/lib/lsf", "--shell", "/usr/sbin/nologin", "lsf"])
        require(status == 0, "service-account-creation-failed")
        user = pwd.getpwnam("lsf")
    group = grp.getgrnam("lsf")
    require(0 < user.pw_uid < 1000 and 0 < group.gr_gid < 1000 and user.pw_gid == group.gr_gid
            and user.pw_dir == "/var/lib/lsf" and user.pw_shell in {"/usr/sbin/nologin", "/bin/false"},
            "unsafe-existing-service-account")
    require(set(group.gr_mem) <= {"lsf"}
            and all(member.pw_name == "lsf" or member.pw_gid != group.gr_gid for member in pwd.getpwall())
            and all(member.gr_gid == group.gr_gid or "lsf" not in member.gr_mem for member in grp.getgrall()),
            "service-account-must-be-exclusive")
    return user.pw_uid, user.pw_gid


def node_identity(layout: Layout, create: bool = False) -> tuple[int, int]:
    require(layout.system == (os.geteuid() == 0), "server-requires-root-local-requires-unprivileged-user")
    return account(create) if layout.system else (os.geteuid(), os.getegid())


def service_identity(layout: Layout) -> tuple[int, int]:
    identity = account(False) if layout.system else (os.geteuid(), os.getegid())
    require(identity[0] == os.geteuid() and identity[1] == os.getegid() and identity[0] != 0,
            "check-must-run-as-node-identity")
    return identity

"""Serialized, journaled installation and explicit retention/purge boundaries."""

from __future__ import annotations

from contextlib import ExitStack
import hashlib
import os
from pathlib import Path
import re
import secrets
import stat
import time

from . import archive, files
from .checks import current
from .common import document, encode, execute, require
from .configuration import LOCAL, approve_compiler, provision
from .layout import Layout, node_identity
from .verify import VerifiedRelease, manifest, publisher_id, publisher_policy, version

UNIT = Path("/etc/systemd/system/lsf.service")
MAX_STATE = 4_194_304


def systemctl(*arguments: str, timeout: float = 100) -> tuple[int, bytes]:
    return execute(["/usr/bin/systemctl", "--no-ask-password", "--no-pager", *arguments],
                   timeout=timeout, maximum=32768)


def stop_service() -> None:
    status, _output = systemctl("stop", "lsf.service")
    require(status == 0, "service-stop-failed")
    status, output = systemctl("show", "lsf.service", "--property=MainPID", "--value")
    require(status == 0 and output.strip() == b"0", "node-process-not-stopped")
    status, output = systemctl("show", "lsf.service", "--property=ControlGroup", "--value")
    require(status == 0, "service-cgroup-observation-failed")
    group = output.decode().strip()
    if group:
        require(group.startswith("/system.slice/lsf.service") and ".." not in group, "unexpected-service-cgroup")
        processes = Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs"
        if processes.exists():
            require(not files.read(processes, 32768).strip(), "compiler-children-not-reaped")


def read_state(layout: Layout) -> dict | None:
    if not layout.state.exists():
        return None
    value = document(files.read(layout.state, MAX_STATE, owners={0, os.geteuid()}), MAX_STATE)
    require(set(value) == {"schemaVersion", "installationId", "system", "profile", "status", "currentVersion",
                           "releases", "roots", "unitSha256"}, "installed-state-members")
    require(value["schemaVersion"] == "latent.native-installation.v1" and value["system"] == layout.system
            and re.fullmatch(r"[0-9a-f]{32}", value["installationId"])
            and value["status"] in {"installed", "removing-stopped", "removed", "purged"}, "installed-state-identity")
    version(value["currentVersion"])
    require(isinstance(value["releases"], dict) and 1 <= len(value["releases"]) <= 4
            and value["currentVersion"] in value["releases"], "installed-release-history")
    for selected, release in value["releases"].items():
        require(set(release) == {"publisher", "metadata", "authentication"}
                and re.fullmatch(r"[0-9a-f]{64}", release["publisher"]),
                "installed-publisher-identity")
        manifest(release["metadata"], selected)
        policy = publisher_policy(release["authentication"]["policy"], selected, allow_candidate=True)
        require(policy["sourceCommit"] == release["metadata"]["sourceCommit"]
                and publisher_id(policy) == release["publisher"], "installed-attestation-identity")
    require(set(value["roots"]) == set(layout.roots()), "installed-root-inventory")
    return value


def validate_roots(layout: Layout, state: dict, identity: tuple[int, int]) -> None:
    for name, path in layout.roots().items():
        require(files.identity(path, {0, os.geteuid(), identity[0]}) == state["roots"][name],
                "installation-root-substitution")


def compatible(state: dict, selected: VerifiedRelease, upgrade: bool, profile: str) -> None:
    require(state["profile"] == profile, "existing-security-profile-is-not-overwritten")
    previous = state["releases"][state["currentVersion"]]
    require(previous["publisher"] == selected.publisher, "publisher-workflow-change-needs-separate-reviewed-policy")
    old, new = previous["metadata"], selected.metadata
    if old["version"] == new["version"]:
        require(old == new, "same-version-different-content")
        return
    require(upgrade, "different-version-requires-explicit-upgrade")
    expected = {"version": old["version"], "sourceCommit": old["sourceCommit"], "archiveSha256": old["archive"]["sha256"]}
    require(expected in new["compatibility"]["upgradeFrom"]
            and all(new["engine"][name] == old["engine"][name]
                    for name in ("wasmtimeVersion", "hostAbiProfile", "dynamicDependencies")),
            "unsupported-upgrade-or-downgrade-no-files-changed")
    require(len(state["releases"]) < 4 or new["version"] in state["releases"], "retained-release-limit")


def prefix_inventory(layout: Layout) -> None:
    allowed = {"install.lock", "run.lock", "installed.json", "transaction.json", "purge.json", "releases", "current", "staging"}
    if not layout.system:
        allowed.update(path.name for path in layout.roots().values())
    with files.directory(layout.prefix, {0, os.geteuid()}) as descriptor:
        require(set(os.listdir(descriptor)) <= allowed, "untracked-files-in-installation-prefix")


def select_current(layout: Layout, selected: str, permitted: set[str]) -> None:
    with files.directory(layout.prefix, {0, os.geteuid()}) as parent:
        try:
            metadata = os.stat("current", dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            require(stat.S_ISLNK(metadata.st_mode) and os.readlink("current", dir_fd=parent) in permitted,
                    "current-release-link-substitution")
        name = ".current-" + secrets.token_hex(16)
        os.symlink("releases/" + selected, name, dir_fd=parent)
        os.replace(name, "current", src_dir_fd=parent, dst_dir_fd=parent)
        os.fsync(parent)


def child_check(layout: Layout, identity: tuple[int, int], command: str, candidate: str | None = None) -> dict:
    root = layout.prefix / "releases" / version(candidate) if candidate is not None else current(layout)
    location = ["--system"] if layout.system else ["--directory", str(layout.prefix)]
    if candidate is not None:
        location += ["--candidate-version", candidate]
    status, output = execute(["/usr/bin/python3", "-I", str(root / "lsf-install.pyz"), command, *location],
                             identity=identity, timeout=75, maximum=262144, cwd=str(layout.data))
    require(status == 0, "service-identity-" + command + "-failed-installation-unactivated")
    return document(output, 262144)


def install(layout: Layout, release: VerifiedRelease, *, profile: str, policy: Path | None = None,
            port: int = 50051, start: bool = False, enable: bool = False, upgrade: bool = False,
            resume: bool = False, acknowledge: bool = False, approved_compiler: str | None = None) -> dict:
    require(profile != LOCAL or acknowledge, "local-experimental-profile-needs-explicit-acknowledgement")
    require(layout.system or not (start or enable), "rootless-never-starts-or-enables-systemd")
    require(layout.system == (os.geteuid() == 0), "server-requires-root-local-requires-unprivileged-user")
    require(approved_compiler is None or (upgrade and approved_compiler == release.metadata["engine"]["compilerSha256"]),
            "compiler-approval-must-match-exact-upgrade-release")
    controller = (os.geteuid(), os.getegid())
    files.mkdir(layout.prefix, 0o755 if layout.system else 0o700, controller, owners={0, controller[0]})
    with ExitStack() as stack:
        stack.enter_context(files.lock(layout.prefix / "install.lock"))
        if not layout.system:
            stack.enter_context(files.lock(layout.prefix / "run.lock", timeout=0))
        prefix_inventory(layout)
        require(not os.path.lexists(layout.prefix / "purge.json"), "finish-interrupted-purge-before-installation")
        state = read_state(layout)
        if state is not None and state["status"] == "purged":
            require(all(not os.path.lexists(path) for path in layout.roots().values()), "purged-installation-has-untracked-roots")
            state = None
        if state:
            require(state["status"] != "removing-stopped", "finish-interrupted-removal-before-installation")
            compatible(state, release, upgrade, profile)
        pending = None
        if layout.transaction.exists():
            pending = document(files.read(layout.transaction, MAX_STATE, owners={0, controller[0]}), MAX_STATE)
            require(resume, "interrupted-installation-repeat-exact-command-with-resume")
            require(pending.get("schemaVersion") == "latent.native-transaction.v1"
                    and pending.get("target") == release.metadata and pending.get("publisher") == release.publisher
                    and pending.get("profile") == profile and pending.get("approvedCompiler") == approved_compiler,
                    "resume-requires-exact-original-release-and-profile")
        else:
            require(not resume, "no-interrupted-installation")
            if state is None:
                require(all(not os.path.lexists(path) for path in layout.roots().values()),
                        "refuse-adopting-untracked-configuration-or-storage")
                require(not layout.system or not os.path.lexists(UNIT), "untracked-systemd-unit")
            pending = {"schemaVersion": "latent.native-transaction.v1", "target": release.metadata,
                       "publisher": release.publisher, "profile": profile,
                       "approvedCompiler": approved_compiler,
                       "installationId": state["installationId"] if state else secrets.token_hex(16),
                       "initial": state is None}
            files.create(layout.transaction, encode(pending))
        identity = node_identity(layout, create=True)
        if state:
            validate_roots(layout, state, identity)
        releases = layout.prefix / "releases"
        files.mkdir(releases, 0o755 if layout.system else 0o700, controller, owners={0, controller[0]})
        selected = release.metadata["version"]
        destination = releases / selected
        if os.path.lexists(destination):
            archive.check_tree(destination, release.metadata["files"])
        else:
            staging = layout.prefix / "staging"
            if os.path.lexists(staging):
                require(resume, "untracked-staging-directory")
                files.remove_tree(staging, maximum=8192)
            files.mkdir(staging, 0o700, controller, owners={0, controller[0]})
            archive.extract(release.archive_fd, staging, release.metadata["files"])
            archive.check_tree(staging, release.metadata["files"])
            with files.directory(staging, {0, controller[0]}) as descriptor:
                os.fchmod(descriptor, 0o755 if layout.system else 0o700)
                os.fsync(descriptor)
            with files.directory(layout.prefix, {0, controller[0]}) as parent, files.directory(releases, {0, controller[0]}) as target:
                os.rename("staging", selected, src_dir_fd=parent, dst_dir_fd=target)
                os.fsync(target)
                os.fsync(parent)
        node = provision(layout, identity, profile, release.metadata, policy, port, pending["initial"], approved_compiler)
        permitted = {"releases/" + selected}
        if state:
            permitted.add("releases/" + state["currentVersion"])
        if not state or state["status"] == "removed":
            select_current(layout, selected, permitted)
        preflight = child_check(layout, identity, "preflight", candidate=selected)
        if layout.system and state and state["status"] == "installed" and state["currentVersion"] != selected:
            status, _output = systemctl("is-active", "--quiet", "lsf.service")
            require(status != 0 or start, "running-service-upgrade-requires-explicit-start")
            stop_service()
            if profile != LOCAL:
                time.sleep(6)
        approve_compiler(layout, identity, node, release.metadata, approved_compiler)
        select_current(layout, selected, permitted)
        unit = files.read(destination / "systemd" / "lsf.service", 16384)
        unit_sha256 = hashlib.sha256(unit).hexdigest()
        if layout.system:
            if os.path.lexists(UNIT):
                expected_unit = state["unitSha256"] if state else unit_sha256
                require((state is not None or resume) and files.digest(UNIT) in {expected_unit, unit_sha256},
                        "operator-modified-systemd-unit-not-overwritten")
                if files.digest(UNIT) != unit_sha256:
                    files.replace(UNIT, unit, 0o644)
            else:
                files.create(UNIT, unit, 0o644)
            status, _output = systemctl("daemon-reload")
            require(status == 0, "systemd-daemon-reload-failed")
        installed = {
            "schemaVersion": "latent.native-installation.v1", "installationId": pending["installationId"],
            "system": layout.system, "profile": profile, "status": "installed", "currentVersion": selected,
            "releases": dict(state["releases"]) if state else {},
            "roots": {name: files.identity(path, {0, controller[0], identity[0]}) for name, path in layout.roots().items()},
            "unitSha256": unit_sha256,
        }
        installed["releases"][selected] = {"publisher": release.publisher, "metadata": release.metadata,
                                            "authentication": release.authentication}
        files.replace(layout.state, encode(installed), 0o644)
        with files.directory(layout.prefix, {0, controller[0]}) as parent:
            os.unlink("transaction.json", dir_fd=parent)
            os.fsync(parent)
        ready = None
        if start:
            status, _output = systemctl("start", "lsf.service")
            require(status == 0, "service-start-or-authenticated-readiness-failed")
            child_check(layout, identity, "readiness")
            ready = True
        if enable:
            status, _output = systemctl("enable", "lsf.service")
            require(status == 0, "service-enable-failed")
        return {"schemaVersion": "latent.native-install-result.v1", "installationId": installed["installationId"],
                "version": selected, "sourceCommit": release.metadata["sourceCommit"], "profile": profile,
                "activationReady": ready, "preflight": preflight, "experimental": True}


def remove(layout: Layout, *, purge: str | None = None) -> dict:
    identity = node_identity(layout)
    with ExitStack() as stack:
        stack.enter_context(files.lock(layout.prefix / "install.lock"))
        if not layout.system:
            stack.enter_context(files.lock(layout.prefix / "run.lock", timeout=0))
        require(not os.path.lexists(layout.transaction), "finish-interrupted-installation-before-removal")
        prefix_inventory(layout)
        state = read_state(layout)
        require(state is not None, "installation-state-required")
        if purge is not None:
            require(purge == state["installationId"] and state["status"] in {"removed", "purged"}, "purge-requires-removal-and-exact-installation-id")
            journal = layout.prefix / "purge.json"
            if state["status"] == "purged":
                require(all(not os.path.lexists(path) for path in layout.roots().values()), "purged-installation-has-untracked-roots")
            elif not journal.exists():
                validate_roots(layout, state, identity)
                files.create(journal, encode({"installationId": purge}))
            else:
                require(document(files.read(journal, owners={0, os.geteuid()})) == {"installationId": purge},
                        "purge-journal-mismatch")
            for name, path in layout.roots().items():
                if os.path.lexists(path):
                    require(files.identity(path, {0, os.geteuid(), identity[0]}) == state["roots"][name],
                            "installation-root-substitution")
                    files.remove_tree(path)
            state["status"] = "purged"
            files.replace(layout.state, encode(state), 0o644)
            with files.directory(layout.prefix, {0, os.geteuid()}) as parent:
                if os.path.lexists(journal):
                    require(document(files.read(journal, owners={0, os.geteuid()})) == {"installationId": purge}, "purge-journal-mismatch")
                    os.unlink("purge.json", dir_fd=parent)
                os.fsync(parent)
            return {"schemaVersion": "latent.native-removal.v1", "purged": True, "accountRetained": layout.system,
                    "installationId": state["installationId"]}
        require(not os.path.lexists(layout.prefix / "purge.json"), "finish-interrupted-purge")
        require(state["status"] != "purged", "installation-already-purged")
        validate_roots(layout, state, identity)
        if layout.system and state["status"] == "installed":
            require(files.digest(UNIT) == state["unitSha256"], "operator-modified-unit-not-removed")
            stop_service()
            status, _output = systemctl("disable", "lsf.service")
            require(status == 0, "service-disable-failed")
        if state["status"] != "removed":
            state["status"] = "removing-stopped"
            files.replace(layout.state, encode(state), 0o644)
        if layout.system and os.path.lexists(UNIT):
            require(files.digest(UNIT) == state["unitSha256"], "operator-modified-unit-not-removed")
            with files.directory(UNIT.parent, {0}) as parent:
                os.unlink(UNIT.name, dir_fd=parent)
                os.fsync(parent)
            status, _output = systemctl("daemon-reload")
            require(status == 0, "systemd-daemon-reload-failed")
        if os.path.lexists(layout.current):
            require(current(layout) == layout.prefix / "releases" / state["currentVersion"], "current-release-link-substitution")
            with files.directory(layout.prefix, {0, os.geteuid()}) as parent:
                os.unlink("current", dir_fd=parent)
                os.fsync(parent)
        for selected, release in state["releases"].items():
            root = layout.prefix / "releases" / selected
            if os.path.lexists(root):
                archive.check_tree(root, release["metadata"]["files"], allow_missing=state["status"] == "removing-stopped")
                files.remove_tree(root, maximum=8192)
        state["status"] = "removed"
        files.replace(layout.state, encode(state), 0o644)
        return {"schemaVersion": "latent.native-removal.v1", "purged": False, "configurationAndDataRetained": True,
                "installationId": state["installationId"]}

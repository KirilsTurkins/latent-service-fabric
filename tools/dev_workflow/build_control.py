"""Identity-scoped build cancellation without acquiring the active build lock."""
from contextlib import contextmanager
from pathlib import Path
import re
import time

from . import build_cache, state
from .common import DevError, members, require

TERMINAL = {"reaped", "idle"}


def identifier(value: str) -> str:
    require(isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value), "build-request-identity")
    return value


def status(root: Path) -> dict:
    if not (root / "active-build.json").exists():
        return {"state": "idle"}
    value = members(state.load(root, "active-build.json"), {"id", "state", "guestInstance", "attempt", "reason"})
    identifier(value["id"])
    if value["attempt"] is not None:
        identifier(value["attempt"])
    require(value["state"] in {"running", "reaped", "uncertain"}, "active-build-state")
    return value


def cancel(root: Path, selected: str, reason: str = "cancelled") -> dict:
    identifier(selected)
    require(reason in {"cancelled", "superseded", "workspace-stopped"}, "build-cancellation-reason")
    active = status(root)
    if active.get("id") != selected or active["state"] != "running":
        return {"accepted": False, "build": active}
    # One bounded marker, targeting one immutable request identity. A later
    # build cannot inherit this cancellation, even if the response was lost.
    state.atomic(root, "build-cancel.json", {"id": selected, "reason": reason})
    return {"accepted": True, "build": active}


def _reconcile(root: Path) -> dict:
    from .service import guest_instance
    active = status(root)
    if active["state"] not in TERMINAL and active["guestInstance"] != guest_instance():
        if active["attempt"] is not None:
            attempt = root / "builds" / active["attempt"]
            build_cache.transition(attempt, "failed")
        active.update(state="reaped", reason="guest-restarted-build-interrupted")
        state.atomic(root, "active-build.json", active)
    return active


def reconcile(root: Path) -> dict:
    with state.lock(root, "build-control.lock", timeout=1):
        return _reconcile(root)


def stop(root: Path) -> None:
    active = reconcile(root)
    if active["state"] == "running":
        cancel(root, active["id"], "workspace-stopped")


def wait_stopped(root: Path, timeout: float = 8) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        active = reconcile(root)
        if active["state"] in TERMINAL:
            return active
        if active["state"] == "uncertain" or time.monotonic() >= deadline:
            raise DevError("build-cleanup-unconfirmed-inspect-owned-workspace", uncertain=True)
        time.sleep(0.05)


class Control:
    def __init__(self, root: Path, selected: str):
        from .service import guest_instance
        self.root = root
        self.record = {"id": identifier(selected), "state": "running", "guestInstance": guest_instance(),
                       "attempt": None, "reason": None}

    def attach(self, attempt: Path) -> None:
        require(attempt.parent == self.root / "builds", "build-control-attempt-owner")
        build_cache.owner(attempt)
        self.record["attempt"] = attempt.name
        state.atomic(self.root, "active-build.json", self.record)

    def check(self) -> None:
        if (self.root / "build-cancel.json").exists():
            requested = members(state.load(self.root, "build-cancel.json"), {"id", "reason"})
            if requested["id"] == self.record["id"]:
                require(requested["reason"] in {"cancelled", "superseded", "workspace-stopped"}, "build-cancellation-reason")
                raise DevError("guest-build-" + requested["reason"])


@contextmanager
def session(root: Path, selected: str):
    from tools.build_process_signals import owned_cancellation
    control = Control(root, selected)
    with owned_cancellation() as cancellation:
        with state.lock(root, "build-control.lock", timeout=1):
            prior = _reconcile(root)
            if prior["state"] not in TERMINAL:
                raise DevError("previous-build-cleanup-unconfirmed", uncertain=True)
            state.atomic(root, "active-build.json", control.record)
        try:
            yield control
        except BaseException as error:
            control.record.update(state="uncertain" if isinstance(error, DevError) and error.uncertain else "reaped",
                                  reason=error.code if isinstance(error, DevError) else "build-interrupted")
            raise
        else:
            control.record.update(state="reaped", reason="build-complete")
        finally:
            with cancellation.defer():
                with state.lock(root, "build-control.lock", timeout=1):
                    require(status(root)["id"] == control.record["id"], "active-build-identity-changed")
                    state.atomic(root, "active-build.json", control.record)

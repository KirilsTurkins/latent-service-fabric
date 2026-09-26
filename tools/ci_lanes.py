"""Bounded same-runner CI scheduling policy (not a process or artifact owner).

Callers supply the *already selected* graph and validated completion data. This
module does not select suites, validate native images, build fixtures, spawn
processes, emit product receipts, or change activation deadlines. In particular,
resources remain charged until the runner reports teardown via ``retire``.

Worker count is deliberately mandatory: choosing a production default requires
comparable completed serial/two-worker observations, not synthetic timings.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from types import MappingProxyType
from typing import Mapping

MAX_STAGES = 256
MAX_CASES = 100_000
MAX_WATCHDOG_SECONDS = 7200
_NAME = re.compile(r"[a-z][a-z0-9._-]{0,95}\Z")


class LaneError(ValueError):
    """An invalid plan, stale lease or invalid lifecycle transition."""


class State(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    CANCELLING = "cancelling"
    RETIRING = "retiring"
    SUCCESS = "success"
    FAILURE = "failure"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


class Phase(str, Enum):
    HOST_BUILD = "host-build"
    COMPONENT_GENERATION = "component-generation"
    NATIVE_PREPARATION = "native-preparation"
    EXECUTION = "execution"
    TEARDOWN = "teardown"
    TRANSFER = "transfer"
    CACHE_WARMING = "cache-warming"


TERMINAL = frozenset({State.SUCCESS, State.FAILURE, State.CANCELLED, State.BLOCKED})
FAILED = TERMINAL - {State.SUCCESS}


@dataclass(frozen=True)
class Stage:
    """Scheduling metadata from upstream suite/recipe owners.

    ``cases`` and ``receipts`` describe expected observations, not proof of their
    authenticity. The prepared-artifact/product adapters validate those first.
    ``watchdog_seconds`` is a total stage watchdog, never an activation budget.
    A physical probe must declare ``exclusive=True`` on its runner.
    """

    name: str
    phase: Phase
    group: str
    watchdog_seconds: int
    needs: tuple[str, ...] = ()
    cases: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()
    exclusive: bool = False


@dataclass(frozen=True)
class Lease:
    stage: Stage
    # Identity, rather than a predictable stage name, scopes completion to the
    # current dispatch. This is an in-process ownership token, not a credential.
    token: object


@dataclass(frozen=True)
class Completion:
    stage: str
    outcome: State
    cases: tuple[str, ...] = ()
    receipts: tuple[str, ...] = ()


def _names(values: tuple[str, ...], *, limit: int, label: str) -> None:
    if not isinstance(values, tuple) or len(values) > limit:
        raise LaneError(f"invalid-{label}")
    if any(not isinstance(value, str) or not value or len(value) > 1024
           or '\0' in value for value in values):
        raise LaneError(f"invalid-{label}")
    if len(set(values)) != len(values):
        raise LaneError(f"duplicate-{label}")


class Scheduler:
    """Single-coordinator policy; process supervision stays in existing runners.

    ``claim_ready`` atomically reserves all returned leases. Independent stages
    may continue after a failure, but dependents of failed work never dispatch.
    On interruption call ``cancel``, ask the owners to stop, and call ``retire``
    only after each owner has actually reclaimed its children/private roots.
    """

    def __init__(self, stages: tuple[Stage, ...], *, workers: int,
                 capacities: Mapping[str, int]) -> None:
        if type(workers) is not int or workers not in (1, 2):
            raise LaneError("workers-must-be-one-or-two")
        if (not isinstance(stages, tuple) or not stages or len(stages) > MAX_STAGES
                or any(not isinstance(stage, Stage) for stage in stages)):
            raise LaneError("invalid-stage-count")
        if not isinstance(capacities, Mapping) or not capacities or len(capacities) > MAX_STAGES:
            raise LaneError("invalid-resource-groups")
        for name, value in capacities.items():
            if (not isinstance(name, str) or not _NAME.fullmatch(name)
                    or type(value) is not int or not 1 <= value <= workers):
                raise LaneError("invalid-resource-capacity")
        for stage in stages:
            if not isinstance(stage.name, str) or not _NAME.fullmatch(stage.name):
                raise LaneError("invalid-stage-name")
            if (not isinstance(stage.phase, Phase) or not isinstance(stage.group, str)
                    or stage.group not in capacities):
                raise LaneError("undeclared-phase-or-resource-group")
            if (type(stage.watchdog_seconds) is not int
                    or not 1 <= stage.watchdog_seconds <= MAX_WATCHDOG_SECONDS
                    or type(stage.exclusive) is not bool):
                raise LaneError("invalid-stage-watchdog-or-exclusion")
            _names(stage.needs, limit=MAX_STAGES, label="dependencies")
            _names(stage.cases, limit=MAX_CASES, label="cases")
            _names(stage.receipts, limit=MAX_STAGES, label="receipts")
            if stage.phase == Phase.EXECUTION and not stage.cases:
                raise LaneError("empty-execution-selection")
        names = [stage.name for stage in stages]
        if len(set(names)) != len(names):
            raise LaneError("duplicate-stage")
        self._stages = {stage.name: stage for stage in stages}
        if any(need not in self._stages for stage in stages for need in stage.needs):
            raise LaneError("missing-prerequisite")
        remaining = dict(self._stages)
        visited: set[str] = set()
        while remaining:
            ready = [name for name, stage in remaining.items() if set(stage.needs) <= visited]
            if not ready:
                raise LaneError("cyclic-prerequisites")
            for name in ready:
                visited.add(name)
                del remaining[name]
        self.workers = workers
        self.capacities = MappingProxyType(dict(capacities))
        self._states = {name: State.PENDING for name in names}
        self._live: dict[str, Lease] = {}
        self._outcomes: dict[str, State] = {}
        self._reasons: dict[str, str] = {}
        self._cancelled = False

    @property
    def states(self) -> Mapping[str, State]:
        return MappingProxyType(dict(self._states))

    @property
    def reasons(self) -> Mapping[str, str]:
        return MappingProxyType(dict(self._reasons))

    @property
    def finished(self) -> bool:
        return all(state in TERMINAL for state in self._states.values())

    @property
    def passed(self) -> bool:
        return not self._cancelled and all(state == State.SUCCESS for state in self._states.values())

    def _block_dependents(self) -> None:
        changed = True
        while changed:
            changed = False
            for name, stage in self._stages.items():
                if (self._states[name] == State.PENDING
                        and any(self._states[need] in FAILED for need in stage.needs)):
                    self._states[name] = State.BLOCKED
                    self._reasons[name] = "unsuccessful-prerequisite"
                    changed = True

    def claim_ready(self) -> tuple[Lease, ...]:
        self._block_dependents()
        if self._cancelled or any(lease.stage.exclusive for lease in self._live.values()):
            return ()
        ready = [stage for name, stage in self._stages.items()
                 if self._states[name] == State.PENDING
                 and all(self._states[need] == State.SUCCESS for need in stage.needs)]
        # A ready physical/exclusive probe is a barrier. Drain running work
        # before it starts; don't keep filling spare slots and starve the probe.
        exclusive = next((stage for stage in ready if stage.exclusive), None)
        if exclusive is not None:
            if self._live:
                return ()
            ready = [exclusive]
        leases = []
        for stage in ready:
            if len(self._live) >= self.workers:
                break
            usage = sum(lease.stage.group == stage.group for lease in self._live.values())
            if usage >= self.capacities[stage.group]:
                continue
            lease = Lease(stage, object())
            self._live[stage.name] = lease
            self._states[stage.name] = State.RUNNING
            leases.append(lease)
        return tuple(leases)

    def _owned(self, lease: Lease) -> str:
        if not isinstance(lease, Lease) or self._live.get(lease.stage.name) is not lease:
            raise LaneError("foreign-or-retired-lease")
        return lease.stage.name

    def complete(self, lease: Lease, report: Completion | None) -> None:
        """Observe an exit; retain its resources until teardown, even on failure.

        Missing/wrong observations fail the stage rather than yielding a passed
        exit-code-only check. Invalid reports cannot unblock any dependents.
        """
        name = self._owned(lease)
        if self._states[name] not in {State.RUNNING, State.CANCELLING}:
            raise LaneError("duplicate-completion")
        outcome = State.FAILURE
        reason = "missing-completion"
        if isinstance(report, Completion):
            reason = "invalid-completion"
            if (report.stage == name and isinstance(report.outcome, State)
                    and report.outcome in {State.SUCCESS, State.FAILURE, State.CANCELLED}):
                outcome = report.outcome
                reason = "reported-" + outcome.value
                if outcome == State.SUCCESS:
                    try:
                        _names(report.cases, limit=MAX_CASES, label="reported-cases")
                        _names(report.receipts, limit=MAX_STAGES, label="reported-receipts")
                        if set(report.cases) != set(lease.stage.cases):
                            raise LaneError("case-parity-mismatch")
                        if set(report.receipts) != set(lease.stage.receipts):
                            raise LaneError("receipt-parity-mismatch")
                    except LaneError as error:
                        outcome, reason = State.FAILURE, str(error)
        if self._cancelled:
            outcome, reason = State.CANCELLED, "run-cancelled"
        self._outcomes[name] = outcome
        self._reasons[name] = reason
        self._states[name] = State.RETIRING

    def retire(self, lease: Lease) -> None:
        """Owner confirms teardown has finished. Never call this on mere exit."""
        name = self._owned(lease)
        if self._states[name] != State.RETIRING:
            raise LaneError("retirement-before-completion")
        self._states[name] = self._outcomes[name]
        del self._live[name]
        self._block_dependents()

    def cancel(self) -> tuple[Lease, ...]:
        """Latch interruption; return still-owned work for runner cleanup.

        Cancellation cannot turn into success, including a cancellation arriving
        between a successful process exit and retirement of its descendants.
        """
        self._cancelled = True
        for name, state in self._states.items():
            if state == State.PENDING:
                self._states[name] = State.CANCELLED
                self._reasons[name] = "run-cancelled"
            elif state == State.RUNNING:
                self._states[name] = State.CANCELLING
            elif state == State.RETIRING:
                self._outcomes[name] = State.CANCELLED
                self._reasons[name] = "run-cancelled"
        return tuple(self._live.values())

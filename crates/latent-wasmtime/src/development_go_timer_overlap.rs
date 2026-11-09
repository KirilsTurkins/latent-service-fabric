//! Closed, activation-owned witness for the signed Go timer overlap fixture.
//!
//! Fixed-capacity state holds at most four Task tokens and five timer tokens.
//! Both Arc backings are prepaid on the original activation, and their charge
//! survives every detached wait clone. The optional barrier uses an already
//! budget-owned provider wait as its finite timeout and invents no result.
use std::{
    alloc::Layout,
    io::Write,
    sync::{atomic::AtomicUsize, Arc, Mutex},
    time::{Duration, Instant},
};

use crate::development_go_timer_fired_state::{Mode as FiredMode, Witness as FiredWitness};
use latent_core::{
    activation_runtime::{OwnerKind, RuntimeToken},
    ActivationBudget, HostMemoryReservation, PlatformError, PlatformErrorCode,
};
use latent_executor::PreparationReadWait;
use tokio::sync::Notify;

const MAX_TASKS: usize = 4;
const BARRIER_LIMIT: Duration = Duration::from_secs(2);
const STOP_OBSERVATION: Duration = Duration::from_millis(10);
const ALLOCATION_BOOKKEEPING: usize = 64;
const GC_MARKER_PERIOD_NANOS: u64 = 37 * 60 * 1_000_000_000;
const ROOT_MARKER_PERIOD_NANOS: u64 = 41 * 60 * 1_000_000_000;
const PREFIX: &str = "LSF-GO-TIMER-OVERLAP-V4";
const DROP_PREFIX: &str = "LSF-GO-TIMER-WAIT-DROP-V1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Case {
    ResetReset,
    ResetStop,
    GcResetReset,
    GcResetStop,
    CancelResetReset,
    DeadlineResetStop,
    FiredStop,
    FiredReset,
    ReturnedStop,
    ReturnedReset,
}

impl Case {
    #[must_use]
    pub(crate) const fn activation(self) -> &'static str {
        match self {
            Self::ResetReset => "go-timer-overlap-reset-reset",
            Self::ResetStop => "go-timer-overlap-reset-stop",
            Self::GcResetReset => "go-timer-overlap-gc-reset-reset",
            Self::GcResetStop => "go-timer-overlap-gc-reset-stop",
            Self::CancelResetReset => "go-timer-overlap-cancel-reset-reset",
            Self::DeadlineResetStop => "go-timer-overlap-deadline-reset-stop",
            Self::FiredStop => "go-timer-fired-stop",
            Self::FiredReset => "go-timer-fired-reset",
            Self::ReturnedStop => "go-timer-returned-stop",
            Self::ReturnedReset => "go-timer-returned-reset",
        }
    }

    const fn fired(self) -> bool {
        matches!(self, Self::FiredStop | Self::FiredReset)
    }

    const fn returned(self) -> bool {
        matches!(self, Self::ReturnedStop | Self::ReturnedReset)
    }

    const fn requires_gc(self) -> bool {
        matches!(self, Self::GcResetReset | Self::GcResetStop)
    }

    const fn hold_for_root_stop(self) -> bool {
        matches!(self, Self::CancelResetReset | Self::DeadlineResetStop)
    }
}

#[derive(Clone, Copy, Debug, Default)]
struct Marker {
    timer: Option<RuntimeToken>,
    task: Option<RuntimeToken>,
    stopped: bool,
    parked: bool,
}

#[derive(Clone, Copy, Debug)]
struct State {
    case: Option<Case>,
    fired: Option<FiredWitness>,
    invalid: bool,
    timeout: bool,
    tasks: [Option<RuntimeToken>; MAX_TASKS],
    task_count: usize,
    target: Option<RuntimeToken>,
    next_live: bool,
    next_seen: bool,
    next_pending: bool,
    next_finished: bool,
    target_stopped: bool,
    markers: [Marker; 2],
    gc_marker: Option<RuntimeToken>,
    gc_marker_stopped: bool,
    second_waiting: bool,
    handshake_confirmed: bool,
    ready_before_stop: bool,
}

impl State {
    const fn new() -> Self {
        Self {
            case: None,
            fired: None,
            invalid: false,
            timeout: false,
            tasks: [None; MAX_TASKS],
            task_count: 0,
            target: None,
            next_live: false,
            next_seen: false,
            next_pending: false,
            next_finished: false,
            target_stopped: false,
            markers: [Marker {
                timer: None,
                task: None,
                stopped: false,
                parked: false,
            }; 2],
            gc_marker: None,
            gc_marker_stopped: false,
            second_waiting: false,
            handshake_confirmed: false,
            ready_before_stop: false,
        }
    }

    // Returned-event qualification reuses the existing fixed-capacity fields:
    // ready_before_stop = event probe; markers[0].stopped = fence probe;
    // markers[0].parked = root park; handshake_confirmed = exact channel probe;
    // markers[1].stopped = post-subtask-drop probe; second_waiting = root wake;
    // markers[1].timer/parked = replacement/stopped; markers[0].timer and
    // gc_marker_stopped = public-return marker and its stop. No extra Arc or
    // storage is admitted, and these fields retain their old meanings elsewhere.
    fn returned_start(
        &mut self,
        token: RuntimeToken,
        parent: Option<RuntimeToken>,
        period: Option<u64>,
    ) {
        let root = self.tasks[0];
        if self.invalid || self.task_count != 1 || root.is_none() || parent != root {
            self.invalid = true;
            return;
        }
        if self.target.is_none() {
            if period != Some(251_000_000) {
                self.invalid = true;
                return;
            }
            self.target = Some(token);
        } else if !self.markers[1].stopped || !self.second_waiting || Some(token) == self.target {
            self.invalid = true;
        } else if self.case == Some(Case::ReturnedReset) && self.markers[1].timer.is_none() {
            if period != Some(3_600_000_000_000) {
                self.invalid = true;
                return;
            }
            self.markers[1].timer = Some(token);
        } else if self.markers[0].timer.is_none()
            && (self.case == Some(Case::ReturnedStop) || self.markers[1].parked)
            && period.is_none()
            && self.markers[1].timer != Some(token)
        {
            self.markers[0].timer = Some(token);
        } else {
            self.invalid = true;
        }
    }

    fn returned_stop(&mut self, token: RuntimeToken) {
        if self.invalid {
            return;
        }
        if Some(token) == self.target {
            if !self.ready_before_stop || !self.next_finished || self.target_stopped {
                self.invalid = true;
            } else {
                self.target_stopped = true;
            }
        } else if Some(token) == self.markers[1].timer {
            if !self.second_waiting || !self.markers[1].stopped || self.markers[1].parked {
                self.invalid = true;
            } else {
                self.markers[1].parked = true;
            }
        } else if Some(token) == self.markers[0].timer {
            if self.gc_marker_stopped {
                self.invalid = true;
            } else {
                self.gc_marker_stopped = true;
            }
        } else {
            self.invalid = true;
        }
    }

    fn returned_probe(&mut self, waits: u32, timers: u32) {
        if self.invalid {
            return;
        }
        if !self.ready_before_stop {
            if !self.next_seen
                || !self.next_pending
                || !self.next_finished
                || self.target_stopped
                || waits != 0
                || timers != 1
            {
                self.invalid = true;
            } else {
                self.ready_before_stop = true;
            }
        } else if !self.markers[0].stopped {
            if !self.target_stopped || self.next_live || waits != 0 || timers != 0 {
                self.invalid = true;
            } else {
                self.markers[0].stopped = true;
            }
        } else if !self.handshake_confirmed {
            if !self.markers[0].parked || waits != 0 || timers != 0 {
                self.invalid = true;
            } else {
                self.handshake_confirmed = true;
            }
        } else if !self.markers[1].stopped {
            if !self.markers[0].parked || waits != 0 || timers != 0 {
                self.invalid = true;
            } else {
                self.markers[1].stopped = true;
            }
        } else {
            self.invalid = true;
        }
    }

    fn returned_complete(&self) -> bool {
        !self.invalid
            && self.task_count == 1
            && self.next_seen
            && self.next_pending
            && self.next_finished
            && !self.next_live
            && self.ready_before_stop
            && self.target_stopped
            && self.markers[0].stopped
            && self.markers[0].parked
            && self.handshake_confirmed
            && self.markers[1].stopped
            && self.second_waiting
            && self.markers[0].timer.is_some()
            && self.gc_marker_stopped
            && (self.case == Some(Case::ReturnedStop)
                || (self.markers[1].timer.is_some() && self.markers[1].parked))
    }

    fn task(&mut self, kind: OwnerKind, token: RuntimeToken, parent: Option<RuntimeToken>) {
        if kind != OwnerKind::Task {
            return;
        }
        if self.task_count == MAX_TASKS || self.tasks.contains(&Some(token)) {
            self.invalid = true;
            return;
        }
        if (self.task_count == 0 && parent.is_some())
            || (self.task_count != 0 && parent != self.tasks[0])
        {
            self.invalid = true;
        }
        self.tasks[self.task_count] = Some(token);
        self.task_count += 1;
    }

    fn timer_start(
        &mut self,
        token: RuntimeToken,
        parent: Option<RuntimeToken>,
        period: Option<u64>,
    ) {
        if self.case.is_some_and(Case::returned) {
            self.returned_start(token, parent, period);
            return;
        }
        if let Some(case) = self.case.filter(|case| case.fired()) {
            let Some(root) = self.tasks[0] else {
                self.invalid = true;
                return;
            };
            let Some(parent) = parent else {
                self.invalid = true;
                return;
            };
            let mode = if case == Case::FiredStop {
                FiredMode::Stop
            } else {
                FiredMode::Reset
            };
            let fired = self
                .fired
                .get_or_insert_with(|| FiredWitness::new(mode, root));
            fired.timer_start(token, parent, period.is_some());
            self.invalid |= fired.invalid();
            return;
        }
        if self.markers[1].parked {
            return;
        }
        if self.case.is_some_and(Case::requires_gc) && self.markers[1].stopped {
            if !self.next_live
                || !self.next_pending
                || !self.target_stopped
                || !self.markers[0].parked
                || Some(token) == self.target
                || self
                    .markers
                    .iter()
                    .any(|marker| marker.timer == Some(token))
            {
                self.invalid = true;
            } else if self.gc_marker.is_none()
                && parent == self.markers[1].task
                && period == Some(GC_MARKER_PERIOD_NANOS)
            {
                self.gc_marker = Some(token);
            } else if self.gc_marker_stopped
                && !self.handshake_confirmed
                && self.second_waiting
                && parent == self.tasks[0]
                && period == Some(ROOT_MARKER_PERIOD_NANOS)
                && Some(token) != self.gc_marker
            {
                // The root can emit this marker only after the worker's
                // GC-marker Stop returned and it signalled the root. A live
                // park at this point is therefore the handshake receive.
                self.handshake_confirmed = true;
            } else {
                self.invalid = true;
            }
            return;
        }
        if period.is_some() {
            self.invalid = true;
            return;
        }
        if !self.next_seen {
            if self.target.is_some() || parent != self.tasks[0] || self.tasks[0].is_none() {
                self.invalid = true;
            } else {
                self.target = Some(token);
            }
            return;
        }
        if !self.next_pending {
            self.invalid = true;
            return;
        }
        let index = usize::from(self.markers[0].timer.is_some());
        if index == 1 && (!self.markers[0].parked || self.markers[1].timer.is_some()) {
            self.invalid = true;
            return;
        }
        let expected = self.tasks[index + 2];
        if expected.is_none() || parent != expected || Some(token) == self.target {
            self.invalid = true;
            return;
        }
        self.markers[index].timer = Some(token);
        self.markers[index].task = expected;
    }

    fn next(&mut self, token: RuntimeToken, waits: u32) -> bool {
        if self.case.is_some_and(Case::returned) {
            if self.invalid || self.next_seen || Some(token) != self.target || waits == 0 {
                self.invalid = true;
                return false;
            }
            self.next_seen = true;
            self.next_live = true;
            return true;
        }
        if self.case.is_some_and(Case::fired) {
            let Some(fired) = self.fired.as_mut() else {
                self.invalid = true;
                return false;
            };
            let accepted = fired.accepted_next(token, waits);
            self.invalid |= fired.invalid();
            return accepted;
        }
        if self.markers[1].parked {
            return false;
        }
        if self.next_seen || Some(token) != self.target || waits == 0 {
            self.invalid = true;
            return false;
        }
        self.next_seen = true;
        self.next_live = true;
        true
    }

    fn next_pending(&mut self, token: RuntimeToken) {
        if self.case.is_some_and(Case::returned) {
            if Some(token) != self.target
                || !self.next_live
                || self.next_pending
                || self.target_stopped
            {
                self.invalid = true;
            } else {
                self.next_pending = true;
            }
            return;
        }
        if self.case.is_some_and(Case::fired) {
            let Some(fired) = self.fired.as_mut() else {
                self.invalid = true;
                return;
            };
            fired.pending(token);
            self.invalid |= fired.invalid();
            return;
        }
        if Some(token) != self.target || !self.next_live || self.target_stopped || self.next_pending
        {
            self.invalid = true;
            return;
        }
        self.next_pending = true;
    }

    fn timer_stop(&mut self, token: RuntimeToken, waits: u32) {
        if self.case.is_some_and(Case::returned) {
            self.returned_stop(token);
            return;
        }
        if self.case.is_some_and(Case::fired) {
            let Some(fired) = self.fired.as_mut() else {
                self.invalid = true;
                return;
            };
            fired.timer_stop(token, waits);
            self.invalid |= fired.invalid();
            return;
        }
        if self.markers[1].parked {
            return;
        }
        if Some(token) == self.markers[0].timer {
            if self.markers[0].stopped {
                self.invalid = true;
            }
            self.markers[0].stopped = true;
        } else if Some(token) == self.target {
            if !self.markers[0].stopped
                || self.target_stopped
                || !self.next_live
                || !self.next_pending
                || waits == 0
            {
                self.invalid = true;
            }
            self.target_stopped = true;
        } else if Some(token) == self.markers[1].timer {
            if !self.markers[0].parked || self.markers[1].stopped {
                self.invalid = true;
            }
            self.markers[1].stopped = true;
        } else if Some(token) == self.gc_marker {
            if self.gc_marker_stopped || !self.next_live || !self.next_pending || waits == 0 {
                self.invalid = true;
            }
            self.gc_marker_stopped = true;
        } else {
            self.invalid = true;
        }
    }

    fn park(&mut self, task: RuntimeToken, waits: u32) -> bool {
        if self.case.is_some_and(Case::returned) {
            if Some(task) == self.tasks[0] && self.markers[0].stopped {
                if self.markers[0].parked {
                    self.invalid = true;
                } else {
                    self.markers[0].parked = true;
                }
            }
            return false;
        }
        if self.markers[1].parked {
            return false;
        }
        for index in 0..2 {
            if self.markers[index].task != Some(task) {
                if self.markers[index]
                    .task
                    .is_some_and(|expected| expected.id == task.id)
                {
                    self.invalid = true;
                }
                continue;
            }
            // Collection, its marker's fence, and the handshake can all park.
            // Only a park after the root confirmed the live handshake counts.
            if index == 1
                && self.case.is_some_and(Case::requires_gc)
                && self.markers[1].stopped
                && !self.handshake_confirmed
            {
                self.second_waiting = true;
                return false;
            }
            if !self.markers[index].stopped
                || !self.target_stopped
                || !self.next_live
                || !self.next_pending
                || waits == 0
                || self.markers[index].parked
                || (index == 1 && !self.markers[0].parked)
            {
                self.invalid = true;
                return false;
            }
            self.markers[index].parked = true;
            return index == 1;
        }
        false
    }

    fn wake(&mut self, task: RuntimeToken) {
        if self.case.is_some_and(Case::returned) {
            if Some(task) == self.tasks[0] && self.markers[0].parked {
                if !self.markers[1].stopped || self.second_waiting {
                    self.invalid = true;
                } else {
                    self.second_waiting = true;
                }
            }
            return;
        }
        if self.markers[1].task == Some(task) {
            self.second_waiting = false;
        }
    }

    fn next_finished(&mut self, token: RuntimeToken) {
        if self.case.is_some_and(Case::returned) {
            if Some(token) != self.target
                || !self.next_live
                || !self.next_pending
                || self.target_stopped
            {
                self.invalid = true;
            } else {
                self.next_live = false;
                self.next_finished = true;
            }
            return;
        }
        if self.case.is_some_and(Case::fired) {
            let Some(fired) = self.fired.as_mut() else {
                self.invalid = true;
                return;
            };
            fired.original_dropped(token, true);
            self.invalid |= fired.invalid();
            return;
        }
        if Some(token) != self.target {
            self.invalid = true;
            return;
        }
        if !self.next_live || !self.markers[1].parked {
            self.invalid = true;
        }
        self.next_live = false;
        self.next_finished = true;
    }

    fn snapshot(&self) -> Snapshot {
        Snapshot {
            complete: !self.invalid
                && !self.timeout
                && self.task_count == MAX_TASKS
                && self.next_seen
                && self.next_pending
                && (self.next_finished
                    || (self.case.is_some_and(Case::hold_for_root_stop) && self.ready_before_stop))
                && self.target_stopped
                && (!self.case.is_some_and(Case::requires_gc) || self.gc_marker_stopped)
                && (!self.case.is_some_and(Case::requires_gc) || self.handshake_confirmed)
                && self
                    .markers
                    .iter()
                    .all(|marker| marker.stopped && marker.parked),
            invalid: self.invalid,
            timeout: self.timeout,
            tasks: self.task_count,
            next_seen: self.next_seen,
            next_pending: self.next_pending,
            target_stopped: self.target_stopped,
            first_parked: self.markers[0].parked,
            gc_marker_stopped: self.gc_marker_stopped,
            handshake_confirmed: self.handshake_confirmed,
            ready_before_stop: self.ready_before_stop,
            second_parked: self.markers[1].parked,
            next_finished: self.next_finished,
        }
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Snapshot {
    pub complete: bool,
    pub invalid: bool,
    pub timeout: bool,
    pub tasks: usize,
    pub next_seen: bool,
    pub next_pending: bool,
    pub target_stopped: bool,
    pub first_parked: bool,
    pub gc_marker_stopped: bool,
    pub handshake_confirmed: bool,
    pub ready_before_stop: bool,
    pub second_parked: bool,
    pub next_finished: bool,
}

struct Inner {
    state: Mutex<State>,
    parked: Notify,
}
struct Charge {
    allocation: HostMemoryReservation,
}

// Only strong billing handles exist. The last one frees its Arc allocation
// before the extracted reservation is dropped, matching runtime::Shared.
struct Billing(Option<Arc<Charge>>);
impl Clone for Billing {
    fn clone(&self) -> Self {
        Self(Some(Arc::clone(self.0.as_ref().expect("live billing"))))
    }
}
impl Drop for Billing {
    fn drop(&mut self) {
        if let Some(charge) = self.0.take() {
            let charge = Arc::into_inner(charge);
            #[cfg(test)]
            if charge.is_some() {
                tests::record_before_refund();
            }
            drop(charge);
        }
    }
}

// Field order drops the payload Arc before its corresponding billing Arc.
#[derive(Clone)]
pub(crate) struct Observer {
    inner: Arc<Inner>,
    billing: Billing,
}

fn arc_bytes<T>() -> Option<usize> {
    // The pinned Rust 1.97.1 ArcInner is the two-word header followed by T.
    Layout::new::<[AtomicUsize; 2]>()
        .extend(Layout::new::<T>())
        .ok()?
        .0
        .pad_to_align()
        .size()
        .checked_add(ALLOCATION_BOOKKEEPING)
}

impl Observer {
    pub(crate) fn select(activation: &str) -> Option<Case> {
        [
            Case::ResetReset,
            Case::ResetStop,
            Case::GcResetReset,
            Case::GcResetStop,
            Case::CancelResetReset,
            Case::DeadlineResetStop,
            Case::FiredStop,
            Case::FiredReset,
            Case::ReturnedStop,
            Case::ReturnedReset,
        ]
        .into_iter()
        .find(|case| case.activation() == activation)
    }

    pub(crate) fn new(case: Case, budget: &ActivationBudget) -> Result<Self, PlatformError> {
        let (payload, total) = (|| {
            let payload = arc_bytes::<Inner>()?;
            let total = payload.checked_add(arc_bytes::<Charge>()?)?;
            Some((u64::try_from(payload).ok()?, u64::try_from(total).ok()?))
        })()
        .ok_or_else(|| {
            crate::containment::platform_error(
                PlatformErrorCode::ResourceExhausted,
                "go-timer-overlap-allocation",
                false,
            )
        })?;
        let mut allocation = budget
            .reserve_host_memory(total)
            .map_err(|error| error.to_host_memory_error())?;
        let inner = Arc::new(Inner {
            state: Mutex::new(State {
                case: Some(case),
                ..State::new()
            }),
            parked: Notify::new(),
        });
        allocation.confirm_bytes(payload);
        let mut billing = Arc::new(Charge { allocation });
        Arc::get_mut(&mut billing)
            .expect("new billing")
            .allocation
            .confirm();
        Ok(Self {
            inner,
            billing: Billing(Some(billing)),
        })
    }

    fn apply(&self, callback: impl FnOnce(&mut State)) {
        if let Ok(mut state) = self.inner.state.lock() {
            callback(&mut state);
        }
    }

    pub(crate) fn task(&self, kind: OwnerKind, token: RuntimeToken, parent: Option<RuntimeToken>) {
        self.apply(|state| state.task(kind, token, parent));
    }
    pub(crate) fn timer_start(
        &self,
        token: RuntimeToken,
        parent: Option<RuntimeToken>,
        period: Option<u64>,
    ) {
        self.apply(|state| state.timer_start(token, parent, period));
    }
    pub(crate) fn next(&self, token: RuntimeToken, waits: u32) -> bool {
        let mut accepted = false;
        self.apply(|state| accepted = state.next(token, waits));
        accepted
    }
    pub(crate) fn next_pending(&self, token: RuntimeToken) {
        self.apply(|state| state.next_pending(token));
    }
    pub(crate) fn timer_stop(&self, token: RuntimeToken, waits: u32) {
        self.apply(|state| state.timer_stop(token, waits));
    }
    pub(crate) fn park(&self, token: RuntimeToken, waits: u32) {
        let mut notify = false;
        self.apply(|state| notify = state.park(token, waits));
        if notify {
            self.inner.parked.notify_one();
        }
    }
    pub(crate) fn wake(&self, token: RuntimeToken) {
        self.apply(|state| state.wake(token));
    }
    pub(crate) fn next_finished(&self, token: RuntimeToken) {
        self.apply(|state| state.next_finished(token));
    }

    pub(crate) fn is_fired(&self) -> bool {
        self.inner
            .state
            .lock()
            .ok()
            .is_some_and(|state| state.case.is_some_and(Case::fired))
    }

    // The selected guest probes only when the matching fence token equals
    // its first stopped token; the host binds that stop to the real target.
    pub(crate) fn fired_probe(&self, waits: u32, timers: u32) {
        let mut release = false;
        self.apply(|state| {
            if state.case.is_some_and(Case::returned) {
                state.returned_probe(waits, timers);
                return;
            }
            if !state.case.is_some_and(Case::fired) {
                return;
            }
            if state.invalid || state.timeout {
                return;
            }
            let Some(fired) = state.fired.as_mut() else {
                state.invalid = true;
                return;
            };
            release = fired.fence_probe(waits, timers);
            state.invalid |= fired.invalid();
        });
        if release {
            self.inner.parked.notify_one();
        }
    }

    pub(crate) async fn wait_for_fired_probe(
        &self,
        token: RuntimeToken,
        provider: &dyn PreparationReadWait,
        budget: &ActivationBudget,
        deadline: Instant,
        stop: &crate::containment::StopControl,
    ) {
        self.apply(|state| {
            let Some(fired) = state.fired.as_mut() else {
                state.invalid = true;
                return;
            };
            fired.hold_due(token);
            state.invalid |= fired.invalid();
        });
        let now = provider.now();
        let cap = now
            .checked_add(BARRIER_LIMIT)
            .unwrap_or(deadline)
            .min(deadline);
        loop {
            if stop.observe().is_some() {
                self.apply(|state| state.invalid = true);
                return;
            }
            let ready = self.inner.state.lock().ok().and_then(|state| {
                if state.invalid {
                    None
                } else {
                    state.fired.as_ref().map(FiredWitness::probed)
                }
            });
            if ready != Some(false) {
                return;
            }
            let now = provider.now();
            if now >= cap {
                self.apply(|state| state.timeout = true);
                return;
            }
            let next = now.checked_add(STOP_OBSERVATION).unwrap_or(cap).min(cap);
            let Ok(mut timeout) = provider.wait_until_owned(next, budget) else {
                self.apply(|state| state.invalid = true);
                return;
            };
            let notified = self.inner.parked.notified();
            let ready = self.inner.state.lock().ok().and_then(|state| {
                if state.invalid {
                    None
                } else {
                    state.fired.as_ref().map(FiredWitness::probed)
                }
            });
            if ready != Some(false) {
                return;
            }
            tokio::select! { () = notified => {}, () = &mut timeout => {}, }
        }
    }

    pub(crate) fn report_wait_drop(&self, token: RuntimeToken, returned: bool) {
        let Ok(mut state) = self.inner.state.lock() else {
            return;
        };
        let matched = if state.case.is_some_and(Case::returned) {
            state.target == Some(token) && state.next_pending
        } else if state.case.is_some_and(Case::fired) {
            state
                .fired
                .as_ref()
                .is_some_and(|fired| fired.original_matches(token))
        } else {
            state.target == Some(token) && state.next_pending
        };
        if !matched {
            state.invalid = true;
            return;
        }
        let Some(case) = state.case else {
            state.invalid = true;
            return;
        };
        // OverlapCompletion is dropped after the original TimerWait field.
        // A missing or duplicate record cannot qualify the owner.
        let _ = writeln!(
            std::io::stderr().lock(),
            "{DROP_PREFIX}|{}|{}",
            case.activation(),
            u8::from(returned)
        );
    }

    fn barrier_state(
        &self,
        token: RuntimeToken,
        stop: &crate::containment::StopControl,
    ) -> Option<bool> {
        let mut state = self.inner.state.lock().ok()?;
        if state.target != Some(token) || state.invalid {
            return None;
        }
        if state.markers[1].parked && state.case.is_some_and(Case::hold_for_root_stop) {
            if !state.ready_before_stop {
                if stop.observe().is_some() {
                    state.invalid = true;
                    return None;
                }
                state.ready_before_stop = true;
            }
            // Preserve the original owner until the actual root stop wins.
            return Some(false);
        }
        Some(state.markers[1].parked)
    }

    pub(crate) async fn wait_for_second_park(
        &self,
        token: RuntimeToken,
        provider: &dyn PreparationReadWait,
        budget: &ActivationBudget,
        deadline: Instant,
        stop: &crate::containment::StopControl,
    ) {
        if self.barrier_state(token, stop) != Some(false) {
            return;
        }
        let now = provider.now();
        let cap = now
            .checked_add(BARRIER_LIMIT)
            .unwrap_or(deadline)
            .min(deadline);
        loop {
            // Keep the real timer wait and its original stop owner. No Store
            // borrow is held here. In particular, a dropped Store or cancelled
            // activation must not wait for the full diagnostic timeout.
            if stop.observe().is_some() {
                self.apply(|state| {
                    if !state.case.is_some_and(Case::hold_for_root_stop) || !state.ready_before_stop
                    {
                        state.invalid = true;
                    }
                });
                return;
            }
            if self.barrier_state(token, stop) != Some(false) {
                return;
            }
            let now = provider.now();
            if now >= cap {
                self.apply(|state| state.timeout = true);
                return;
            }
            let next = now.checked_add(STOP_OBSERVATION).unwrap_or(cap).min(cap);
            let Ok(mut timeout) = provider.wait_until_owned(next, budget) else {
                self.apply(|state| state.invalid = true);
                return;
            };
            let notified = self.inner.parked.notified();
            if self.barrier_state(token, stop) != Some(false) {
                return;
            }
            tokio::select! {
                () = notified => {},
                () = &mut timeout => {},
            }
        }
    }

    pub(crate) fn report(&self) {
        let Ok(state) = self.inner.state.lock() else {
            return;
        };
        let Some(case) = state.case else {
            return;
        };
        let snapshot = state.snapshot();
        let bytes = self
            .billing
            .0
            .as_ref()
            .map_or(0, |charge| charge.allocation.bytes());
        if case.returned() {
            let _ = writeln!(
                std::io::stderr().lock(),
                "LSF-GO-TIMER-RETURNED-V1|{}|{}|{}|{}|{}",
                case.activation(),
                u8::from(state.returned_complete()),
                u8::from(state.invalid),
                u8::from(state.timeout),
                bytes
            );
            return;
        }
        if case.fired() {
            let complete = !state.invalid
                && !state.timeout
                && state.fired.as_ref().is_some_and(FiredWitness::complete);
            let _ = writeln!(
                std::io::stderr().lock(),
                "LSF-GO-TIMER-FIRED-V1|{}|{}|{}|{}|{}",
                case.activation(),
                u8::from(complete),
                u8::from(state.invalid),
                u8::from(state.timeout),
                bytes
            );
            return;
        }
        // Fixed fields and labels only. A failed write produces no evidence.
        let _ = writeln!(
            std::io::stderr().lock(),
            "{PREFIX}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
            case.activation(),
            u8::from(snapshot.complete),
            u8::from(snapshot.invalid),
            u8::from(snapshot.timeout),
            snapshot.tasks,
            u8::from(snapshot.next_seen),
            u8::from(snapshot.next_pending),
            u8::from(snapshot.target_stopped),
            u8::from(snapshot.first_parked),
            u8::from(snapshot.gc_marker_stopped),
            u8::from(snapshot.handshake_confirmed),
            u8::from(snapshot.second_parked),
            u8::from(snapshot.ready_before_stop),
            u8::from(snapshot.next_finished),
            bytes
        );
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use latent_core::{BudgetProfile, ClockSample, EffectiveActivationBudget, ResourceBudget};
    use latent_executor::OwnedPreparationWait;
    use std::{
        alloc::{GlobalAlloc, System},
        cell::Cell,
        future::Future,
        task::{Context, Waker},
    };

    // Test-controller bookkeeping only: an immutable allocator delegates to
    // System, while each test thread tracks just its two exact Arc pointers.
    // It is not part of the activation witness or any non-test binary.
    struct WatchingAllocator;
    #[derive(Clone, Copy, Default)]
    struct Watch {
        payload: usize,
        billing: usize,
        payload_freed: bool,
        billing_freed: bool,
        before_refund: bool,
    }
    thread_local! {
        static WATCH: Cell<Watch> = const { Cell::new(Watch {
            payload: 0, billing: 0, payload_freed: false,
            billing_freed: false, before_refund: false,
        }) };
    }
    #[global_allocator]
    static ALLOCATOR: WatchingAllocator = WatchingAllocator;
    // SAFETY: allocation and deallocation are delegated with the unchanged
    // pointer/layout to System. The observer stores integer addresses only;
    // it never dereferences or changes the allocator's storage.
    #[allow(unsafe_code, reason = "test-only exact allocator-release observation")]
    unsafe impl GlobalAlloc for WatchingAllocator {
        unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
            unsafe { System.alloc(layout) }
        }
        unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
            unsafe { System.dealloc(pointer, layout) };
            let _ = WATCH.try_with(|cell| {
                let mut watch = cell.get();
                if pointer as usize == watch.payload {
                    watch.payload_freed = true;
                }
                if pointer as usize == watch.billing {
                    watch.billing_freed = true;
                }
                cell.set(watch);
            });
        }
    }
    pub(super) fn record_before_refund() {
        let _ = WATCH.try_with(|cell| {
            let mut watch = cell.get();
            if watch.payload != 0 && watch.billing != 0 {
                watch.before_refund = watch.payload_freed && watch.billing_freed;
            }
            cell.set(watch);
        });
    }

    fn budget(memory: u64) -> ActivationBudget {
        let limits = ResourceBudget {
            cpu_fuel: 1_000_000_000,
            memory_bytes: memory,
            wall_time_limit_millis: Some(5000),
            child_calls: 0,
            outbound_requests: 0,
            state_read_bytes: 0,
            state_write_bytes: 0,
            blob_read_bytes: 0,
            blob_write_bytes: 0,
            log_bytes: 0,
            effect_count: 0,
        };
        let grant = EffectiveActivationBudget::admit_profile_at(
            BudgetProfile::Phase3,
            &limits,
            &limits,
            &limits,
            None,
            ClockSample::system_now(),
        )
        .unwrap();
        ActivationBudget::with_profile(grant, BudgetProfile::Phase3).unwrap()
    }

    struct TestWait;
    impl PreparationReadWait for TestWait {
        fn now(&self) -> Instant {
            tokio::time::Instant::now().into_std()
        }
        fn wait_until(&self, deadline: Instant) -> latent_core::BoxFuture<'_, ()> {
            Box::pin(tokio::time::sleep_until(deadline.into()))
        }
        fn wait_until_owned<'a>(
            &'a self,
            deadline: Instant,
            budget: &ActivationBudget,
        ) -> Result<OwnedPreparationWait<'a>, PlatformError> {
            OwnedPreparationWait::try_boxed(budget, || tokio::time::sleep_until(deadline.into()))
        }
    }

    fn token(id: u64) -> RuntimeToken {
        RuntimeToken { generation: 1, id }
    }

    fn returned_before_event(case: Case) -> State {
        let mut state = State {
            case: Some(case),
            ..State::new()
        };
        state.task(OwnerKind::Task, token(1), None);
        state.timer_start(token(10), Some(token(1)), Some(251_000_000));
        assert!(state.next(token(10), 1));
        state.next_pending(token(10));
        state.next_finished(token(10));
        state
    }

    fn returned_before_drop(case: Case) -> State {
        let mut state = returned_before_event(case);
        state.returned_probe(0, 1); // matching successful returned event
        state.timer_stop(token(10), 0);
        state.returned_probe(0, 0); // same-token public fence
        state.park(token(1), 0);
        state.returned_probe(0, 0); // exact wait.done channel identity
        state
    }

    #[test]
    fn returned_timer_requires_same_token_fence_park_drop_and_public_return() {
        for case in [Case::ReturnedStop, Case::ReturnedReset] {
            let mut state = returned_before_drop(case);
            assert!(!state.returned_complete());
            state.returned_probe(0, 0); // after canonical subtask drop
            state.wake(token(1));
            if case == Case::ReturnedReset {
                state.timer_start(token(11), Some(token(1)), Some(3_600_000_000_000));
                state.timer_stop(token(11), 0);
            }
            state.timer_start(token(12), Some(token(1)), None);
            state.timer_stop(token(12), 0);
            assert!(state.returned_complete(), "{case:?}: {state:?}");
        }
    }

    #[test]
    fn returned_timer_rejects_early_stop_missing_or_foreign_edges() {
        let mut stopped = returned_before_event(Case::ReturnedStop);
        stopped.timer_stop(token(10), 0);
        assert!(!stopped.returned_complete());
        assert!(stopped.invalid);

        let mut foreign = returned_before_event(Case::ReturnedStop);
        foreign.returned_probe(0, 1);
        foreign.timer_stop(
            RuntimeToken {
                generation: 2,
                id: 10,
            },
            0,
        );
        assert!(!foreign.returned_complete());
        assert!(foreign.invalid);

        let mut no_park = returned_before_event(Case::ReturnedStop);
        no_park.returned_probe(0, 1);
        no_park.timer_stop(token(10), 0);
        no_park.returned_probe(0, 0);
        no_park.returned_probe(0, 0);
        assert!(!no_park.returned_complete());
        assert!(no_park.invalid);

        let mut no_channel = returned_before_event(Case::ReturnedReset);
        no_channel.returned_probe(0, 1);
        no_channel.timer_stop(token(10), 0);
        no_channel.returned_probe(0, 0);
        no_channel.park(token(1), 0);
        no_channel.wake(token(1));
        assert!(!no_channel.returned_complete());
        assert!(no_channel.invalid);

        let mut early_replacement = returned_before_drop(Case::ReturnedReset);
        early_replacement.timer_start(token(11), Some(token(1)), Some(3_600_000_000_000));
        assert!(!early_replacement.returned_complete());
        assert!(early_replacement.invalid);
    }

    fn before_second_park() -> State {
        let mut state = State {
            case: Some(Case::ResetReset),
            ..State::new()
        };
        state.task(OwnerKind::Task, token(1), None);
        state.timer_start(token(10), Some(token(1)), None);
        state.task(OwnerKind::Task, token(2), Some(token(1)));
        state.next(token(10), 1);
        state.next_pending(token(10));
        state.task(OwnerKind::Task, token(3), Some(token(1)));
        state.timer_start(token(11), Some(token(3)), None);
        state.timer_stop(token(11), 1);
        state.timer_stop(token(10), 1);
        assert!(!state.park(token(3), 1));
        state.task(OwnerKind::Task, token(4), Some(token(1)));
        state.timer_start(token(12), Some(token(4)), None);
        state.timer_stop(token(12), 1);
        state
    }

    #[test]
    fn only_exact_original_next_stop_and_distinct_task_parks_complete() {
        let mut state = before_second_park();
        assert!(!state.snapshot().complete);
        assert!(state.park(token(4), 1));
        state.next_finished(token(10));
        assert_eq!(
            state.snapshot(),
            Snapshot {
                complete: true,
                invalid: false,
                timeout: false,
                tasks: 4,
                next_seen: true,
                next_pending: true,
                target_stopped: true,
                first_parked: true,
                gc_marker_stopped: false,
                handshake_confirmed: false,
                ready_before_stop: false,
                second_parked: true,
                next_finished: true,
            }
        );
    }

    #[test]
    fn gc_cases_use_the_same_live_original_wait_and_ordered_parks() {
        for case in [Case::GcResetReset, Case::GcResetStop] {
            assert_eq!(Observer::select(case.activation()), Some(case));
            let mut state = before_second_park();
            state.case = Some(case);
            assert!(state.next_live && state.next_pending && state.markers[0].parked);
            // GC itself can park the second worker. It must not count as
            // the later timer-operation park or release the provider wait.
            assert!(!state.park(token(4), 1));
            assert!(!state.invalid && !state.snapshot().second_parked);
            state.wake(token(4));
            state.timer_start(token(13), Some(token(4)), Some(GC_MARKER_PERIOD_NANOS));
            state.timer_stop(token(13), 1);
            // The GC marker's Stop can itself fence an unpublished wait.
            // Its park and wake cannot be mistaken for the handshake.
            assert!(!state.park(token(4), 1));
            state.wake(token(4));
            assert!(!state.park(token(4), 1));
            state.timer_start(token(14), Some(token(1)), Some(ROOT_MARKER_PERIOD_NANOS));
            assert!(state.snapshot().handshake_confirmed);
            state.wake(token(4));
            assert!(state.park(token(4), 1));
            state.next_finished(token(10));
            assert!(state.snapshot().complete);
            assert!(state.snapshot().gc_marker_stopped);

            // If the root marker arrives before the worker has actually
            // parked on the release channel, fail closed. A later handshake
            // park must never be reinterpreted as the timer operation.
            let mut root_too_early = before_second_park();
            root_too_early.case = Some(case);
            root_too_early.timer_start(token(13), Some(token(4)), Some(GC_MARKER_PERIOD_NANOS));
            root_too_early.timer_stop(token(13), 1);
            assert!(!root_too_early.park(token(4), 1));
            root_too_early.wake(token(4));
            root_too_early.timer_start(token(14), Some(token(1)), Some(ROOT_MARKER_PERIOD_NANOS));
            assert!(root_too_early.invalid);

            let mut missing = before_second_park();
            missing.case = Some(case);
            assert!(!missing.park(token(4), 1));
            missing.next_finished(token(10));
            assert!(!missing.snapshot().complete && missing.invalid);

            let mut wrong_marker = before_second_park();
            wrong_marker.case = Some(case);
            wrong_marker.timer_start(token(13), Some(token(4)), None);
            assert!(wrong_marker.invalid);

            // An admitted provider wait on the post-GC marker is not the
            // original wait and makes the witness invalid, even if it parks.
            let mut marker_wait = before_second_park();
            marker_wait.case = Some(case);
            marker_wait.timer_start(token(13), Some(token(4)), Some(GC_MARKER_PERIOD_NANOS));
            assert!(!marker_wait.next(token(13), 2));
            assert!(marker_wait.invalid);

            let mut early = before_second_park();
            early.case = Some(case);
            early.markers[0].parked = false;
            early.markers[1] = Marker::default();
            early.timer_start(token(12), Some(token(4)), None);
            assert!(early.invalid);
        }
    }

    #[test]
    fn wrong_token_order_extra_task_and_early_completion_fail_closed() {
        let mut wrong_next = State {
            case: Some(Case::ResetReset),
            ..State::new()
        };
        wrong_next.task(OwnerKind::Task, token(1), None);
        wrong_next.timer_start(token(10), Some(token(1)), None);
        wrong_next.next(token(99), 1);
        assert!(wrong_next.invalid);

        let mut wrong_park = before_second_park();
        assert!(!wrong_park.park(token(99), 1));
        wrong_park.next_finished(token(10));
        assert!(!wrong_park.snapshot().complete);
        assert!(wrong_park.invalid);

        let mut wrong_marker = before_second_park();
        wrong_marker.timer_stop(token(99), 1);
        assert!(wrong_marker.invalid);

        let mut extra = before_second_park();
        extra.task(OwnerKind::Task, token(5), Some(token(1)));
        assert!(extra.invalid);

        let mut no_wait = before_second_park();
        assert!(!no_wait.park(token(4), 0));
        assert!(no_wait.invalid);

        let mut no_pending = before_second_park();
        no_pending.next_pending = false;
        assert!(!no_pending.park(token(4), 1));
        assert!(no_pending.invalid);
    }

    #[test]
    fn timeout_or_missing_physical_next_never_qualifies() {
        let mut state = before_second_park();
        state.timeout = true;
        assert!(state.park(token(4), 1));
        state.next_finished(token(10));
        assert!(!state.snapshot().complete);
        assert!(state.snapshot().timeout);
    }

    #[test]
    fn original_budget_precedes_both_allocations_and_last_clone_refunds_physically_first() {
        let payload = arc_bytes::<Inner>().unwrap();
        let charge = arc_bytes::<Charge>().unwrap();
        let bytes = u64::try_from(payload + charge).unwrap();
        let denied = budget(bytes - 1);
        assert!(Observer::new(Case::ResetReset, &denied).is_err());
        assert_eq!(denied.host_memory_bytes(), 0);
        assert_eq!(denied.outstanding_reservations(), 0);
        let budget = budget(bytes);
        let observer = Observer::new(Case::ResetReset, &budget).unwrap();
        assert_eq!(budget.host_memory_bytes(), bytes);
        let inner_offset = Layout::new::<[AtomicUsize; 2]>()
            .extend(Layout::new::<Inner>())
            .unwrap()
            .1;
        let charge_offset = Layout::new::<[AtomicUsize; 2]>()
            .extend(Layout::new::<Charge>())
            .unwrap()
            .1;
        let payload_address = Arc::as_ptr(&observer.inner) as usize - inner_offset;
        let billing_address =
            Arc::as_ptr(observer.billing.0.as_ref().unwrap()) as usize - charge_offset;
        WATCH.with(|watch| {
            watch.set(Watch {
                payload: payload_address,
                billing: billing_address,
                ..Watch::default()
            })
        });
        let last = observer.clone();
        drop(observer);
        assert_eq!(budget.host_memory_bytes(), bytes);
        assert!(!WATCH.with(|watch| watch.get().payload_freed));
        drop(last);
        let observed = WATCH.with(|watch| {
            let value = watch.get();
            watch.set(Watch::default());
            value
        });
        assert!(observed.payload_freed && observed.billing_freed && observed.before_refund);
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
        println!("witness model: payload={payload}, billing={charge}, total={bytes} bytes");
    }

    #[test]
    fn separate_activations_and_token_generations_never_share_observations() {
        let one_budget = budget(8192);
        let two_budget = budget(8192);
        let one = Observer::new(Case::ResetReset, &one_budget).unwrap();
        let two = Observer::new(Case::ResetReset, &two_budget).unwrap();
        one.apply(|state| *state = before_second_park());
        assert_eq!(two.inner.state.lock().unwrap().snapshot().tasks, 0);
        one.park(
            RuntimeToken {
                generation: 2,
                id: 4,
            },
            1,
        );
        assert!(one.inner.state.lock().unwrap().snapshot().invalid);
        assert!(!two.inner.state.lock().unwrap().snapshot().invalid);
        drop(one);
        assert_eq!(one_budget.host_memory_bytes(), 0);
        assert!(two_budget.host_memory_bytes() > 0);
        drop(two);
        assert_eq!(two_budget.host_memory_bytes(), 0);
    }

    #[tokio::test(start_paused = true)]
    async fn timeout_and_stop_release_the_owned_provider_wait_without_a_synthetic_result() {
        for cancelled in [false, true] {
            let budget = budget(8192);
            let observer = Observer::new(Case::ResetReset, &budget).unwrap();
            observer.apply(|state| *state = before_second_park());
            let witness_bytes = budget.host_memory_bytes();
            let stop = crate::containment::StopControl::new(None, None);
            let provider = TestWait;
            let deadline = provider.now() + Duration::from_secs(5);
            let mut barrier = Box::pin(observer.wait_for_second_park(
                token(10),
                &provider,
                &budget,
                deadline,
                &stop,
            ));
            let mut context = Context::from_waker(Waker::noop());
            assert!(barrier.as_mut().poll(&mut context).is_pending());
            assert!(budget.host_memory_bytes() > witness_bytes);
            if cancelled {
                stop.cancel_for_revocation();
            }
            tokio::time::advance(if cancelled {
                STOP_OBSERVATION
            } else {
                BARRIER_LIMIT
            })
            .await;
            barrier.await;
            assert_eq!(budget.host_memory_bytes(), witness_bytes);
            let snapshot = observer.inner.state.lock().unwrap().snapshot();
            assert!(!snapshot.complete);
            assert_eq!(snapshot.invalid, cancelled);
            assert_eq!(snapshot.timeout, !cancelled);
            drop(observer);
            assert_eq!(budget.host_memory_bytes(), 0);
            assert_eq!(budget.outstanding_reservations(), 0);
        }
    }

    #[tokio::test(start_paused = true)]
    async fn root_stop_cases_hold_both_parked_tasks_until_the_original_stop() {
        for case in [Case::CancelResetReset, Case::DeadlineResetStop] {
            assert_eq!(Observer::select(case.activation()), Some(case));
            let budget = budget(8192);
            let observer = Observer::new(case, &budget).unwrap();
            observer.apply(|state| {
                *state = before_second_park();
                state.case = Some(case);
                assert!(state.park(token(4), 1));
            });
            let stop = crate::containment::StopControl::new(None, None);
            let provider = TestWait;
            let deadline = provider.now() + Duration::from_secs(5);
            let mut barrier = Box::pin(observer.wait_for_second_park(
                token(10),
                &provider,
                &budget,
                deadline,
                &stop,
            ));
            let mut context = Context::from_waker(Waker::noop());
            assert!(barrier.as_mut().poll(&mut context).is_pending());
            let before = observer.inner.state.lock().unwrap().snapshot();
            assert!(before.ready_before_stop && before.second_parked && !before.invalid);
            stop.cancel_for_revocation();
            tokio::time::advance(STOP_OBSERVATION).await;
            barrier.await;
            assert!(observer.inner.state.lock().unwrap().snapshot().complete);

            let early = Observer::new(case, &budget).unwrap();
            early.apply(|state| {
                *state = before_second_park();
                state.case = Some(case);
            });
            early
                .wait_for_second_park(token(10), &provider, &budget, deadline, &stop)
                .await;
            let snapshot = early.inner.state.lock().unwrap().snapshot();
            assert!(snapshot.invalid && !snapshot.ready_before_stop && !snapshot.complete);
        }
    }

    #[tokio::test(start_paused = true)]
    async fn dropped_store_keeps_original_charge_until_the_pending_wait_is_cancelled() {
        let budget = budget(8192);
        let observer = Observer::new(Case::ResetReset, &budget).unwrap();
        observer.apply(|state| *state = before_second_park());
        let witness_bytes = budget.host_memory_bytes();
        let store = wasmtime::Store::new(&wasmtime::Engine::default(), observer);
        let detached = store.data().clone();
        let wait_budget = budget.clone();
        let waiter = tokio::spawn(async move {
            let provider = TestWait;
            let stop = crate::containment::StopControl::new(None, None);
            let deadline = provider.now() + Duration::from_secs(5);
            detached
                .wait_for_second_park(token(10), &provider, &wait_budget, deadline, &stop)
                .await;
        });
        tokio::task::yield_now().await;
        assert!(budget.host_memory_bytes() > witness_bytes);
        drop(store);
        assert!(budget.host_memory_bytes() > witness_bytes);
        waiter.abort();
        assert!(waiter.await.unwrap_err().is_cancelled());
        assert_eq!(budget.host_memory_bytes(), 0);
        assert_eq!(budget.outstanding_reservations(), 0);
    }
}

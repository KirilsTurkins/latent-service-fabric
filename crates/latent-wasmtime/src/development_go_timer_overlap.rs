//! Closed, activation-owned witness for the signed Go timer overlap fixture.
//!
//! Fixed-capacity state holds at most four Task tokens and three timer tokens.
//! Both Arc backings are prepaid on the original activation, and their charge
//! survives every detached wait clone. The optional barrier uses an already
//! budget-owned provider wait as its finite timeout and invents no result.
use std::{
    alloc::Layout,
    io::Write,
    sync::{atomic::AtomicUsize, Arc, Mutex},
    time::{Duration, Instant},
};

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
const PREFIX: &str = "LSF-GO-TIMER-OVERLAP-V1";

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum Case {
    ResetReset,
    ResetStop,
    GcResetReset,
    GcResetStop,
}

impl Case {
    #[must_use]
    pub(crate) const fn activation(self) -> &'static str {
        match self {
            Self::ResetReset => "go-timer-overlap-reset-reset",
            Self::ResetStop => "go-timer-overlap-reset-stop",
            Self::GcResetReset => "go-timer-overlap-gc-reset-reset",
            Self::GcResetStop => "go-timer-overlap-gc-reset-stop",
        }
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
}

impl State {
    const fn new() -> Self {
        Self {
            case: None,
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
        }
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

    fn timer_start(&mut self, token: RuntimeToken, parent: Option<RuntimeToken>) {
        if self.markers[1].parked {
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
        if Some(token) != self.target || !self.next_live || self.target_stopped || self.next_pending
        {
            self.invalid = true;
            return;
        }
        self.next_pending = true;
    }

    fn timer_stop(&mut self, token: RuntimeToken, waits: u32) {
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
        } else {
            self.invalid = true;
        }
    }

    fn park(&mut self, task: RuntimeToken, waits: u32) -> bool {
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

    fn next_finished(&mut self, token: RuntimeToken) {
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
                && self.next_finished
                && self.target_stopped
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
    pub(crate) fn timer_start(&self, token: RuntimeToken, parent: Option<RuntimeToken>) {
        self.apply(|state| state.timer_start(token, parent));
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
    pub(crate) fn next_finished(&self, token: RuntimeToken) {
        self.apply(|state| state.next_finished(token));
    }

    fn barrier_state(&self, token: RuntimeToken) -> Option<bool> {
        let state = self.inner.state.lock().ok()?;
        if state.target != Some(token) || state.invalid {
            return None;
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
        if self.barrier_state(token) != Some(false) {
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
                self.apply(|state| state.invalid = true);
                return;
            }
            if self.barrier_state(token) != Some(false) {
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
            if self.barrier_state(token) != Some(false) {
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
        // Fixed fields and labels only. A failed write produces no evidence.
        let _ = writeln!(
            std::io::stderr().lock(),
            "{PREFIX}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}|{}",
            case.activation(),
            u8::from(snapshot.complete),
            u8::from(snapshot.invalid),
            u8::from(snapshot.timeout),
            snapshot.tasks,
            u8::from(snapshot.next_seen),
            u8::from(snapshot.next_pending),
            u8::from(snapshot.target_stopped),
            u8::from(snapshot.first_parked),
            u8::from(snapshot.second_parked),
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

    fn before_second_park() -> State {
        let mut state = State {
            case: Some(Case::ResetReset),
            ..State::new()
        };
        state.task(OwnerKind::Task, token(1), None);
        state.timer_start(token(10), Some(token(1)));
        state.task(OwnerKind::Task, token(2), Some(token(1)));
        state.next(token(10), 1);
        state.next_pending(token(10));
        state.task(OwnerKind::Task, token(3), Some(token(1)));
        state.timer_start(token(11), Some(token(3)));
        state.timer_stop(token(11), 1);
        state.timer_stop(token(10), 1);
        assert!(!state.park(token(3), 1));
        state.task(OwnerKind::Task, token(4), Some(token(1)));
        state.timer_start(token(12), Some(token(4)));
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
            assert!(state.park(token(4), 1));
            state.next_finished(token(10));
            assert!(state.snapshot().complete);

            let mut early = before_second_park();
            early.case = Some(case);
            early.markers[0].parked = false;
            early.markers[1] = Marker::default();
            early.timer_start(token(12), Some(token(4)));
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
        wrong_next.timer_start(token(10), Some(token(1)));
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

//! Original activation memory capacity retained with actual host values.
use latent_core::{ActivationBudget, BudgetProfile, HostMemoryReservation, PlatformError};
use std::sync::{Arc, Mutex};
use wasmtime::component::{DynamicValueMemory, Val};

use super::{failure, limit};

/// Wasmtime's typed carrier preserves the domain error's complete budget metadata.
#[derive(Debug)]
pub(crate) struct LiftMemoryError(pub(crate) PlatformError);
impl std::fmt::Display for LiftMemoryError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        formatter.write_str(&self.0.message)
    }
}
impl std::error::Error for LiftMemoryError {}

// As in the existing conservative codec node charge, include finite native
// allocation bookkeeping. These are capacity bounds, not RSS measurements.
const ALLOCATION_METADATA: usize = 64;

#[derive(Default)]
pub(super) struct Escrow {
    budget: Option<ActivationBudget>,
    reservation: Option<HostMemoryReservation>,
    conservative_on_drop: bool,
}
impl Escrow {
    pub(super) fn new(budget: Option<&ActivationBudget>) -> Self {
        Self {
            // Explicit legacy Phase1 callers retain their original behavior.
            // Admitted Phase3/4 execution always uses the supplied original.
            budget: budget
                .filter(|b| matches!(b.profile(), BudgetProfile::Phase3 | BudgetProfile::Phase4))
                .cloned(),
            reservation: None,
            conservative_on_drop: false,
        }
    }
    pub(super) fn add(&mut self, bytes: usize) -> Result<(), PlatformError> {
        let Some(budget) = &self.budget else {
            return Ok(());
        };
        let bytes = u64::try_from(bytes).map_err(|_| limit())?;
        if bytes == 0 {
            return Ok(());
        }
        match &mut self.reservation {
            Some(memory) => memory.grow(bytes),
            None => budget.reserve_host_memory(bytes).map(|memory| {
                self.reservation = Some(memory);
            }),
        }
        .map_err(|error| error.to_platform_error())
    }
    pub(super) fn active(&self) -> bool {
        self.reservation.is_some()
    }
    pub(super) fn confirm(&mut self) {
        if let Some(memory) = &mut self.reservation {
            memory.confirm();
        }
    }
    pub(super) fn shrink(&mut self, bytes: usize) -> Result<(), PlatformError> {
        if let Some(memory) = &mut self.reservation {
            let bytes = u64::try_from(bytes).map_err(|_| limit())?;
            if bytes > memory.bytes() {
                return Err(failure(
                    latent_core::PlatformErrorCode::Internal,
                    "host-codec-capacity-proof",
                ));
            }
            memory.shrink(bytes);
        }
        Ok(())
    }
    pub(super) fn confirm_retained(&mut self, bytes: usize) -> Result<(), PlatformError> {
        if let Some(memory) = &mut self.reservation {
            let bytes = u64::try_from(bytes).map_err(|_| limit())?;
            if bytes > memory.bytes() {
                return Err(failure(
                    latent_core::PlatformErrorCode::Internal,
                    "host-codec-capacity-proof",
                ));
            }
            memory.confirm_bytes(bytes);
        }
        self.shrink(bytes)
    }
    pub(super) fn take(mut self) -> Option<HostMemoryReservation> {
        self.conservative_on_drop = false;
        self.reservation.take()
    }
}
impl Drop for Escrow {
    fn drop(&mut self) {
        // An abandoned/failed native lift may have allocated unpublished trees.
        // Its future has physically unwound before this original owner drops.
        // Preserve the prepaid upper bound as conservative peak attribution;
        // it is not an exact observation of those opaque temporary allocations.
        if self.conservative_on_drop {
            self.confirm();
        }
    }
}

pub(crate) struct OwnedValues {
    // Actual values are destroyed before the reservation, on every return path.
    pub(super) values: Vec<Val>,
    memory: Escrow,
    lift_memory: Option<Arc<LiftMemory>>,
}
impl OwnedValues {
    pub(super) fn finish(values: Vec<Val>, memory: Escrow) -> Result<Self, PlatformError> {
        let mut owner = Self {
            values,
            memory,
            lift_memory: None,
        };
        owner.memory.confirm();
        owner.tighten()?;
        Ok(owner)
    }
    pub(crate) fn output(
        count: usize,
        bytes: usize,
        budget: &ActivationBudget,
    ) -> Result<Self, PlatformError> {
        let mut memory = Escrow::new(Some(budget));
        memory.add(bytes)?; // before even the output slot vector allocation
        let mut values = Vec::new();
        values.try_reserve_exact(count).map_err(|_| limit())?;
        values.resize(count, Val::Bool(false));
        // Only the slot vector exists yet. Future lifting capacity remains
        // pending; it is not misreported as a large tiny-response allocation.
        if let Some(reservation) = &mut memory.reservation {
            let retained = u64::try_from(retained_values(&values, 0)?).map_err(|_| limit())?;
            if retained > reservation.bytes() {
                return Err(failure(
                    latent_core::PlatformErrorCode::Internal,
                    "host-codec-capacity-proof",
                ));
            }
            reservation.confirm_bytes(retained);
        }
        Ok(Self {
            values,
            memory,
            lift_memory: None,
        })
    }
    /// Original slots plus actual native lifting allocations; no signature maximum escrow.
    pub(crate) fn output_accounted(
        count: usize,
        budget: &ActivationBudget,
    ) -> Result<Self, PlatformError> {
        let mut owner = Self::output(count, allocation(count, size_of::<Val>())?, budget)?;
        owner.lift_memory = Some(LiftMemory::new(budget)?);
        Ok(owner)
    }
    pub(crate) fn lift_memory(&self) -> Option<Arc<dyn DynamicValueMemory>> {
        self.lift_memory
            .as_ref()
            .map(|memory| Arc::clone(memory) as Arc<dyn DynamicValueMemory>)
    }
    #[cfg(feature = "development-test-host")]
    pub(crate) fn attach_development_task_return(
        &self,
        shared: Arc<crate::backend::SharedRuntime>,
        slot: usize,
        session: Option<latent_capabilities::broker::CapabilitySessionObserver>,
    ) {
        let Some(memory) = &self.lift_memory else {
            return;
        };
        let Some(session) = session else {
            shared.reject_development_task_return(
                slot,
                crate::DevelopmentJoinRejectReason::SessionUnavailable,
            );
            return;
        };
        let Ok(mut sink) = memory.task_return.lock() else {
            return;
        };
        if sink.is_some() {
            shared.reject_development_task_return(
                slot,
                crate::DevelopmentJoinRejectReason::DuplicateCapture,
            );
            return;
        }
        *sink = Some(TaskReturnSink {
            shared,
            slot,
            session,
            managed_stage: None,
        });
        memory
            .task_return_enabled
            .store(true, std::sync::atomic::Ordering::Release);
    }
    #[cfg(feature = "development-test-host")]
    pub(crate) fn development_host_admission_scope(&self) -> Option<Arc<LiftMemory>> {
        self.lift_memory
            .as_ref()
            .filter(|memory| {
                memory
                    .task_return_enabled
                    .load(std::sync::atomic::Ordering::Acquire)
                    || memory
                        .managed_stage_enabled
                        .load(std::sync::atomic::Ordering::Acquire)
            })
            .map(Arc::clone)
    }
    #[cfg(feature = "development-test-host")]
    pub(crate) fn attach_development_managed_stage(
        &self,
        shared: Arc<crate::backend::SharedRuntime>,
        slot: usize,
        session: Option<latent_capabilities::broker::CapabilitySessionObserver>,
    ) {
        let (Some(memory), Some(session)) = (&self.lift_memory, session) else {
            return;
        };
        let Ok(mut sink) = memory.task_return.lock() else {
            return;
        };
        if sink.is_some() || session.is_closed() || !shared.development_managed_stage_live(slot) {
            return;
        }
        *sink = Some(TaskReturnSink {
            shared,
            slot,
            session,
            managed_stage: Some(ManagedStageState::default()),
        });
        memory
            .managed_stage_enabled
            .store(true, std::sync::atomic::Ordering::Release);
    }
    #[cfg(feature = "development-test-host")]
    pub(crate) fn finish_development_managed_stage(&self) {
        if let Some(memory) = &self.lift_memory {
            memory.finish_managed_stage();
        }
    }
    pub(crate) fn begin_lift(&mut self) {
        self.memory.conservative_on_drop = self.lift_memory.is_none();
    }
    pub(crate) fn finish_lift(&mut self, succeeded: bool) -> Result<(), PlatformError> {
        if self.lift_memory.is_some() {
            return Ok(());
        }
        if !succeeded {
            self.memory.confirm();
        }
        self.tighten()?;
        self.memory.conservative_on_drop = false;
        Ok(())
    }
    pub(crate) fn tighten(&mut self) -> Result<(), PlatformError> {
        if self.lift_memory.is_some() {
            return Ok(());
        }
        if self.memory.active() {
            self.memory
                .confirm_retained(retained_values(&self.values, 0)?)?;
        }
        Ok(())
    }
    pub(crate) fn as_slice(&self) -> &[Val] {
        &self.values
    }
    pub(crate) fn as_mut_slice(&mut self) -> &mut [Val] {
        &mut self.values
    }
}
fn allocation(capacity: usize, item: usize) -> Result<usize, PlatformError> {
    capacity
        .checked_mul(item)
        .and_then(|n| {
            n.checked_add(if capacity == 0 {
                0
            } else {
                ALLOCATION_METADATA
            })
        })
        .ok_or_else(limit)
}
fn add(total: &mut usize, bytes: usize) -> Result<(), PlatformError> {
    *total = total.checked_add(bytes).ok_or_else(limit)?;
    Ok(())
}
fn text(value: &String) -> Result<usize, PlatformError> {
    allocation(value.capacity(), 1)
}
fn retained_values(values: &Vec<Val>, depth: usize) -> Result<usize, PlatformError> {
    let mut total = allocation(values.capacity(), size_of::<Val>())?;
    for value in values {
        add(&mut total, retained_value(value, depth)?)?;
    }
    Ok(total)
}
fn retained_value(value: &Val, depth: usize) -> Result<usize, PlatformError> {
    if depth > 64 {
        return Err(limit());
    }
    let mut total = 0;
    match value {
        Val::String(value) | Val::Enum(value) => add(&mut total, text(value)?)?,
        Val::List(values) | Val::Tuple(values) | Val::FixedLengthList(values) => {
            add(&mut total, retained_values(values, depth + 1)?)?
        }
        Val::Record(fields) => {
            add(
                &mut total,
                allocation(fields.capacity(), size_of::<(String, Val)>())?,
            )?;
            for (name, value) in fields {
                add(&mut total, text(name)?)?;
                add(&mut total, retained_value(value, depth + 1)?)?;
            }
        }
        Val::Variant(name, value) => {
            add(&mut total, text(name)?)?;
            add(&mut total, boxed(value.as_deref(), depth)?)?;
        }
        Val::Option(value) => add(&mut total, boxed(value.as_deref(), depth)?)?,
        Val::Result(value) => add(
            &mut total,
            boxed(
                match value {
                    Ok(v) | Err(v) => v.as_deref(),
                },
                depth,
            )?,
        )?,
        Val::Flags(names) => {
            add(
                &mut total,
                allocation(names.capacity(), size_of::<String>())?,
            )?;
            for name in names {
                add(&mut total, text(name)?)?;
            }
        }
        Val::Bool(_)
        | Val::S8(_)
        | Val::U8(_)
        | Val::S16(_)
        | Val::U16(_)
        | Val::S32(_)
        | Val::U32(_)
        | Val::S64(_)
        | Val::U64(_)
        | Val::Float32(_)
        | Val::Float64(_)
        | Val::Char(_) => {}
        // These never pass the existing signature/codec profile. Do not guess
        // at native resource/future ownership to shrink an unexpected result.
        Val::Map(_) | Val::Resource(_) | Val::Future(_) | Val::Stream(_) | Val::ErrorContext(_) => {
            return Err(super::unsupported());
        }
    }
    Ok(total)
}
fn boxed(value: Option<&Val>, depth: usize) -> Result<usize, PlatformError> {
    match value {
        Some(value) => retained_value(value, depth + 1)?
            .checked_add(size_of::<Val>() + ALLOCATION_METADATA)
            .ok_or_else(limit),
        None => Ok(0),
    }
}

// Arc header, Mutex/Escrow/budget and allocation bookkeeping. This owner is
// admitted before Arc::new; it never allocates a collection of reservation guards.
const LIFT_SCOPE_BYTES: usize = 256;
const _: () = assert!(
    size_of::<LiftMemory>() + 2 * size_of::<usize>() + ALLOCATION_METADATA <= LIFT_SCOPE_BYTES
);
#[cfg(feature = "development-test-host")]
const _: () = assert!(size_of::<Option<Arc<LiftMemory>>>() == size_of::<usize>());
#[cfg(feature = "development-test-host")]
struct TaskReturnSink {
    shared: Arc<crate::backend::SharedRuntime>,
    slot: usize,
    session: latent_capabilities::broker::CapabilitySessionObserver,
    managed_stage: Option<ManagedStageState>,
}
#[cfg(feature = "development-test-host")]
#[derive(Default)]
struct ManagedStageState {
    attempts: u8,
    overflow: bool,
    transport_failed: bool,
    inconclusive: bool,
    finished: bool,
}
#[cfg(feature = "development-test-host")]
impl ManagedStageState {
    fn accept(&mut self, stage: u32, guard: u32) -> bool {
        if self.finished || self.overflow || self.inconclusive {
            return false;
        }
        self.attempts = self.attempts.saturating_add(1);
        if self.attempts > 16 {
            self.overflow = true;
            return false;
        }
        let known = (guard == 0 && matches!(stage, 1..=9 | 17..=24))
            || (stage == guard && matches!(guard, 10..=16));
        if !known {
            self.inconclusive = true;
        }
        known
    }
}
pub(crate) struct LiftMemory {
    // These original-call references retire before the original scope refund.
    #[cfg(feature = "development-test-host")]
    task_return: Mutex<Option<TaskReturnSink>>,
    #[cfg(feature = "development-test-host")]
    task_return_enabled: std::sync::atomic::AtomicBool,
    #[cfg(feature = "development-test-host")]
    managed_stage_enabled: std::sync::atomic::AtomicBool,
    memory: Mutex<Escrow>,
    budget: ActivationBudget,
}
impl LiftMemory {
    #[cfg(all(test, feature = "development-test-host"))]
    pub(crate) fn development_stage_counter_control() {
        let mut counter = ManagedStageState::default();
        for _ in 0..16 {
            assert!(counter.accept(2, 0));
        }
        assert_eq!(counter.attempts, 16);
        assert!(!counter.accept(2, 0));
        assert!(counter.overflow);
        for _ in 0..100 {
            assert!(!counter.accept(2, 0));
        }
        assert_eq!(counter.attempts, 17);
        for (stage, guard) in [
            (0, 0),
            (25, 0),
            (1, 10),
            (10, 0),
            (16, 15),
            (u32::MAX, u32::MAX),
        ] {
            let mut counter = ManagedStageState::default();
            assert!(!counter.accept(stage, guard));
            assert!(counter.inconclusive);
            assert!(!counter.accept(1, 0));
        }
        for stage in 10..=16 {
            assert!(ManagedStageState::default().accept(stage, stage));
        }
        for stage in [1, 9, 17, 18, 19, 20, 21, 22, 23, 24] {
            assert!(ManagedStageState::default().accept(stage, 0));
        }
        let mut finished = ManagedStageState {
            finished: true,
            ..Default::default()
        };
        assert!(!finished.accept(1, 0));
        assert_eq!(finished.attempts, 0);
    }
    #[cfg(feature = "development-test-host")]
    pub(crate) fn managed_stage(
        &self,
        actual: &latent_capabilities::broker::CapabilitySession,
        stage: u32,
        guard: u32,
    ) {
        use std::io::Write;
        let Ok(mut holder) = self.task_return.lock() else {
            return;
        };
        let Some(sink) = holder.as_mut() else { return };
        let Some(state) = sink.managed_stage.as_mut() else {
            return;
        };
        if !actual.is_observed_by(&sink.session)
            || sink.session.is_closed()
            || !sink.shared.development_managed_stage_live(sink.slot)
        {
            state.inconclusive = true;
            return;
        }
        let prior_overflow = state.overflow;
        if state.accept(stage, guard) {
            state.transport_failed |=
                writeln!(&mut std::io::stderr().lock(),
                "DOTNET_MANAGED_STAGE {{\"slot\":{},\"sequence\":{},\"stage\":{},\"guard\":{}}}",
                sink.slot, state.attempts, stage, guard)
                .is_err();
        } else if !prior_overflow && state.overflow {
            state.transport_failed |= writeln!(
                &mut std::io::stderr().lock(),
                "DOTNET_MANAGED_STAGE_OVERFLOW {{\"slot\":{}}}",
                sink.slot
            )
            .is_err();
        }
    }
    #[cfg(feature = "development-test-host")]
    fn finish_managed_stage(&self) {
        use std::io::Write;
        let Ok(mut holder) = self.task_return.lock() else {
            return;
        };
        let Some(sink) = holder.as_mut() else { return };
        let Some(state) = sink.managed_stage.as_mut() else {
            return;
        };
        if state.finished {
            return;
        }
        state.finished = true;
        state.inconclusive |=
            sink.session.is_closed() || !sink.shared.development_managed_stage_live(sink.slot);
        // A failed final write is necessarily a missing-summary/inconclusive capture.
        let _ = writeln!(&mut std::io::stderr().lock(),
            "DOTNET_MANAGED_STAGE_SUMMARY {{\"slot\":{},\"attempts\":{},\"overflow\":{},\"transportFailed\":{},\"inconclusive\":{}}}",
            sink.slot, state.attempts, state.overflow, state.transport_failed, state.inconclusive);
        self.managed_stage_enabled
            .store(false, std::sync::atomic::Ordering::Release);
    }
    #[cfg(feature = "development-test-host")]
    pub(crate) fn host_admission_refusal(
        &self,
        actual: &latent_capabilities::broker::CapabilitySession,
        edge: crate::development_trap_observer::DevelopmentHostAdmissionEdge,
        operation: crate::development_trap_observer::DevelopmentHostOperation,
        code: latent_core::PlatformErrorCode,
    ) {
        let Ok(sink) = self.task_return.lock() else {
            return;
        };
        let Some(sink) = &*sink else {
            return;
        };
        if sink.managed_stage.as_ref().is_some_and(|state| {
            state.finished
                || sink.session.is_closed()
                || !self
                    .managed_stage_enabled
                    .load(std::sync::atomic::Ordering::Acquire)
                || !sink.shared.development_managed_stage_live(sink.slot)
        }) {
            return;
        }
        if actual.is_observed_by(&sink.session) {
            sink.shared.capture_development_host_admission_refusal(
                sink.slot,
                edge,
                operation,
                code,
                sink.session.is_closed(),
            );
        }
    }
    #[cfg(feature = "development-test-host")]
    pub(crate) fn managed_stage_host_admission_refusal(
        &self,
        actual: &latent_capabilities::broker::CapabilitySession,
        edge: crate::development_trap_observer::DevelopmentHostAdmissionEdge,
        operation: crate::development_trap_observer::DevelopmentHostOperation,
        code: latent_core::PlatformErrorCode,
    ) {
        if self
            .managed_stage_enabled
            .load(std::sync::atomic::Ordering::Acquire)
        {
            self.host_admission_refusal(actual, edge, operation, code);
        }
    }
    fn new(budget: &ActivationBudget) -> Result<Arc<Self>, PlatformError> {
        let mut memory = Escrow::new(Some(budget));
        memory.add(LIFT_SCOPE_BYTES)?;
        let owner = Arc::new(Self {
            #[cfg(feature = "development-test-host")]
            task_return: Mutex::new(None),
            #[cfg(feature = "development-test-host")]
            task_return_enabled: std::sync::atomic::AtomicBool::new(false),
            #[cfg(feature = "development-test-host")]
            managed_stage_enabled: std::sync::atomic::AtomicBool::new(false),
            memory: Mutex::new(memory),
            budget: budget.clone(),
        });
        owner
            .memory
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .confirm();
        Ok(owner)
    }
}
impl DynamicValueMemory for LiftMemory {
    #[cfg(feature = "development-test-host")]
    fn development_task_return_enabled(&self) -> bool {
        self.task_return_enabled
            .load(std::sync::atomic::Ordering::Acquire)
    }
    #[cfg(feature = "development-test-host")]
    fn development_task_return(&self, event: wasmtime::component::DevelopmentTaskReturnEvent) {
        if !self.development_task_return_enabled() {
            return;
        }
        let Ok(sink) = self.task_return.lock() else {
            return;
        };
        if let Some(sink) = &*sink {
            sink.shared.capture_development_task_return(
                sink.slot,
                !sink.session.is_closed(),
                event,
            );
        }
    }
    fn reserve(&self, bytes: usize) -> wasmtime::Result<()> {
        self.memory
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .add(bytes)
            .map_err(|error| wasmtime::Error::new(LiftMemoryError(error)))
    }
    fn confirm(&self) {
        self.memory
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .confirm();
    }
    fn release(&self, bytes: usize) {
        let mut memory = self
            .memory
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(reservation) = &mut memory.reservation {
            let retained = reservation
                .bytes()
                .checked_sub(bytes as u64)
                .expect("exact native allocation retirement");
            assert!(
                retained >= LIFT_SCOPE_BYTES as u64,
                "scope metadata remains owned"
            );
            reservation.shrink(retained);
        }
    }
    fn fork(&self) -> wasmtime::Result<Arc<dyn DynamicValueMemory>> {
        // A parameter copy gets a new original owner, NEVER the root result sink.
        Self::new(&self.budget)
            .map(|memory| memory as Arc<dyn DynamicValueMemory>)
            .map_err(|error| wasmtime::Error::new(LiftMemoryError(error)))
    }
}

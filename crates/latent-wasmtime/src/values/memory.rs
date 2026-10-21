//! Original activation memory capacity retained with actual host values.
use latent_core::{ActivationBudget, BudgetProfile, HostMemoryReservation, PlatformError};
use std::sync::{Arc, Mutex};
use wasmtime::component::{DynamicValueMemory, Val};

use super::{failure, limit};

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
struct LiftMemory {
    memory: Mutex<Escrow>,
    budget: ActivationBudget,
}
impl LiftMemory {
    fn new(budget: &ActivationBudget) -> Result<Arc<Self>, PlatformError> {
        let mut memory = Escrow::new(Some(budget));
        memory.add(LIFT_SCOPE_BYTES)?;
        let owner = Arc::new(Self {
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
    fn reserve(&self, bytes: usize) -> wasmtime::Result<()> {
        self.memory
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .add(bytes)
            .map_err(wasmtime::Error::new)
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
        Self::new(&self.budget)
            .map(|memory| memory as Arc<dyn DynamicValueMemory>)
            .map_err(wasmtime::Error::new)
    }
}

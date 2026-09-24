//! One set of refundable reservations and one audit owner across clock admission.
use super::{CapabilityCallCost, ProviderCall, Work, WorkLifetime};
use crate::broker::{
    busy, capacity, denied, error,
    session::{HandleEntry, SessionCore},
    CapabilitySession, GuestCapabilityHandle, HostClock, Kind,
};
use latent_core::{BudgetDimension, PlatformError, PlatformErrorCode};
use latent_policy::capability::ResourceTarget;
use std::{
    sync::{atomic::Ordering, Arc},
    time::{Duration, Instant},
};
use zeroize::Zeroizing;

pub(in crate::broker) struct PendingWork {
    core: Arc<SessionCore>,
    row: Arc<HandleEntry>,
    clock: HostClock,
    work: Option<Work>,
    entered: bool,
}

impl PendingWork {
    pub(in crate::broker) fn new(
        session: &CapabilitySession,
        handle: GuestCapabilityHandle,
        clock: HostClock,
    ) -> Result<Self, PlatformError> {
        Ok(Self {
            core: Arc::clone(&session.core),
            row: session.row(handle)?,
            clock,
            work: None,
            entered: false,
        })
    }

    pub(in crate::broker) const fn entered(&self) -> bool {
        self.entered
    }

    pub(in crate::broker) fn deadline(&self) -> Option<Instant> {
        self.work.as_ref().map(|work| work.deadline)
    }

    pub(in crate::broker) fn attempt(&mut self) -> Result<(), PlatformError> {
        debug_assert!(!self.entered);
        let core = &self.core;
        let row = &self.row;
        let live = core.owner.live.try_read().map_err(|_| busy())?;
        let binding = &core.plan.bindings[row.binding];
        let installed = binding.provider.live.try_read().map_err(|_| busy())?;
        let state = core.state.try_lock().map_err(|_| busy())?;
        core.check()?;
        if !*live
            || !*installed
            || row.operation != self.clock.operation()
            || row.resource.target() != ResourceTarget::Clock
            || binding.provider.capability != self.clock.capability()
            || state
                .slots
                .get(usize::from(row.id.wire_parts().0))
                .and_then(Option::as_ref)
                .is_none_or(|current| !Arc::ptr_eq(current, row))
        {
            return Err(denied());
        }
        if core.owner.limits.maximum_output_bytes < 8
            || core.stats.calls.load(Ordering::Acquire)
                >= core.owner.limits.maximum_calls_per_session
        {
            return Err(capacity());
        }
        let decision = core.decision(
            row.binding,
            self.clock.operation(),
            ResourceTarget::Clock,
            0,
            8,
        )?;
        // Waiting never converts the clock's synchronous audit contract into
        // a required-journal dispatch or bypasses a required-audit policy.
        if decision.requires_audit() {
            return Err(error(
                PlatformErrorCode::PermissionDenied,
                "capability-required-audit-path",
            ));
        }
        let cost = CapabilityCallCost::new(8).with_charge(BudgetDimension::CpuFuel, 100)?;
        cost.validate_minimum(
            self.clock.operation(),
            &binding.provider.minimum_call_charges,
        )?;
        let policy_deadline = core
            .owner
            .clock
            .monotonic_now()
            .checked_add(Duration::from_millis(decision.ceiling().wall_time_millis))
            .ok_or_else(capacity)?;
        let deadline = core
            .deadline
            .monotonic()
            .map_or(policy_deadline, |d| d.min(policy_deadline));
        if core.owner.clock.monotonic_now() >= deadline {
            return Err(error(
                PlatformErrorCode::DeadlineExceeded,
                "capability-call-deadline",
            ));
        }
        if self.work.is_none() {
            self.work = Some(Self::reserve(core, row, self.clock, cost, deadline)?);
        }
        let work = self.work.as_mut().expect("pending clock work");
        work.deadline = work.deadline.min(deadline);
        core.plan.with_routes(&mut || {
            core.owner.policies.with_current_dependencies(
                &decision,
                core.plan.dependencies_for(row.binding),
                &mut |_, _| {
                    if self.entered {
                        return Err(denied());
                    }
                    self.entered = true;
                    core.check()?;
                    if core.owner.clock.monotonic_now() >= work.deadline {
                        return Err(error(
                            PlatformErrorCode::DeadlineExceeded,
                            "capability-call-deadline",
                        ));
                    }
                    if let Some(reservation) = work.pending_budget.take() {
                        reservation
                            .commit()
                            .map_err(|error| error.to_platform_error())?;
                    }
                    work.lifetime.active = true;
                    core.stats.calls.fetch_add(1, Ordering::AcqRel);
                    core.stats
                        .buffer_bytes
                        .fetch_add(work.lifetime.buffer_bytes, Ordering::AcqRel);
                    Ok(())
                },
            )
        })
    }

    fn reserve(
        core: &Arc<SessionCore>,
        row: &Arc<HandleEntry>,
        clock: HostClock,
        cost: CapabilityCallCost,
        deadline: Instant,
    ) -> Result<Work, PlatformError> {
        let call_slot = core.owner.counters.acquire(Kind::Call, 1)?;
        let result = core.owner.counters.acquire(Kind::Result, 1)?;
        let input_bytes = core.owner.counters.acquire(Kind::Buffer, 0)?;
        let output_bytes = core.owner.counters.acquire(Kind::Buffer, 8)?;
        let metadata = core.owner.counters.acquire(
            Kind::Metadata,
            if core.owner.audit.is_some() {
                16384
            } else {
                4096
            },
        )?;
        let pending_budget = cost.reserve(&core.budget)?;
        let id = crate::broker::session::next_incarnation()?;
        let audit = if core.owner.audit.is_some() {
            crate::broker::audit::CallAudit::prepare(
                core,
                row.binding,
                clock.operation(),
                ResourceTarget::Clock,
                crate::broker::audit::request_digest(
                    clock.operation(),
                    ResourceTarget::Clock,
                    &[],
                    None,
                ),
                false,
                id,
            )?
        } else {
            None
        };
        Ok(Work {
            audit,
            required_audit: false,
            input_size: 0,
            pending_budget,
            input: Zeroizing::new(Vec::new()),
            row: Arc::clone(row),
            session: Arc::clone(core),
            id,
            deadline,
            maximum_output_bytes: 8,
            stream_budget: None,
            input_bytes,
            output_bytes,
            result,
            metadata,
            lifetime: WorkLifetime {
                stats: Arc::clone(&core.stats),
                active: false,
                buffer_bytes: 8,
                _slot: call_slot,
            },
        })
    }

    pub(in crate::broker) fn finish(mut self) -> ProviderCall {
        debug_assert!(self.entered);
        let mut call = ProviderCall {
            work: self.work.take(),
        };
        call.dispatched();
        call
    }
}

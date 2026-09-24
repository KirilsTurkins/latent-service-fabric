//! One bounded row owner across pre-publication clock currentness contention.
use super::*;
use crate::broker::HostClock;

pub(in crate::broker) struct PendingBinding {
    core: Arc<SessionCore>,
    clock: HostClock,
    row: Option<Arc<HandleEntry>>,
    entered: bool,
    observed: bool,
}

impl PendingBinding {
    pub(in crate::broker) fn new(session: &CapabilitySession, clock: HostClock) -> Self {
        Self {
            core: Arc::clone(&session.core),
            clock,
            row: None,
            entered: false,
            observed: false,
        }
    }

    pub(in crate::broker) const fn entered(&self) -> bool {
        self.entered
    }

    pub(in crate::broker) fn attempt(&mut self) -> Result<GuestCapabilityHandle, PlatformError> {
        debug_assert!(!self.entered);
        let core = &self.core;
        let live = core.owner.live.try_read().map_err(|_| busy())?;
        if !*live {
            return Err(denied());
        }
        let index = core
            .plan
            .bindings
            .iter()
            .position(|binding| binding.provider.capability == self.clock.capability())
            .ok_or_else(denied)?;
        let binding = &core.plan.bindings[index];
        let installed = binding.provider.live.try_read().map_err(|_| busy())?;
        if !*installed {
            return Err(denied());
        }
        let mut state = core.state.try_lock().map_err(|_| busy())?;
        core.check()?;
        if core.stats.handles.load(Ordering::Acquire) - usize::from(self.row.is_some())
            >= core.owner.limits.maximum_handles_per_session
        {
            return Err(capacity());
        }
        let slot = match &self.row {
            Some(row) => usize::from(row.id.slot),
            None => state
                .slots
                .iter()
                .position(Option::is_none)
                .ok_or_else(capacity)?,
        };
        if state.slots.get(slot).is_none_or(Option::is_some) {
            return Err(denied());
        }
        let decision = core.decision(index, self.clock.operation(), ResourceTarget::Clock, 0, 0)?;
        if self.row.is_none() {
            let charge = core.owner.counters.acquire(Kind::Handle, 1)?;
            let metadata = core.owner.counters.acquire(Kind::Metadata, 8192)?;
            let id = GuestCapabilityHandle {
                slot: u16::try_from(slot).map_err(|_| capacity())?,
                incarnation: next_incarnation()?,
            };
            // This retained row is a physical per-session owner even before
            // publication. Charge it once; no handle is usable until the fence.
            core.stats.handles.fetch_add(1, Ordering::AcqRel);
            self.row = Some(Arc::new(HandleEntry {
                id,
                binding: index,
                operation: self.clock.operation().into(),
                resource: ResourceRequest::Clock,
                _metadata: metadata,
                _slot: charge,
                lifetime: HandleLifetime {
                    stats: Arc::clone(&core.stats),
                    counted: AtomicBool::new(true),
                },
            }));
        }
        let row = self.row.as_ref().expect("pending clock row");
        core.plan.with_routes(&mut || {
            core.owner.policies.with_current_dependencies(
                &decision,
                core.plan.dependencies_for(index),
                &mut |_, _| {
                    // A callback entered by any fence, even one returning Busy
                    // after its callback, must never be entered a second time.
                    if self.entered {
                        return Err(denied());
                    }
                    self.entered = true;
                    core.check()?;
                    state.slots[slot] = Some(Arc::clone(row));
                    Ok(())
                },
            )
        })?;
        Ok(row.id)
    }

    pub(in crate::broker) fn observe(
        &mut self,
        result: &Result<GuestCapabilityHandle, PlatformError>,
    ) {
        debug_assert!(!self.observed);
        self.observed = true;
        crate::broker::audit::observe_grant(
            &self.core,
            self.clock.capability(),
            self.clock.operation(),
            ResourceTarget::Clock,
            result,
        );
    }

    pub(in crate::broker) fn observe_failure(&mut self, failure: PlatformError) -> PlatformError {
        let result = Err(failure);
        self.observe(&result);
        result.expect_err("original clock admission failure")
    }
}

impl Drop for PendingBinding {
    fn drop(&mut self) {
        if !self.observed {
            self.observe(&Err(stopped()));
        }
        if let Some(row) = &self.row {
            if row.lifetime.counted.load(Ordering::Acquire) {
                let mut state = self
                    .core
                    .state
                    .lock()
                    .unwrap_or_else(std::sync::PoisonError::into_inner);
                if let Some(slot) = state.slots.get_mut(usize::from(row.id.slot)) {
                    if slot
                        .as_ref()
                        .is_some_and(|current| Arc::ptr_eq(current, row))
                    {
                        *slot = None;
                    }
                }
            }
        }
    }
}

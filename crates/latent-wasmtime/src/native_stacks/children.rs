//! Conservative child capacity through actual Store destruction.
//! Wasmtime caches worker fibers and stacks across logical child completion.
//! No guest completion flag, join or thread handle refunds this capacity.
use super::*;
use latent_core::activation_runtime::RuntimeToken;

pub(super) struct Children {
    retained: Vec<Permit>,
    started: Vec<RuntimeToken>,
    pub(super) pending: Option<Permit>,
    accepted: usize,
    maximum: usize,
}

impl Children {
    pub(super) fn new(maximum: usize) -> Result<Self, PlatformError> {
        let mut retained = Vec::new();
        retained
            .try_reserve_exact(maximum)
            .map_err(|_| failure("native-child-table-allocation"))?;
        let mut started = Vec::new();
        started
            .try_reserve_exact(maximum)
            .map_err(|_| failure("native-child-task-table-allocation"))?;
        Ok(Self {
            retained,
            started,
            pending: None,
            accepted: 0,
            maximum,
        })
    }
    pub(super) fn retained_count(&self) -> usize {
        self.retained.len() + usize::from(self.pending.is_some())
    }
    pub(super) fn release_after_store_dropped(&mut self) {
        drop(self.pending.take());
        self.retained.clear();
        self.started.clear();
    }
}

impl StackContext {
    pub(crate) fn reserve_child(&self, continuation: RuntimeToken) -> Result<(), PlatformError> {
        let mut children = self
            .children
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        // A guest can copy its token or reset a context's started byte. Each
        // distinct native child still needs a distinct admitted original Task;
        // logical settlement cannot make an earlier start reusable.
        if children.started.contains(&continuation) {
            return Err(crate::containment::platform_error(
                PlatformErrorCode::InvalidArgument,
                "native-child-task-already-started",
                false,
            ));
        }
        // Finite total starts, not a misleading reusable logical-thread count.
        // A previous start may have reused a cached worker without consuming its
        // pending stack permit. Retain it until actual Store destruction.
        if children.accepted >= children.maximum {
            return Err(crate::containment::platform_error(
                PlatformErrorCode::ResourceExhausted,
                "native-child-total-start-capacity",
                false,
            ));
        }
        let owner = self
            .runtime
            .register_from_task(OwnerKind::Native, continuation)?;
        let memory = self
            .budget
            .reserve_host_memory(self.mapped as u64)
            .map_err(|error| error.to_platform_error())?;
        if let Some(pending) = children.pending.take() {
            children.retained.push(pending);
        }
        children.pending = Some(Permit {
            _owner: owner,
            memory,
        });
        children.started.push(continuation);
        children.accepted += 1;
        Ok(())
    }

    /// Host-only: the invoking future has returned and its actual Store has
    /// already been dropped. No guest import exposes this release operation.
    pub(crate) fn after_store_dropped(&self) -> Result<(), PlatformError> {
        if self.active.load(Ordering::Acquire) != 0
            || self.retirement_failed.load(Ordering::Acquire)
        {
            return Err(failure("native-stack-retirement-unproven"));
        }
        self.children
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner)
            .release_after_store_dropped();
        self.try_retire();
        if self.physically_retired() {
            Ok(())
        } else {
            Err(failure("native-stack-retirement-unproven"))
        }
    }
}

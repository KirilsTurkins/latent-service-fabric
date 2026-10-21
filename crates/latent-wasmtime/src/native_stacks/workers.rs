//! Engine-owned async fibers share the original Native and memory ceilings.
//! This path is selected only while canonical thread creation stays disabled.
use super::*;
use latent_core::activation_runtime::RuntimeToken;

pub(super) struct Workers {
    parents: Vec<RuntimeToken>,
    maximum: usize,
}

impl Workers {
    pub(super) fn new(maximum: usize, root: RuntimeToken) -> Result<Self, PlatformError> {
        let mut parents = Vec::new();
        parents
            .try_reserve_exact(maximum)
            .map_err(|_| failure("native-worker-table-allocation"))?;
        parents.push(root);
        Ok(Self { parents, maximum })
    }
}

impl StackContext {
    pub(super) fn admit_worker(&self) -> wasmtime::Result<Permit> {
        let workers = self
            .workers
            .as_ref()
            .ok_or_else(|| wasmtime::Error::msg("native-stack-prestart-admission-required"))?;
        let mut workers = workers
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if self.finalization_requested.load(Ordering::Acquire)
            || workers.parents.len() >= workers.maximum
        {
            return Err(wasmtime::Error::msg("native-worker-admission-closed"));
        }
        let parent = workers
            .parents
            .first()
            .copied()
            .ok_or_else(|| wasmtime::Error::msg("native-worker-live-parent-required"))?;
        // The current poll belongs to this exact activation. No caller supplies
        // a parent or capacity, and no guest C thread can reach this profile.
        let owner = self
            .runtime
            .register(OwnerKind::Native, Some(parent))
            .map_err(|_| wasmtime::Error::msg("native-worker-original-native-limit"))?;
        let memory = self
            .budget
            .reserve_host_memory(self.mapped as u64)
            .map_err(|_| wasmtime::Error::msg("native-worker-original-memory-limit"))?;
        let mut metadata = self
            .budget
            .reserve_host_memory(CHILD_METADATA_ESCROW as u64)
            .map_err(|_| wasmtime::Error::msg("native-worker-original-metadata-limit"))?;
        // Vector storage was admitted before context allocation. Every actual
        // mapping has a separate Native owner and metadata reservation.
        workers.parents.push(owner.token());
        metadata.confirm();
        Ok(Permit {
            _owner: owner,
            _worker_metadata: Some(metadata),
            memory,
        })
    }

    pub(super) fn release_worker_parent(&self, token: RuntimeToken) {
        if let Some(workers) = &self.workers {
            workers
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .parents
                .retain(|parent| *parent != token);
        }
    }

    pub(super) fn worker_parents_empty(&self) -> bool {
        self.workers.as_ref().is_none_or(|workers| {
            workers
                .lock()
                .unwrap_or_else(std::sync::PoisonError::into_inner)
                .parents
                .is_empty()
        })
    }
}

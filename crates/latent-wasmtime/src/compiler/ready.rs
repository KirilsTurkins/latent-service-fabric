use std::sync::{Arc, Mutex};

use latent_core::PlatformError;

use super::{capacity_error, CompilerObserver};

pub(super) struct ReadyGate {
    maximum_count: usize,
    maximum_metadata: usize,
    maximum_image: usize,
    state: Mutex<(usize, usize, usize)>,
    metrics: CompilerObserver,
}

impl ReadyGate {
    pub(super) fn new(
        count: usize,
        metadata: usize,
        image: usize,
        metrics: CompilerObserver,
    ) -> Arc<Self> {
        Arc::new(Self {
            maximum_count: count,
            maximum_metadata: metadata,
            maximum_image: image,
            state: Mutex::new((0, 0, 0)),
            metrics,
        })
    }

    pub(super) fn reserve(self: &Arc<Self>) -> Result<ReadyPermit, PlatformError> {
        let mut state = self
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if state.0 >= self.maximum_count {
            self.metrics
                .update(|state| state.ready_rejected = state.ready_rejected.saturating_add(1));
            return Err(capacity_error("preparation-ready-capacity"));
        }
        state.0 += 1;
        self.metrics
            .update(|snapshot| snapshot.ready_preparations = state.0 as u64);
        drop(state);
        self.metrics.notify();
        Ok(ReadyPermit {
            gate: Arc::clone(self),
            metadata: 0,
            image: 0,
        })
    }
}

pub(crate) struct ReadyPermit {
    gate: Arc<ReadyGate>,
    metadata: usize,
    image: usize,
}

impl ReadyPermit {
    pub(super) fn charge(mut self, metadata: usize, image: usize) -> Result<Self, PlatformError> {
        // Includes the immutable runtime and the caller's descriptor/import copy.
        let metadata = metadata
            .checked_mul(2)
            .ok_or_else(|| capacity_error("preparation-ready-bytes"))?;
        let mut state = self
            .gate
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if metadata > self.gate.maximum_metadata.saturating_sub(state.1)
            || image > self.gate.maximum_image.saturating_sub(state.2)
        {
            self.gate
                .metrics
                .update(|state| state.ready_rejected = state.ready_rejected.saturating_add(1));
            drop(state);
            return Err(capacity_error("preparation-ready-bytes"));
        }
        state.1 += metadata;
        state.2 += image;
        self.metadata = metadata;
        self.image = image;
        self.gate.metrics.update(|snapshot| {
            snapshot.ready_metadata_bytes = state.1 as u64;
            snapshot.ready_compiled_image_bytes = state.2 as u64;
        });
        drop(state);
        Ok(self)
    }
}

impl Drop for ReadyPermit {
    fn drop(&mut self) {
        let mut state = self
            .gate
            .state
            .lock()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        state.0 -= 1;
        state.1 -= self.metadata;
        state.2 -= self.image;
        self.gate.metrics.update(|snapshot| {
            snapshot.ready_preparations = state.0 as u64;
            snapshot.ready_metadata_bytes = state.1 as u64;
            snapshot.ready_compiled_image_bytes = state.2 as u64;
        });
        drop(state);
        self.gate.metrics.notify();
    }
}

pub(crate) struct ReadyPin<T> {
    pub(crate) runtime: Arc<T>,
    pub(crate) permit: ReadyPermit,
}

//! Original global startup admission precedes native allocation and exposure.
use std::sync::Arc;
use std::time::Instant;

use latent_core::{
    native_capacity::{
        NativeAdmissionClass, NativeBufferClass, NativeBufferPermit, NativeCapacityOwner,
        NativeReservation, NativeReservationRequest,
    },
    ActivationClock, PlatformError,
};
use latent_effects::authority::EffectAuthorityOwner;
use latent_state::namespace::catalog::NamespaceCatalog;
use latent_state::protected_store::{ProtectedStoreOwner, ProtectedStoreStartupMemory};

use crate::config::NodeSettings;

/// These owners are moved through the actual standalone startup. An externally
/// supplied catalog must already have this exact authority's rejection observer;
/// exposure cannot be repaired by attaching a different owner afterwards.
pub(in crate::standalone) struct StateBootstrap {
    pub authority: EffectAuthorityOwner,
    pub native: NativeCapacityOwner,
    pub deadline: Instant,
    pub(super) clock: Arc<dyn ActivationClock>,
    memory: Option<ProtectedStoreStartupMemory>,
    configuration: [u8; 32],
    original: Arc<NativeReservation>,
    pub(super) opened_store: Option<Arc<ProtectedStoreOwner>>,
    pub(super) namespaces: Option<Arc<NamespaceCatalog>>,
    _application_memory: NativeBufferPermit,
}

impl StateBootstrap {
    pub fn new(
        settings: &NodeSettings,
        clock: &Arc<dyn ActivationClock>,
    ) -> Result<Option<Self>, PlatformError> {
        let Some(state) = &settings.state else {
            return Ok(None);
        };
        Self::new_state(state, clock).map(Some)
    }

    pub(super) fn new_state(
        state: &crate::config::state::StateSettings,
        clock: &Arc<dyn ActivationClock>,
    ) -> Result<Self, PlatformError> {
        // Derivation checks the resident footprint and separately usable recovery
        // headroom. Recheck actual worker/validator sizing before accepting any
        // allocation, including the fixed native owner and authority shells.
        let expected = state
            .store
            .startup_memory_bytes(crate::config::state::STARTUP_VALIDATOR_BYTES)
            .map_err(|_| super::unavailable())?
            .checked_add(crate::config::state::STARTUP_APPLICATION_BYTES)
            .and_then(|bytes| {
                bytes.checked_add(
                    EffectAuthorityOwner::retained_memory_bytes(
                        crate::config::state::EFFECT_AUTHORITY_MAXIMUM_RULES,
                    )
                    .ok()?,
                )
            })
            .ok_or_else(super::unavailable)?;
        if expected != state.startup_work_bytes {
            return Err(super::unavailable());
        }
        let deadline = clock
            .monotonic_now()
            .checked_add(state.startup_timeout)
            .ok_or_else(super::unavailable)?;
        let native = NativeCapacityOwner::with_clock(state.native, Arc::clone(clock))
            .map_err(|_| super::unavailable())?;
        let original = Arc::new(
            native
                .reserve(
                    NativeAdmissionClass::Recovery,
                    NativeReservationRequest {
                        work_bytes: state.startup_work_bytes,
                        ..NativeReservationRequest::default()
                    },
                    deadline,
                )
                .map_err(|_| super::unavailable())?,
        );
        let memory = ProtectedStoreStartupMemory::new(&native, Arc::clone(&original))
            .map_err(|_| super::unavailable())?;
        let application_memory = original
            .reserve_buffer(
                NativeBufferClass::Work,
                crate::config::state::STARTUP_APPLICATION_BYTES,
            )
            .map_err(|_| super::unavailable())?;
        // No rule is installed. Actual protected checkpoint/covered-clock
        // admission later supplies the floor; zero is only an empty lower bound.
        let authority = EffectAuthorityOwner::with_retained_capacity(
            crate::config::state::EFFECT_AUTHORITY_MAXIMUM_RULES,
            state.dispatcher.accepted_jobs,
            0,
            &native,
            Arc::clone(&original),
        )
        .map_err(|_| super::unavailable())?;
        let configuration = super::configuration::identity(state);
        Ok(Self {
            authority,
            native,
            deadline,
            clock: Arc::clone(clock),
            memory: Some(memory),
            configuration,
            original,
            opened_store: None,
            namespaces: None,
            _application_memory: application_memory,
        })
    }

    pub fn take_memory(&mut self) -> Result<ProtectedStoreStartupMemory, PlatformError> {
        self.original
            .with_live(|| ())
            .map_err(|_| super::unavailable())?;
        self.memory.take().ok_or_else(super::unavailable)
    }

    pub fn check_live(&self) -> Result<(), PlatformError> {
        self.original
            .with_live(|| ())
            .map_err(|_| super::unavailable())
    }

    pub(super) fn original(&self) -> Arc<NativeReservation> {
        Arc::clone(&self.original)
    }

    pub(in crate::standalone) fn matches(
        &self,
        settings: &crate::config::state::StateSettings,
    ) -> bool {
        self.configuration == super::configuration::identity(settings)
    }

    /// The initializer's actual buffers have retired before readiness is
    /// delivered. Reuse that prepaid Work for resident namespace metadata,
    /// retaining its charge on the same lifecycle owner as later handles.
    pub(super) fn open_namespaces(
        &mut self,
        settings: &crate::config::state::StateSettings,
    ) -> Result<Arc<NamespaceCatalog>, PlatformError> {
        self.check_live()?;
        if self.namespaces.is_some() || !self.matches(settings) {
            return Err(super::unavailable());
        }
        let store = self.opened_store.as_ref().ok_or_else(super::unavailable)?;
        let snapshot = store.snapshot().map_err(|_| super::unavailable())?;
        if snapshot.admission_closed
            || snapshot.quarantined
            || !store.uses_native_capacity(&self.native)
        {
            return Err(super::unavailable());
        }
        let catalog = Arc::new(
            NamespaceCatalog::with_retained_capacity(&self.native, self.original())
                .map_err(|_| super::unavailable())?,
        );
        self.check_live()?;
        self.namespaces = Some(Arc::clone(&catalog));
        Ok(catalog)
    }
}

impl Drop for StateBootstrap {
    fn drop(&mut self) {
        if let Some(namespaces) = &self.namespaces {
            // Closing is not retirement. Retained real handles/completions
            // keep their metadata and the original global charge until Drop.
            if namespaces.lifecycle().retire().is_err() {
                self.native.quarantine();
            }
        }
        // A detached boot future never leaves admission exposed. The store's
        // actual worker/engine owners retain their original physical permits;
        // a positive drain performed by the final runtime needs no quarantine.
        if let Some(store) = &self.opened_store {
            if store
                .snapshot()
                .map_or(true, |snapshot| !snapshot.physically_retired())
            {
                store.quarantine();
                self.native.quarantine();
                return;
            }
        }
        self.native.close();
    }
}

#[cfg(test)]
pub(super) mod tests;

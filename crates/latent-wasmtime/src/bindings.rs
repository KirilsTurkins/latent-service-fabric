//! Shared generated host bindings used by the Wasmtime backend.

use latent_component_bindings::host::echo as generated;

pub use generated::{exports, latent, Service};

/// Aggregate runtime-world host bindings for future generic host composition.
pub mod runtime {
    pub use latent_component_bindings::host::runtime::*;
}

use crate::host::HostState;

pub struct ServicePre<T: 'static> {
    inner: generated::ServicePre<T>,
}

impl<T: 'static> ServicePre<T> {
    pub fn new(instance_pre: wasmtime::component::InstancePre<T>) -> wasmtime::Result<Self> {
        Ok(Self {
            inner: generated::ServicePre::new(instance_pre)?,
        })
    }
}

impl ServicePre<HostState> {
    pub async fn instantiate_async(
        &self,
        store: &mut wasmtime::Store<HostState>,
    ) -> wasmtime::Result<Service> {
        self.inner.instantiate_async(store).await
    }
}

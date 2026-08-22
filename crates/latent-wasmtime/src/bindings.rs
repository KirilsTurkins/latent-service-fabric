//! Generated host bindings for the Phase 0 echo world.

mod generated {
    include!(concat!(env!("OUT_DIR"), "/echo_bindings.rs"));
}

pub use generated::{exports, latent, Service};

use crate::host::{hostcall_fuel_limit, HostState};

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
        let delegated_log_bytes =
            <HostState as generated::latent::context::context::Host>::remaining_budget(
                store.data_mut(),
            )
            .await
            .log_bytes;
        store.set_hostcall_fuel(hostcall_fuel_limit(usize::MAX, delegated_log_bytes));
        self.inner.instantiate_async(store).await
    }
}

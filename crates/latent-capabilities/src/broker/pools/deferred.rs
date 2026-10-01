//! Sealed deferred work shares the existing node provider ownership ledger.
use super::{IngressRequest, PlatformError, ProviderClient, ProviderPools};
use latent_effects::authority::DispatchGrant;
use std::{future::Future, sync::Arc, time::Instant};

/// One finite physical request accepted from the dispatcher. This cannot mint a
/// guest session or select a tenant/provider using untrusted event fields.
pub struct DeferredRequest {
    request: IngressRequest,
    grant: DispatchGrant,
}

impl ProviderPools {
    pub fn deferred<T: Send + 'static>(
        &self,
        client: &Arc<ProviderClient<T>>,
        grant: DispatchGrant,
        maximum_operations: usize,
        memory_bytes: usize,
    ) -> Result<DeferredRequest, PlatformError> {
        if grant.profile().provider != client.core.epoch.logical_id {
            return Err(super::denied());
        }
        // The same bounded tenant/request/running slots and prepaid memory as
        // node ingress are retained through real socket and buffer destruction.
        let request = self.ingress(
            client,
            &grant.scope().tenant,
            grant.deadline(),
            maximum_operations,
            memory_bytes,
        )?;
        Ok(DeferredRequest { request, grant })
    }
}

impl DeferredRequest {
    #[must_use]
    pub fn grant(&self) -> &DispatchGrant {
        &self.grant
    }

    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        self.request.checkpoint()
    }

    #[must_use]
    pub fn deadline(&self) -> Instant {
        self.request.deadline()
    }

    pub fn begin_operation(&self) -> Result<(), PlatformError> {
        self.request.begin_operation()
    }

    pub async fn wait_for<F: Future>(&self, future: F) -> Result<F::Output, PlatformError> {
        self.request.wait_for(future).await
    }
}

impl<T: Send + 'static> ProviderClient<T> {
    pub fn checkout_deferred(
        self: &Arc<Self>,
        request: &DeferredRequest,
    ) -> Result<Option<super::PooledConnection<T>>, PlatformError> {
        self.checkout_ingress(&request.request)
    }

    pub fn reserve_deferred_connection(
        self: &Arc<Self>,
        request: &DeferredRequest,
    ) -> Result<super::ConnectionReservation<T>, PlatformError> {
        self.reserve_ingress_connection(&request.request)
    }
}

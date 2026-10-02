//! Sealed deferred work shares the existing node provider ownership ledger.
use super::{IngressRequest, MaintenanceRequest, PlatformError, ProviderClient, ProviderPools};
use latent_effects::authority::{DispatchGrant, DispatchPurpose};
use std::{future::Future, sync::Arc, time::Instant};

/// One finite physical request accepted from the dispatcher. This cannot mint a
/// guest session or select a tenant/provider using untrusted event fields.
pub struct DeferredRequest {
    request: Request,
    grant: DispatchGrant,
}

enum Request {
    Execute(IngressRequest),
    Reconcile(MaintenanceRequest),
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
        let request = match grant.purpose() {
            DispatchPurpose::Execute => Request::Execute(self.ingress(
                client,
                &grant.scope().tenant,
                grant.deadline(),
                maximum_operations,
                memory_bytes,
            )?),
            // An original authenticated lookup uses the existing cleanup
            // ledger, with the same finite metadata/socket owner. It creates
            // no ingress, guest session, replacement pool or execution grant.
            DispatchPurpose::ReconcileOnly => Request::Reconcile(
                self.maintenance(client, grant.deadline(), 1)?
                    .begin_deferred_request(maximum_operations, memory_bytes)?,
            ),
        };
        Ok(DeferredRequest { request, grant })
    }
}

impl DeferredRequest {
    #[must_use]
    pub fn grant(&self) -> &DispatchGrant {
        &self.grant
    }

    pub fn checkpoint(&self) -> Result<(), PlatformError> {
        match &self.request {
            Request::Execute(request) => request.checkpoint(),
            Request::Reconcile(request) => request.checkpoint(),
        }
    }

    #[must_use]
    pub fn deadline(&self) -> Instant {
        match &self.request {
            Request::Execute(request) => request.deadline(),
            Request::Reconcile(request) => request.deadline(),
        }
    }

    pub fn begin_operation(&self) -> Result<(), PlatformError> {
        match &self.request {
            Request::Execute(request) => request.begin_operation(),
            Request::Reconcile(request) => request.begin_operation(),
        }
    }

    pub async fn wait_for<F: Future>(&self, future: F) -> Result<F::Output, PlatformError> {
        match &self.request {
            Request::Execute(request) => request.wait_for(future).await,
            Request::Reconcile(request) => request.wait_for(future).await,
        }
    }
}

impl<T: Send + 'static> ProviderClient<T> {
    pub fn checkout_deferred(
        self: &Arc<Self>,
        request: &DeferredRequest,
    ) -> Result<Option<super::PooledConnection<T>>, PlatformError> {
        match &request.request {
            Request::Execute(request) => self.checkout_ingress(request),
            Request::Reconcile(request) => {
                request.check_client(&self.core)?;
                // Maintenance sockets cannot borrow or become idle guest
                // connections; actual dial capacity remains shared and finite.
                Ok(None)
            }
        }
    }

    pub fn reserve_deferred_connection(
        self: &Arc<Self>,
        request: &DeferredRequest,
    ) -> Result<super::ConnectionReservation<T>, PlatformError> {
        match &request.request {
            Request::Execute(request) => self.reserve_ingress_connection(request),
            Request::Reconcile(request) => self.reserve_maintenance_connection(request),
        }
    }
}

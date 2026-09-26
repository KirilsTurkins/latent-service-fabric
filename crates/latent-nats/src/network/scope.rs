use crate::{EventError, Result};
use latent_capabilities::broker::pools::{
    ConnectionReservation, IngressRequest, PoolCall, PooledConnection, ProviderClient,
};
use std::{future::Future, sync::Arc};

/// The protocol borrows an existing invocation or node ingress owner. Neither
/// branch creates a guest session, executor, new deadline or detached I/O task.
#[derive(Clone, Copy)]
pub(crate) enum Scope<'a> {
    Invocation(&'a PoolCall),
    Ingress(&'a IngressRequest),
}
impl<'a> From<&'a PoolCall> for Scope<'a> {
    fn from(call: &'a PoolCall) -> Self {
        Self::Invocation(call)
    }
}
impl<'a> From<&'a IngressRequest> for Scope<'a> {
    fn from(call: &'a IngressRequest) -> Self {
        Self::Ingress(call)
    }
}
impl Scope<'_> {
    pub(crate) fn checkpoint(self) -> Result<()> {
        match self {
            Self::Invocation(call) => call.io().checkpoint(),
            Self::Ingress(call) => call.checkpoint(),
        }
        .map_err(Into::into)
    }
    pub(crate) async fn wait_for<F: Future>(self, future: F) -> Result<F::Output> {
        match self {
            Self::Invocation(call) => call.io().wait_for(future).await,
            Self::Ingress(call) => call.wait_for(future).await,
        }
        .map_err(EventError::from)
    }
    pub(crate) fn checkout<T: Send + 'static>(
        self,
        client: &Arc<ProviderClient<T>>,
    ) -> Result<Option<PooledConnection<T>>> {
        match self {
            Self::Invocation(call) => client.checkout(call),
            Self::Ingress(call) => client.checkout_ingress(call),
        }
        .map_err(Into::into)
    }
    pub(crate) fn reserve<T: Send + 'static>(
        self,
        client: &Arc<ProviderClient<T>>,
    ) -> Result<ConnectionReservation<T>> {
        match self {
            Self::Invocation(call) => client.reserve_connection(call),
            Self::Ingress(call) => client.reserve_ingress_connection(call),
        }
        .map_err(Into::into)
    }
}

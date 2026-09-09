use std::sync::Arc;

use latent_core::{ActivationId, BoxFuture};
use latent_executor::ExecutionCancellationProbe;
use latent_scheduler::SchedulingCancellation;

use crate::{CancellationHandle, CancellationRegistration, CancellationToken};

use super::transport_stop::TransportStop;

/// One bounded probe shared by the scheduler and backend. Transport observation
/// never installs the registry's explicit-cancellation publication winner.
pub(super) struct ActivationControl {
    token: CancellationToken,
    cancellation: CancellationHandle,
    transport: Arc<TransportStop>,
}

impl ActivationControl {
    pub(super) fn new(
        registration: &CancellationRegistration,
        transport: Arc<TransportStop>,
    ) -> Self {
        Self {
            token: registration.token(),
            cancellation: registration.handle(),
            transport,
        }
    }

    pub(super) fn token(&self) -> &CancellationToken {
        &self.token
    }

    pub(super) fn transport(&self) -> &TransportStop {
        &self.transport
    }

    pub(super) fn stopped(&self) -> bool {
        self.token.is_cancelled() || self.transport.disconnected()
    }

    pub(super) fn reason(&self) -> Option<String> {
        self.token.reason().or_else(|| {
            self.transport
                .disconnected()
                .then(|| "activation transport disconnected".to_owned())
        })
    }
}

impl ExecutionCancellationProbe for ActivationControl {
    fn is_cancelled(&self) -> bool {
        self.stopped()
    }

    fn reason(&self) -> Option<String> {
        self.reason()
    }
}

impl SchedulingCancellation for ActivationControl {
    fn activation_id(&self) -> &ActivationId {
        self.token.activation_id()
    }

    fn is_cancelled(&self) -> bool {
        self.stopped()
    }

    fn request_cancellation(&self) -> bool {
        self.cancellation.cancel("scheduler cancellation")
    }

    fn cancelled(&self) -> BoxFuture<'_, ()> {
        Box::pin(async move {
            tokio::select! {
                biased;
                () = self.token.cancelled() => {},
                () = self.transport.disconnect() => {},
            }
        })
    }
}

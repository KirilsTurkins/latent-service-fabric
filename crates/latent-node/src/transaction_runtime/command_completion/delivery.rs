//! Current-purpose data delivery, independent of the durable disposition.
use std::sync::Arc;

use latent_capabilities::namespace::Mode;
use latent_commit::atomic::CommandRecord;
use latent_core::PlatformError;
use latent_state::{
    embedded::StoreError,
    namespace::catalog::NamespaceCatalog,
    session::{version::capture_view_identity, StateMode, StateScope},
    store_io::StoreIoKind,
};

use super::super::{authorization::denied, StateAuthorization, StateTransactionHost};

/// Retains the original caller, publication, namespace and cancellation gate.
/// This is not a grant, result receipt, commit permit or refreshed deadline.
pub struct ResultDeliveryFence {
    authorization: Arc<StateAuthorization>,
    operation: &'static str,
    command: Option<CommandRecord>,
}

impl std::fmt::Debug for ResultDeliveryFence {
    fn fmt(&self, output: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        output
            .debug_struct("ResultDeliveryFence")
            .field("operation", &self.operation)
            .finish_non_exhaustive()
    }
}
impl PartialEq for ResultDeliveryFence {
    fn eq(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.authorization, &other.authorization)
            && self.operation == other.operation
            && self.command == other.command
    }
}
impl Eq for ResultDeliveryFence {}

impl ResultDeliveryFence {
    pub(super) fn command(
        authorization: Arc<StateAuthorization>,
        command: &CommandRecord,
    ) -> Result<Self, PlatformError> {
        if authorization.authority_mode() != Mode::Inspection {
            return Err(denied());
        }
        authorization.accepts_record(command)?;
        let fence = Self {
            authorization,
            operation: "read-result",
            command: Some(command.clone()),
        };
        fence.with_current(0, || Ok(()))?;
        Ok(fence)
    }

    /// Invoke a short, non-I/O delivery action under current policy, namespace
    /// lifecycle and the original cancellation/deadline gate. A previous read
    /// decision or confirmed durable outcome never substitutes for this check.
    pub fn with_current<T>(
        &self,
        output_bytes: usize,
        action: impl FnOnce() -> Result<T, PlatformError>,
    ) -> Result<T, PlatformError> {
        if let Some(command) = &self.command {
            self.authorization.accepts_record(command)?;
        }
        let mut result = None;
        self.authorization
            .authorize(self.operation, 0, output_bytes, || {
                result = Some(action()?);
                Ok(())
            })?;
        result.ok_or_else(denied)
    }
}

impl StateTransactionHost {
    /// A fresh query can retain its actual admitted read authority for later
    /// response delivery. This opens no view and creates no command row.
    pub async fn query_delivery_fence(&self) -> Result<ResultDeliveryFence, PlatformError> {
        if self.authorization.authority_mode() != Mode::Query {
            return Err(denied());
        }
        self.authorization
            .authorize("query-info", 0, 0, || Ok(()))?;
        let authorization = Arc::clone(&self.authorization);
        let original = self.view_identity;
        let job = self
            .store
            .with_store(StoreIoKind::Read, 8192, move |store| {
                let view = store.snapshot()?;
                let ownership = authorization.authority.ownership();
                let scope = StateScope {
                    tenant: ownership.tenant.clone(),
                    namespace: latent_core::StateNamespaceId(ownership.namespace.clone()),
                    incarnation: ownership.incarnation,
                    state_schema: authorization.namespace.record().state_schema.clone(),
                    entity: ownership.entity.clone(),
                    mode: StateMode::Query,
                };
                let current =
                    capture_view_identity(&view, &scope).map_err(|error| match error {
                        latent_state::session::StateError::Corrupt => StoreError::Corrupt,
                        _ => StoreError::Unavailable,
                    })?;
                if current.namespace.incarnation != original.namespace.incarnation
                    || current.epochs != original.epochs
                {
                    return Err(StoreError::Unavailable);
                }
                NamespaceCatalog::read_in(&view, &scope.tenant, &scope.namespace)
                    .map_err(|_| StoreError::Unavailable)?
                    .ok_or(StoreError::Unavailable)
            })
            .map_err(super::errors::protected)?;
        let namespace = job
            .await
            .map_err(|_| {
                super::errors::atomic(latent_commit::atomic::AtomicError::RecoveryRequired)
            })?
            .map_err(super::errors::protected)?;
        let fence = ResultDeliveryFence {
            authorization: Arc::new(self.authorization.rebind_query_delivery(namespace)?),
            operation: "query-info",
            command: None,
        };
        fence.with_current(0, || Ok(()))?;
        Ok(fence)
    }
}
